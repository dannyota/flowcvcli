"""Core HTTP client: auth, session cookie jar, JSON envelope, re-login retry.

Feature mixins build on this interface:
  self.cfg                      -> Config
  self.resume_id                -> str (raises if unset)
  self.request(path, method="GET", body=None, query=None) -> dict envelope
  self.request_raw(path, query=None) -> (status:int, bytes)
  self.get_resume()             -> dict (data.resume), raises on failure
  self.now_iso()                -> ISO-8601 millisecond UTC timestamp string

`path` is relative to https://app.flowcv.com/api (e.g. "resumes/save_entry",
"auth/login"), or an absolute http(s) URL (e.g. the /pubcache template catalog).

Session handling: every request goes through a single `http.cookiejar.CookieJar`
behind an opener, so the client (a) sends *all* cookies the login set — not just
`flowcvsidapp` — and (b) automatically captures any `Set-Cookie` the server
returns mid-session (rotation). The full cookie set is persisted to
`.flowcv_session` (0o600). FlowCV rate-limits login (~100/day) and returns HTTP
429 when hammered; we surface that clearly rather than retrying into the wall.
"""
import datetime
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .config import Config, SESSION_FILE

API = "https://app.flowcv.com/api"
ORIGIN = "https://app.flowcv.com"
COOKIE_DOMAIN = "app.flowcv.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/149.0.0.0 Safari/537.36")


def now_iso():
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _multipart(fields):
    boundary = "----flowcvcli" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out += [f"--{boundary}", f'Content-Disposition: form-data; name="{k}"', "", v]
    out += [f"--{boundary}--", ""]
    return boundary, "\r\n".join(out).encode()


def _make_cookie(name, value):
    """Build a session cookie scoped to the FlowCV app domain."""
    return http.cookiejar.Cookie(
        version=0, name=name, value=value, port=None, port_specified=False,
        domain=COOKIE_DOMAIN, domain_specified=True, domain_initial_dot=False,
        path="/", path_specified=True, secure=True, expires=None, discard=False,
        comment=None, comment_url=None, rest={})


def _seed_jar(jar, cookie_str):
    """Load cookies from a 'name=value; name2=value2' header string into `jar`."""
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")   # split on first '=' (values may contain '=')
        name, value = name.strip(), value.strip()
        if name:
            jar.set_cookie(_make_cookie(name, value))


def _jar_header(jar):
    """Render a cookie jar as a 'name=value; …' Cookie header string."""
    return "; ".join(f"{c.name}={c.value}" for c in jar)


def _rate_limit_msg(method, path):
    return (f"{method} {path} -> HTTP 429 (rate limited by FlowCV). Too many "
            "requests in a short window — wait a while before retrying, and reuse "
            "the cached session (.flowcv_session / FLOWCV_COOKIE) instead of "
            "logging in repeatedly (login is capped at ~100/day).")


def login(email, password, jar=None):
    """POST /auth/login (multipart email+password) into a cookie jar.

    Seeds an anonymous session (init_user) then logs in on the *same* jar, so the
    jar ends up holding the full authenticated cookie set. Returns the jar
    (creating a fresh one if not supplied). Raises SystemExit with a clear message
    on a 429 rate-limit or a failed login.
    """
    if jar is None:
        jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = {"user-agent": UA, "origin": ORIGIN, "accept": "application/json, text/plain, */*"}

    # Seed an anonymous session like the web app does — but login also works
    # standalone (the browser's curl skips this), so a throttled/failed init_user
    # must NOT abort a login that would otherwise succeed. Best-effort only.
    try:
        opener.open(urllib.request.Request(f"{API}/auth/init_user", headers=base), timeout=30).read()
    except urllib.error.HTTPError:
        pass
    except urllib.error.URLError as e:
        raise SystemExit(f"login (init_user) -> network error: {e.reason}")

    boundary, body = _multipart({"email": email, "password": password,
                                 "resumeData": "undefined", "letterData": "undefined",
                                 "resumeImg": "", "letterImg": ""})
    h = dict(base, **{"content-type": f"multipart/form-data; boundary={boundary}"})
    try:
        resp = opener.open(
            urllib.request.Request(f"{API}/auth/login", data=body, headers=h, method="POST"), timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SystemExit(_rate_limit_msg("POST", "auth/login"))
        raise SystemExit(f"login failed: HTTP {e.code} {e.read()[:200]!r}")
    except urllib.error.URLError as e:
        raise SystemExit(f"login -> network error: {e.reason}")
    data = json.loads(resp.read().decode())
    if not data.get("success"):
        # whitelist error/code only — the raw envelope can echo the account email
        raise SystemExit(f"login failed (code {data.get('code')}): {data.get('error') or 'check email/password'}")
    if not any(c.name == "flowcvsidapp" for c in jar):
        raise SystemExit("login succeeded but no session cookie was set")
    return jar


def _write_session(cookie):
    """Persist the session cookie header with owner-only perms (0o600) — it's a credential."""
    parent = os.path.dirname(SESSION_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(cookie)


class Client:
    def __init__(self, config=None, resume_id=None):
        self.cfg = config or Config.load()
        if resume_id:
            self.cfg.resume_id = resume_id
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))
        self._authed = False      # has the jar been seeded yet?
        self._persisted = None    # last cookie header written to .flowcv_session

    # ---- auth -------------------------------------------------------------
    def _ensure_auth(self):
        """Seed the cookie jar once, in priority order: FLOWCV_COOKIE (env) ->
        cached .flowcv_session -> a fresh login(). Idempotent."""
        if self._authed:
            return
        if self.cfg.cookie:
            _seed_jar(self._jar, self.cfg.cookie)
            self._authed = True
            return
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE) as f:
                cached = f.read().strip()
            if cached:
                _seed_jar(self._jar, cached)
                self._persisted = cached
                self._authed = True
                return
        if self.cfg.email and self.cfg.password:
            login(self.cfg.email, self.cfg.password, self._jar)
            self._persist()
            self._authed = True
            return
        raise SystemExit("No auth. Set FLOWCV_COOKIE, or FLOWCV_EMAIL + "
                         "FLOWCV_PASSWORD, in .env.")

    def cookie(self):
        """Current Cookie header (all session cookies). For multipart uploads that
        build their own request instead of going through `_send`."""
        self._ensure_auth()
        return _jar_header(self._jar)

    def _persist(self):
        header = _jar_header(self._jar)
        _write_session(header)
        self._persisted = header

    def _maybe_persist(self):
        """Re-persist if the server rotated the session (Set-Cookie changed the
        jar). Never shadow an authoritative env cookie with a session file."""
        if self.cfg.cookie:
            return
        header = _jar_header(self._jar)
        if header and header != self._persisted:
            _write_session(header)
            self._persisted = header

    def relogin(self):
        """Discard the current session and log in fresh (only if we have creds).

        Clears the jar first so a stale/duplicate cookie can't shadow the new
        session — "a fresh login() session" the way the web app starts one.
        """
        if not (self.cfg.email and self.cfg.password):
            return False
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass
        self._jar.clear()
        login(self.cfg.email, self.cfg.password, self._jar)
        self._persist()
        self._authed = True
        return True

    @property
    def resume_id(self):
        """The target resume id. If none was configured, auto-use the account's
        only resume; if there are several, require an explicit choice."""
        if self.cfg.resume_id:
            return self.cfg.resume_id
        env = self.request("resumes/all")
        resumes = (env.get("data") or {}).get("resumes") if env.get("success") else None
        if resumes is None:
            raise SystemExit("Could not list resumes to auto-select one — set "
                             "FLOWCV_RESUME_ID or pass --resume-id.")
        if not resumes:
            raise SystemExit("This account has no resumes yet.")
        if len(resumes) == 1:
            self.cfg.resume_id = resumes[0].get("id")   # cache for the rest of the run
            return self.cfg.resume_id
        listing = "\n".join(f"  {r.get('id')}  {r.get('title') or '(untitled)'}" for r in resumes)
        raise SystemExit("You have multiple resumes — choose one with --resume-id <id> "
                         "or FLOWCV_RESUME_ID:\n" + listing)

    def now_iso(self):
        return now_iso()

    # ---- http -------------------------------------------------------------
    def _url(self, path):
        return path if path.startswith("http") else f"{API}/{path}"

    def _send(self, path, method, body, query, timeout):
        self._ensure_auth()                       # jar carries the cookies; opener attaches them
        url = self._url(path)
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"accept": "application/json, text/plain, */*", "user-agent": UA,
                   "origin": ORIGIN}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError as e:   # DNS/conn/TLS/timeout
            raise SystemExit(f"{method} {url} -> network error: {e.reason}")

    def request(self, path, method="GET", body=None, query=None, timeout=30):
        """Return the parsed JSON envelope dict. Retries once after re-login on 401/403."""
        status, raw = self._send(path, method, body, query, timeout)
        if status in (401, 403) and self.relogin():
            status, raw = self._send(path, method, body, query, timeout)
        if status == 429:
            raise SystemExit(_rate_limit_msg(method, path))
        self._maybe_persist()
        try:
            return json.loads(raw.decode())
        except ValueError:
            raise SystemExit(f"{method} {path} -> HTTP {status}: {raw[:200]!r}")

    def request_raw(self, path, query=None, timeout=120):
        """Return (status, bytes). For binary endpoints (PDF download)."""
        status, raw = self._send(path, "GET", None, query, timeout)
        if status in (401, 403) and self.relogin():
            status, raw = self._send(path, "GET", None, query, timeout)
        if status == 429:
            raise SystemExit(_rate_limit_msg("GET", path))
        self._maybe_persist()
        return status, raw

    # ---- resume fetch -----------------------------------------------------
    def get_resume(self):
        """Return the full resume object (data.resume). Raises on failure.

        A freshly minted session can return `400 reloadClient:true` on its first
        heavy read and then succeed; retry once on that signal before giving up.
        """
        env = self.request(f"resumes/{self.resume_id}")
        if not env.get("success") and env.get("reloadClient"):
            env = self.request(f"resumes/{self.resume_id}")   # session-warmup retry
        if not env.get("success"):
            raise SystemExit(f"get resume failed (code {env.get('code')}): {env.get('error') or ''} "
                             "(session expired? refresh FLOWCV_COOKIE or re-login)")
        return env["data"]["resume"]

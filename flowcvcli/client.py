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
import contextlib
import copy
import datetime
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .config import Config, SESSION_FILE
from .errors import ApiError, AuthError, RateLimitError

API = "https://app.flowcv.com/api"
ORIGIN = "https://app.flowcv.com"
COOKIE_DOMAIN = "app.flowcv.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/149.0.0.0 Safari/537.36")

# The web app always carries an `appVersion` build-hash cookie and an `i18n`
# locale cookie, and the API expects them on requests, so we send them on login
# and persist them with the session. (They are NOT what fixes the login 429 —
# that's the TLS fingerprint; see `_impersonated_login`.)
#
# `appVersion` is a build hash that changes on every FlowCV deploy, so we DON'T
# hard-code it: we GET the app root and capture the `Set-Cookie: appVersion=...`
# the server emits (exactly how the browser gets it). The constant below is only
# a last-resort fallback if that fetch fails; FLOWCV_APP_VERSION overrides both.
APP_VERSION_FALLBACK = "a66cb813d07308dcd4b0332278e3f9a2fcef0bb5"
I18N_COOKIE = os.environ.get("FLOWCV_I18N", "en|vn")


def fetch_app_version():
    """GET the app root and return the current `appVersion` build hash.

    The browser obtains `appVersion` from the Set-Cookie on the first page load;
    we mirror that so the value is always current rather than pinned to a stale
    build hash. Returns the captured value, or None if the fetch failed. This is
    a plain GET (not the login POST), so it isn't subject to the WAF throttling.
    """
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        opener.open(urllib.request.Request(ORIGIN + "/", headers={"user-agent": UA}),
                    timeout=30).read()
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    for c in jar:
        if c.name == "appVersion":
            return c.value
    return None


def resolve_app_version():
    """The appVersion to send on login: env override > live fetch > pinned fallback."""
    return (os.environ.get("FLOWCV_APP_VERSION")
            or fetch_app_version()
            or APP_VERSION_FALLBACK)


def _impersonated_login(email, password, send_cookies):
    """POST /auth/login with a Chrome TLS fingerprint; return (status, body, cookies).

    FlowCV's edge fingerprints the TLS ClientHello (JA3) and throttles Python's
    `ssl` stack on the login endpoint — every stdlib client (urllib, http.client)
    gets an application-level HTTP 429, while curl and real browsers from the SAME
    ip/headers/cookies/moment are accepted. Verified end to end: byte-identical
    headers+ordering via http.client 429s, and Python login even WITH a valid
    session cookie 429s, while a browser fetch with that same session 200s. So the
    fix is to present a browser TLS fingerprint, which `curl_cffi` does in pure
    Python (libcurl-impersonate) — no subprocess, no system curl.

    `send_cookies` is the {name: value} cookie dict to send (appVersion/i18n).
    Returns (status, response_text, {name: value} of cookies the server set).
    Raises ImportError if curl_cffi is not installed (the caller surfaces it).
    """
    from curl_cffi import requests as _cffi   # lazy: only login needs it

    boundary, body = _multipart({"email": email, "password": password,
                                 "resumeData": "undefined", "letterData": "undefined",
                                 "resumeImg": "", "letterImg": ""})
    r = _cffi.post(
        ORIGIN + "/api/auth/login",
        headers={"accept": "application/json, text/plain, */*",
                 "content-type": f"multipart/form-data; boundary={boundary}",
                 "origin": ORIGIN},
        cookies=send_cookies, data=body, impersonate="chrome", timeout=60)
    return r.status_code, r.text, dict(r.cookies)


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


def _retry_after_seconds(headers):
    """Seconds to wait from a `Retry-After` response header, or None to give up.

    Honors only the integer-seconds form; the RFC 7231 HTTP-date form is treated
    as unparseable (None). Caps the wait at 60s — a longer, missing, negative, or
    non-integer value returns None so the caller raises instead of stalling.
    Case-insensitive so it works over a urllib header map or a plain test dict.
    """
    value = None
    for name, val in (headers or {}).items():
        if name.lower() == "retry-after":
            value = val
            break
    if value is None:
        return None
    try:
        secs = int(str(value).strip())
    except ValueError:
        return None
    return secs if 0 <= secs <= 60 else None


def login(email, password, jar=None):
    """Authenticate and load the full session cookie set into a cookie jar.

    FlowCV's edge fingerprints the TLS ClientHello (JA3) and throttles Python's
    `ssl` on the login endpoint — every stdlib client (urllib, http.client) gets
    an application-level HTTP 429, while curl and real browsers from the SAME
    ip/headers/cookies/moment are accepted. Verified empirically: byte-identical
    headers+ordering via http.client 429s, Python login even WITH a valid session
    cookie 429s, and a browser fetch with that same session 200s. So we send the
    login POST with a Chrome TLS fingerprint via curl_cffi (see
    `_impersonated_login`) and capture the session cookies. Every OTHER call stays
    on urllib — only the login endpoint is fingerprint-gated.

    Returns the jar (creating a fresh one if not supplied), populated with the
    session cookie plus the `appVersion`/`i18n` cookies the API expects on every
    later request. Raises RateLimitError on a 429 and AuthError on a missing
    curl_cffi or a failed login.
    """
    if jar is None:
        jar = http.cookiejar.CookieJar()

    # Browser-style cookies the API expects: live appVersion build-hash + locale.
    appver = resolve_app_version()
    jar.set_cookie(_make_cookie("i18n", I18N_COOKIE))
    jar.set_cookie(_make_cookie("appVersion", appver))

    try:
        status, info, set_cookies = _impersonated_login(
            email, password, {"i18n": I18N_COOKIE, "appVersion": appver})
    except ImportError:
        raise AuthError(
            "login needs the 'curl_cffi' package: FlowCV throttles Python's TLS "
            "fingerprint on the login endpoint, and curl_cffi presents a browser "
            "one. Install it (`pip install curl_cffi`), or set FLOWCV_COOKIE to a "
            "session cookie captured from a logged-in browser.")
    if status == 429:
        raise RateLimitError(_rate_limit_msg("POST", "auth/login"))
    if status != 200:
        raise AuthError(f"login failed: HTTP {status} {info[:200]!r}")
    try:
        data = json.loads(info)
    except ValueError:
        data = {}
    if data and not data.get("success"):
        raise AuthError(f"login failed (code {data.get('code')}): "
                        f"{data.get('error') or 'check email/password'}")

    for name, value in set_cookies.items():
        jar.set_cookie(_make_cookie(name, value))
    if not any(c.name == "flowcvsidapp" for c in jar):
        raise AuthError("login succeeded but no session cookie was set")
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
        self._last_headers = {}   # response headers of the most recent _send (429 Retry-After)
        self._batch_depth = 0     # >0 while inside batch(): get_resume() is cached
        self._batch_cache = None  # the one fetched resume shared across a batch

    # ---- auth -------------------------------------------------------------
    def _ensure_auth(self):
        """Seed the cookie jar once, in priority order: FLOWCV_COOKIE (env) ->
        cached .flowcv_session -> a fresh login(). Idempotent."""
        if self._authed:
            return
        if self.cfg.cookie:
            _seed_jar(self._jar, self.cfg.cookie)
            if not any(c.name == "flowcvsidapp" for c in self._jar):
                raise AuthError(
                    "FLOWCV_COOKIE has no flowcvsidapp cookie — paste the full "
                    "name=value pair from DevTools "
                    "(FLOWCV_COOKIE=flowcvsidapp=s%3A...), not just the value.")
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
        raise AuthError("No auth. Set FLOWCV_COOKIE, or FLOWCV_EMAIL + "
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
        if self.cfg.cookie:
            print("warning: logged in fresh because FLOWCV_COOKIE was rejected — "
                  "remove the stale cookie from .env so the cached session is "
                  "reused (login is capped at ~100/day).", file=sys.stderr)
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
            raise ApiError("Could not list resumes to auto-select one — set "
                           "FLOWCV_RESUME_ID or pass --resume-id.")
        if not resumes:
            raise ApiError("This account has no resumes yet.")
        if len(resumes) == 1:
            self.cfg.resume_id = resumes[0].get("id")   # cache for the rest of the run
            return self.cfg.resume_id
        listing = "\n".join(f"  {r.get('id')}  {r.get('title') or '(untitled)'}" for r in resumes)
        raise ApiError("You have multiple resumes — choose one with --resume-id <id> "
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
        # Stash the response headers on self (not a wider return tuple) so the
        # 429 Retry-After handling can read them without changing _send's shape.
        try:
            with self._opener.open(req, timeout=timeout) as r:
                self._last_headers = dict(r.headers)
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            self._last_headers = dict(e.headers or {})
            return e.code, e.read()
        except urllib.error.URLError as e:   # DNS/conn/TLS/timeout
            raise ApiError(f"{method} {url} -> network error: {e.reason}")

    def _auth_rescues(self):
        """Recovery steps for a 401/403, cheapest first. Yields True after loading
        a new auth source into the jar (the caller then retries the request), and
        ends with a fresh login — the expensive step (capped at ~100/day).

        When the seed was a stale FLOWCV_COOKIE, the cached session file written
        by an earlier login is often still valid, so it is tried before a login.
        """
        if self.cfg.cookie and os.path.exists(SESSION_FILE):
            with open(SESSION_FILE) as f:
                cached = f.read().strip()
            if cached and cached != _jar_header(self._jar):
                self._jar.clear()
                _seed_jar(self._jar, cached)
                self._persisted = cached
                print("warning: FLOWCV_COOKIE was rejected (401) — trying the "
                      "cached session instead; remove the stale FLOWCV_COOKIE "
                      "from .env.", file=sys.stderr)
                yield True
        yield self.relogin()

    def _send_rescued(self, path, method, body, query, timeout):
        """_send plus the shared error handling: auth rescue on 401/403 (cached
        session, then re-login), one polite 429 Retry-After retry, and re-persist."""
        status, raw = self._send(path, method, body, query, timeout)
        if status in (401, 403):
            for rescued in self._auth_rescues():
                if not rescued:
                    continue
                status, raw = self._send(path, method, body, query, timeout)
                if status not in (401, 403):
                    break
        if status == 429:
            # Honor a short `Retry-After` with exactly one retry; a missing /
            # unparseable / >60s header means don't wait — raise straight away.
            delay = _retry_after_seconds(self._last_headers)
            if delay is None:
                raise RateLimitError(_rate_limit_msg(method, path))
            time.sleep(delay)
            status, raw = self._send(path, method, body, query, timeout)
            if status == 429:
                raise RateLimitError(_rate_limit_msg(method, path))
        self._maybe_persist()
        return status, raw

    def request(self, path, method="GET", body=None, query=None, timeout=30):
        """Return the parsed JSON envelope dict (see _send_rescued for retries)."""
        if method != "GET":
            self._batch_cache = None   # a write may change structure; force a refetch
        status, raw = self._send_rescued(path, method, body, query, timeout)
        try:
            return json.loads(raw.decode())
        except ValueError:
            raise ApiError(f"{method} {path} -> HTTP {status}: {raw[:200]!r}")

    def request_raw(self, path, query=None, timeout=120):
        """Return (status, bytes). For binary endpoints (PDF download)."""
        return self._send_rescued(path, "GET", None, query, timeout)

    # ---- resume fetch -----------------------------------------------------
    @contextlib.contextmanager
    def batch(self):
        """Fetch the resume at most once for a burst of reads (fewer GETs).

        Inside the `with`, `get_resume()` caches its first result and reuses it, so
        N reads cost 1 GET against the rate-limited API; any write (a non-GET
        `request`) invalidates the cache and the next read refetches. Each read
        still returns an independent deep copy, so a caller mutating the result
        can't poison the cache. Reentrant: nested batches share one cache and only
        the outermost exit clears it. Outside a batch there is no caching (behavior
        is exactly as before).
        """
        self._batch_depth += 1
        try:
            yield self
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                self._batch_cache = None

    def get_resume(self):
        """Return the full resume object (data.resume). Raises on failure.

        Inside a `batch()` the resume is fetched once and reused (see `batch`);
        every call returns a fresh deep copy so callers can mutate it freely.
        """
        if self._batch_depth:
            if self._batch_cache is None:
                self._batch_cache = self._fetch_resume()
            return copy.deepcopy(self._batch_cache)
        return self._fetch_resume()

    def _fetch_resume(self):
        """GET the resume envelope and unwrap data.resume.

        A freshly minted session can return `400 reloadClient:true` on its first
        heavy read and then succeed; retry once on that signal before giving up.
        """
        env = self.request(f"resumes/{self.resume_id}")
        if not env.get("success") and env.get("reloadClient"):
            env = self.request(f"resumes/{self.resume_id}")   # session-warmup retry
        if not env.get("success"):
            raise ApiError(f"get resume failed (code {env.get('code')}): {env.get('error') or ''} "
                           "(session expired? refresh FLOWCV_COOKIE or re-login)")
        return env["data"]["resume"]

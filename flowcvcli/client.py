"""Core HTTP client: auth, session caching, JSON envelope, 401 re-login retry.

Feature mixins build on this interface:
  self.cfg                      -> Config
  self.resume_id                -> str (raises if unset)
  self.request(path, method="GET", body=None, query=None) -> dict envelope
  self.request_raw(path, query=None) -> (status:int, bytes)
  self.get_resume()             -> dict (data.resume), raises on failure
  self.now_iso()                -> ISO-8601 millisecond UTC timestamp string

`path` is relative to https://app.flowcv.com/api (e.g. "resumes/save_entry",
"auth/login"), or an absolute http(s) URL (e.g. the /pubcache template catalog).
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


def login(email, password):
    """POST /auth/login (multipart email+password) -> session cookie string."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = {"user-agent": UA, "origin": ORIGIN, "accept": "application/json, text/plain, */*"}
    opener.open(urllib.request.Request(f"{API}/auth/init_user", headers=base), timeout=30).read()
    boundary, body = _multipart({"email": email, "password": password,
                                 "resumeData": "undefined", "letterData": "undefined",
                                 "resumeImg": "", "letterImg": ""})
    h = dict(base, **{"content-type": f"multipart/form-data; boundary={boundary}"})
    resp = opener.open(urllib.request.Request(f"{API}/auth/login", data=body, headers=h, method="POST"), timeout=30)
    data = json.loads(resp.read().decode())
    if not data.get("success"):
        raise SystemExit(f"login failed: {json.dumps(data)[:200]}")
    cookie = "; ".join(f"{c.name}={c.value}" for c in jar if c.name == "flowcvsidapp")
    if "flowcvsidapp" not in cookie:
        raise SystemExit("login succeeded but no session cookie was set")
    return cookie


class Client:
    def __init__(self, config=None, resume_id=None):
        self.cfg = config or Config.load()
        if resume_id:
            self.cfg.resume_id = resume_id
        self._cookie = None  # resolved lazily

    # ---- auth -------------------------------------------------------------
    def cookie(self):
        if self._cookie:
            return self._cookie
        c = self.cfg.cookie
        if not c and os.path.exists(SESSION_FILE):
            c = open(SESSION_FILE).read().strip() or None
        if not c and self.cfg.email and self.cfg.password:
            c = login(self.cfg.email, self.cfg.password)
            with open(SESSION_FILE, "w") as f:
                f.write(c)
        if not c:
            raise SystemExit("No auth. Set FLOWCV_COOKIE, or FLOWCV_EMAIL + "
                             "FLOWCV_PASSWORD, in .env.")
        self._cookie = c
        return c

    def relogin(self):
        if not (self.cfg.email and self.cfg.password):
            return False
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass
        self._cookie = login(self.cfg.email, self.cfg.password)
        with open(SESSION_FILE, "w") as f:
            f.write(self._cookie)
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
        if len(resumes) == 1:
            self.cfg.resume_id = resumes[0]["id"]   # cache for the rest of the run
            return self.cfg.resume_id
        if not resumes:
            raise SystemExit("This account has no resumes yet.")
        listing = "\n".join(f"  {r.get('id')}  {r.get('title') or '(untitled)'}" for r in resumes)
        raise SystemExit("You have multiple resumes — choose one with --resume-id <id> "
                         "or FLOWCV_RESUME_ID:\n" + listing)

    def now_iso(self):
        return now_iso()

    # ---- http -------------------------------------------------------------
    def _url(self, path):
        return path if path.startswith("http") else f"{API}/{path}"

    def _send(self, path, method, body, query, timeout):
        url = self._url(path)
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"accept": "application/json, text/plain, */*", "user-agent": UA,
                   "cookie": self.cookie(), "origin": ORIGIN}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
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
        try:
            return json.loads(raw.decode())
        except ValueError:
            raise SystemExit(f"{method} {path} -> HTTP {status}: {raw[:200]!r}")

    def request_raw(self, path, query=None, timeout=120):
        """Return (status, bytes). For binary endpoints (PDF download)."""
        status, raw = self._send(path, "GET", None, query, timeout)
        if status in (401, 403) and self.relogin():
            status, raw = self._send(path, "GET", None, query, timeout)
        return status, raw

    # ---- resume fetch -----------------------------------------------------
    def get_resume(self):
        """Return the full resume object (data.resume). Raises on failure."""
        env = self.request(f"resumes/{self.resume_id}")
        if not env.get("success"):
            raise SystemExit(f"get resume failed: {json.dumps(env)[:200]} "
                             "(session expired? refresh FLOWCV_COOKIE)")
        return env["data"]["resume"]

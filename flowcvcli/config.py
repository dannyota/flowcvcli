"""Configuration: resolve resume id + auth from a dotenv file and env vars.

Dotenv search order (first match wins; later files fill in missing keys):
  1. ``$FLOWCV_ENV_FILE``  — an explicit path
  2. ``./.env``           — in the current working directory (where you run the tool)
  3. ``<config home>/.env`` — e.g. ``~/.config/flowcvcli/.env``

Real environment variables always override the dotenv file. The cached session
cookie (a credential) is written to ``<config home>/session`` with ``0600``
permissions, overridable via ``$FLOWCV_SESSION_FILE``. Paths are resolved from
the user's environment, never from the install location, so the tool behaves the
same whether it's run from source or ``pip install``-ed.
"""
import os

APP = "flowcvcli"


def _config_home():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP)


# Where the cached session cookie lives (override with $FLOWCV_SESSION_FILE).
SESSION_FILE = os.environ.get("FLOWCV_SESSION_FILE") or os.path.join(_config_home(), "session")


def _dotenv_files():
    paths = []
    if os.environ.get("FLOWCV_ENV_FILE"):
        paths.append(os.environ["FLOWCV_ENV_FILE"])
    paths.append(os.path.join(os.getcwd(), ".env"))
    paths.append(os.path.join(_config_home(), ".env"))
    return paths


def _load_dotenv():
    fv = {}
    for path in _dotenv_files():
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.rstrip("\r\n").strip()    # tolerate CRLF (.env edited on Windows)
                if line.startswith("export "):        # tolerate `export KEY=val`
                    line = line[len("export "):]
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)          # split first '='; cookie may contain '='
                    v = v.strip()
                    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                        v = v[1:-1]                    # drop surrounding quotes
                    fv.setdefault(k.strip(), v)        # first file wins per key
    return fv


def _pick(fv, *keys):
    for k in keys:
        v = os.environ.get(k) or fv.get(k)
        if v:
            return v
    return None


class Config:
    """Resolved auth + target resume. resume_id may be None for resume-list ops."""

    def __init__(self, resume_id=None, cookie=None, email=None, password=None):
        self.resume_id = resume_id
        self.cookie = cookie
        self.email = email
        self.password = password

    @classmethod
    def load(cls):
        fv = _load_dotenv()
        return cls(
            resume_id=_pick(fv, "FLOWCV_RESUME_ID", "RESUME_ID"),
            cookie=_pick(fv, "FLOWCV_COOKIE", "COOKIE"),
            email=_pick(fv, "FLOWCV_EMAIL", "EMAIL"),
            password=_pick(fv, "FLOWCV_PASSWORD", "PASSWORD"),
        )

    def require_resume_id(self):
        if not self.resume_id:
            raise SystemExit("No resume id. Set FLOWCV_RESUME_ID, pass resume_id=, "
                             "or use --resume-id. Run `flowcv resumes` to list them.")
        return self.resume_id

"""Configuration: resolve resume id + auth from .env / env vars."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_FILE = os.path.join(ROOT, ".flowcv_session")


def _load_dotenv():
    fv = {}
    for name in (".env", ".flowcv_env"):
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.rstrip("\r\n")            # tolerate CRLF (.env edited on Windows)
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)          # split first '='; cookie may contain '='
                    v = v.strip()
                    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                        v = v[1:-1]                    # drop surrounding quotes
                    fv.setdefault(k.strip(), v)
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
                             "or use --resume-id. Run `resumes` to list them.")
        return self.resume_id

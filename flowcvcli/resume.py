"""Resume-level operations: listing, create/duplicate/rename/delete, PDF
download, web-resume publish/status.

ResumeMixin is a pure mixin over Client (see client.py): no __init__, all
state lives on `self`. Write methods return the JSON envelope dict so callers
can check `env["success"]`.
"""
import datetime
import glob
import json
import os
import uuid

from .config import backups_dir
from .errors import ApiError

# Top-level resume fields that must NOT be copied into a new resume: server
# regenerates them (unique tokens / timestamps). `id` and `uuid` are reassigned.
_NEW_RESUME_DROP = ("webToken", "feedbackToken", "createdAt", "updatedAt", "lastChangeAt")

_BACKUP_KEEP = 20   # newest snapshots to retain per resume id (older pruned)


class ResumeMixin:
    # ---- listing ----------------------------------------------------------
    def list_resumes(self):
        """GET /resumes/all -> the list of resume summaries. Raises on failure."""
        env = self.request("resumes/all")
        if not env.get("success"):
            raise ApiError(f"list resumes failed: {env}")
        return env["data"]["resumes"]

    # ---- create / duplicate / rename / delete -----------------------------
    def _create_from(self, title, keep_content, src=None):
        """Create a new resume by cloning a full resume object.

        FlowCV's `create` needs a complete resume object (every NOT-NULL column),
        so we clone a valid one — `src` (defaults to the current resume) — then
        reassign a fresh id/uuid, drop the unique tokens (server regenerates), and
        set the title. `keep_content=False` makes a blank resume that keeps the
        same identity (personalDetails) and design (customization);
        `keep_content=True` is a full copy. Returns the new resume id.

        Verified live: the server IGNORES the client-supplied id and mints its
        own (returned in data.resume), so we must read the id back — trusting
        ours yields dead ids (every follow-up read 400s with reloadClient). The
        clone is also force-unpublished: cloning a live resume would otherwise
        instantly publish the copy under a fresh public token.
        """
        src = self.get_resume() if src is None else src
        clone = json.loads(json.dumps(src))    # deep copy
        new_id = str(uuid.uuid4())
        clone["id"] = new_id
        clone["uuid"] = str(uuid.uuid4())
        clone["title"] = title
        clone["webResumeLive"] = False
        for k in _NEW_RESUME_DROP:
            clone.pop(k, None)
        if not keep_content:
            clone["content"] = {}
        env = self.request("resumes/create", method="POST", body={"clientResume": clone})
        if not env.get("success"):
            raise ApiError(f"create resume failed: {json.dumps(env)[:200]}")
        created = (env.get("data") or {}).get("resume") or {}
        return created.get("id") or new_id

    def create_resume(self, title):
        """Create a new, empty resume (same contact details & styling, no content).
        Returns the new resume id."""
        return self._create_from(title, keep_content=False)

    def duplicate_resume(self, title=None):
        """Duplicate the current resume (content and all). Returns the new id."""
        if title is None:
            title = (self.get_resume().get("title") or "Resume") + " (copy)"
        return self._create_from(title, keep_content=True)

    # ---- backup / restore -------------------------------------------------
    def export_resume(self):
        """Return the full resume object (for a backup/snapshot)."""
        return self.get_resume()

    def import_resume(self, resume, title=None):
        """Restore a previously exported resume object into a NEW resume
        (non-destructive — the current resume is untouched). Returns the new id.
        """
        if title is None:
            title = (resume.get("title") or "Resume") + " (restored)"
        return self._create_from(title, keep_content=True, src=resume)

    # ---- local snapshots (auto-backup before destructive ops) -------------
    def snapshot(self, resume_id=None):
        """Save a timestamped JSON snapshot of a resume, returning the path.

        Used to guard destructive ops: export_resume() -> <state home>/flowcvcli/
        backups/<id>-<UTC yyyymmdd-HHMMSS>.json (dir 0o700, file 0o600), then prune
        to the newest _BACKUP_KEEP per id. Raises (ApiError) if the resume can't be
        fetched — the caller then aborts the destructive op instead of losing data.
        """
        rid = resume_id or self.resume_id
        blob = json.dumps(self.export_resume(), indent=2, ensure_ascii=False)
        d = backups_dir()
        os.makedirs(d, mode=0o700, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = os.path.join(d, f"{rid}-{ts}.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(blob)
        self._prune_backups(rid)
        return path

    def _prune_backups(self, resume_id):
        """Keep only the newest _BACKUP_KEEP snapshots for `resume_id`. Timestamp
        names are zero-padded, so lexical sort == chronological."""
        files = sorted(glob.glob(os.path.join(backups_dir(), f"{resume_id}-*.json")))
        for old in files[:-_BACKUP_KEEP]:
            try:
                os.remove(old)
            except OSError:
                pass

    def list_backups(self, all_resumes=False):
        """Snapshot files (path, size, mtime) for the current resume, or all."""
        pattern = "*.json" if all_resumes else f"{self.resume_id}-*.json"
        out = []
        for path in sorted(glob.glob(os.path.join(backups_dir(), pattern))):
            st = os.stat(path)
            out.append({"path": path, "size": st.st_size, "mtime": st.st_mtime})
        return out

    def rename_resume(self, title):
        """PATCH /resumes/rename_resume — set the resume's title."""
        return self.request("resumes/rename_resume", method="PATCH",
                            body={"resumeId": self.resume_id, "resumeTitle": title})

    def delete_resume(self, resume_id=None):
        """DELETE /resumes/delete_resume — permanently delete a resume.

        Defaults to the configured resume; pass an explicit id to delete another.
        Irreversible — the CLI guards this behind --yes.
        """
        rid = resume_id or self.resume_id
        return self.request("resumes/delete_resume", method="DELETE", query={"resumeId": rid})

    # ---- PDF --------------------------------------------------------------
    def download_pdf(self, pages=10):
        """GET /resumes/download -> PDF bytes. Raises unless a 200 + %PDF body."""
        status, raw = self.request_raw(
            "resumes/download",
            query={"resumeId": self.resume_id, "previewPageCount": pages},
        )
        if status != 200 or not raw.startswith(b"%PDF"):
            raise ApiError(f"download failed: HTTP {status}, {raw[:80]!r}")
        return raw

    def save_pdf(self, path, pages=10):
        """Download the resume PDF and write it to `path`; return `path`."""
        with open(path, "wb") as f:
            f.write(self.download_pdf(pages))
        return path

    def download_public(self, token):
        """Download ANY public/shared resume's PDF by its web token (no ownership needed)."""
        status, raw = self.request_raw("public/download_resume", query={"token": token})
        if status != 200 or not raw.startswith(b"%PDF"):
            raise ApiError(f"public download failed: HTTP {status}, {raw[:80]!r}")
        return raw

    # ---- web resume -------------------------------------------------------
    def publish(self):
        """PATCH /resumes/publish_web_resume to make the web resume public."""
        return self.request("resumes/publish_web_resume", method="PATCH",
                            body={"publish": True, "resumeId": self.resume_id})

    def unpublish(self):
        """PATCH /resumes/publish_web_resume to take the web resume offline."""
        return self.request("resumes/publish_web_resume", method="PATCH",
                            body={"publish": False, "resumeId": self.resume_id})

    def web_status(self):
        """Return {live, url} for the public web resume (url None if no token)."""
        r = self.get_resume()
        token = r.get("webToken")
        return {
            "live": r.get("webResumeLive"),
            "url": "https://flowcv.com/resume/" + token if token else None,
        }

    def share_url(self):
        """Return the public web-resume URL (or None if no webToken)."""
        return self.web_status()["url"]

"""Resume-level operations: listing, PDF download, web-resume publish/status.

ResumeMixin is a pure mixin over Client (see client.py): no __init__, all
state lives on `self`. Write methods return the JSON envelope dict so callers
can check `env["success"]`.
"""


class ResumeMixin:
    # ---- listing ----------------------------------------------------------
    def list_resumes(self):
        """GET /resumes/all -> the list of resume summaries. Raises on failure."""
        env = self.request("resumes/all")
        if not env.get("success"):
            raise SystemExit(f"list resumes failed: {env}")
        return env["data"]["resumes"]

    # ---- PDF --------------------------------------------------------------
    def download_pdf(self, pages=10):
        """GET /resumes/download -> PDF bytes. Raises unless a 200 + %PDF body."""
        status, raw = self.request_raw(
            "resumes/download",
            query={"resumeId": self.resume_id, "previewPageCount": pages},
        )
        if status != 200 or not raw.startswith(b"%PDF"):
            raise SystemExit(f"download failed: HTTP {status}, {raw[:80]!r}")
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
            raise SystemExit(f"public download failed: HTTP {status}, {raw[:80]!r}")
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

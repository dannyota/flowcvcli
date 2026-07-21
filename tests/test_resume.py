"""Resume create/duplicate/import: server-assigned ids and safe clone defaults."""
import json
import unittest

from flowcvcli.api import FlowCV
from flowcvcli.config import Config

SRC = {"id": "SRC", "uuid": "U", "title": "Mine", "webToken": "tok",
       "feedbackToken": "ftok", "createdAt": "c", "updatedAt": "u",
       "lastChangeAt": "l", "webResumeLive": True,
       "personalDetails": {"fullName": "D"},
       "customization": {"font": {}}, "content": {"work": {"entries": []}}}


class FakeFlowCV(FlowCV):
    """Serves a canned source resume and a scripted create response."""

    def __init__(self, create_env):
        super().__init__(config=Config(resume_id="SRC", cookie="flowcvsidapp=x"))
        self._create_env = create_env
        self.calls = []

    def get_resume(self):
        return json.loads(json.dumps(SRC))

    def request(self, path, method="GET", body=None, query=None, timeout=30):
        self.calls.append({"path": path, "method": method, "body": body})
        if path == "resumes/create":
            return self._create_env
        return {"success": True, "data": {}}


class CreateResumeTest(unittest.TestCase):
    def test_returns_the_server_assigned_id(self):
        # Verified live: the server ignores the client-side id and mints its own;
        # trusting ours produced dead ids (every follow-up 400s reloadClient).
        fc = FakeFlowCV({"success": True, "data": {"resume": {"id": "SERVER-ID"}}})
        self.assertEqual(fc.create_resume("New"), "SERVER-ID")

    def test_falls_back_to_the_client_id_when_response_has_none(self):
        fc = FakeFlowCV({"success": True, "data": {}})
        new_id = fc.create_resume("New")
        sent = fc.calls[-1]["body"]["clientResume"]
        self.assertEqual(new_id, sent["id"])

    def test_clone_is_not_published_and_drops_unique_tokens(self):
        # A duplicate of a LIVE resume must not go public under a fresh token.
        fc = FakeFlowCV({"success": True, "data": {"resume": {"id": "S"}}})
        fc.duplicate_resume("Copy")
        sent = fc.calls[-1]["body"]["clientResume"]
        self.assertFalse(sent["webResumeLive"])
        for k in ("webToken", "feedbackToken", "createdAt", "updatedAt", "lastChangeAt"):
            self.assertNotIn(k, sent)
        self.assertNotEqual(sent["id"], "SRC")
        self.assertEqual(sent["personalDetails"], {"fullName": "D"})

    def test_import_returns_the_server_id(self):
        fc = FakeFlowCV({"success": True, "data": {"resume": {"id": "S2"}}})
        self.assertEqual(fc.import_resume(json.loads(json.dumps(SRC))), "S2")


if __name__ == "__main__":
    unittest.main()

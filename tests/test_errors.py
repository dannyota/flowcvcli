"""The library exception hierarchy and its CLI/library boundaries (no network)."""
import json
import unittest
from unittest import mock

from flowcvcli.api import FlowCV
from flowcvcli.cli import main
from flowcvcli.client import Client, _jar_header
from flowcvcli.config import Config
from flowcvcli.errors import (ApiError, AuthError, FlowCVError, NotFoundError,
                              RateLimitError)


class HierarchyTest(unittest.TestCase):
    def test_every_subclass_is_a_flowcv_error_and_an_exception(self):
        for cls in (AuthError, RateLimitError, NotFoundError, ApiError):
            self.assertTrue(issubclass(cls, FlowCVError))
            self.assertTrue(issubclass(cls, Exception))


class ScriptedClient(Client):
    """Serves one scripted (status, body) response instead of hitting the network."""

    def __init__(self, config, script):
        super().__init__(config=config)
        self.script = list(script)

    def _send(self, path, method, body, query, timeout):
        self._ensure_auth()
        return self.script.pop(0)


class RaisesTest(unittest.TestCase):
    def test_429_raises_rate_limit_error(self):
        c = ScriptedClient(Config(resume_id="R1", cookie="flowcvsidapp=x"), [(429, b"")])
        with self.assertRaises(RateLimitError):
            c.request("resumes/all")

    def test_missing_entry_raises_not_found_error(self):
        fc = FlowCV(config=Config(resume_id="R1", cookie="flowcvsidapp=x"))
        resume = {"id": "R1", "content": {"publication": {"entries": [{"id": "E1"}]}}}
        with mock.patch.object(FlowCV, "get_resume", lambda self: json.loads(json.dumps(resume))):
            with self.assertRaises(NotFoundError):
                fc.find_entry(fc.get_resume(), "publication", "missing")


class CliBoundaryTest(unittest.TestCase):
    def test_library_error_becomes_sys_exit(self):
        with mock.patch("flowcvcli.cli.FlowCV") as FC:
            FC.return_value.set_date.side_effect = NotFoundError(
                "entry not found: publication/X")
            with self.assertRaises(SystemExit) as ctx:
                main(["date", "publication", "X", "--year", "2018"])
        self.assertIn("not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

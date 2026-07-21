"""429 Retry-After: one polite retry when the header allows, else raise (no network)."""
import unittest
from unittest import mock

from flowcvcli.client import Client
from flowcvcli.config import Config
from flowcvcli.errors import RateLimitError

OK = (200, b'{"success": true}')


class ScriptedClient(Client):
    """Serves scripted responses; a script item is (status, body) or
    (status, body, headers), the last exposed to the retry logic via _last_headers."""

    def __init__(self, config, script):
        super().__init__(config=config)
        self.script = list(script)
        self.sends = 0

    def _send(self, path, method, body, query, timeout):
        self._ensure_auth()
        self.sends += 1
        item = self.script.pop(0)
        if len(item) == 3:
            status, raw, headers = item
        else:
            status, raw = item
            headers = {}
        self._last_headers = headers
        return status, raw


def cfg():
    return Config(resume_id="R1", cookie="flowcvsidapp=x")


class RetryAfterTest(unittest.TestCase):
    def test_429_with_header_then_200_sleeps_once_and_succeeds(self):
        c = ScriptedClient(cfg(), [(429, b"", {"Retry-After": "2"}), OK])
        with mock.patch("flowcvcli.client.time.sleep") as sleep:
            env = c.request("resumes/all")
        self.assertTrue(env["success"])
        sleep.assert_called_once_with(2)
        self.assertEqual(c.sends, 2)                      # original + one retry

    def test_429_without_header_raises_immediately(self):
        c = ScriptedClient(cfg(), [(429, b"")])
        with mock.patch("flowcvcli.client.time.sleep") as sleep:
            with self.assertRaises(RateLimitError):
                c.request("resumes/all")
        sleep.assert_not_called()
        self.assertEqual(c.sends, 1)                      # never retried

    def test_429_with_header_over_60_raises_immediately(self):
        c = ScriptedClient(cfg(), [(429, b"", {"Retry-After": "120"})])
        with mock.patch("flowcvcli.client.time.sleep") as sleep:
            with self.assertRaises(RateLimitError):
                c.request("resumes/all")
        sleep.assert_not_called()
        self.assertEqual(c.sends, 1)

    def test_429_with_unparseable_header_raises_immediately(self):
        c = ScriptedClient(cfg(), [(429, b"", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})])
        with mock.patch("flowcvcli.client.time.sleep") as sleep:
            with self.assertRaises(RateLimitError):
                c.request("resumes/all")
        sleep.assert_not_called()
        self.assertEqual(c.sends, 1)

    def test_two_429s_raise_after_one_sleep(self):
        c = ScriptedClient(cfg(), [(429, b"", {"Retry-After": "1"}),
                                   (429, b"", {"Retry-After": "1"})])
        with mock.patch("flowcvcli.client.time.sleep") as sleep:
            with self.assertRaises(RateLimitError):
                c.request("resumes/all")
        sleep.assert_called_once_with(1)
        self.assertEqual(c.sends, 2)                      # retried exactly once

    def test_retry_after_is_case_insensitive(self):
        c = ScriptedClient(cfg(), [(429, b"", {"retry-after": "3"}), OK])
        with mock.patch("flowcvcli.client.time.sleep") as sleep:
            env = c.request("resumes/all")
        self.assertTrue(env["success"])
        sleep.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()

"""Client auth seeding, 401 rescue order, and envelope handling (no network)."""
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from flowcvcli.client import Client, _jar_header
from flowcvcli.config import Config
from flowcvcli.errors import ApiError, AuthError, RateLimitError


class ScriptedClient(Client):
    """Serves scripted (status, body) responses instead of hitting the network."""

    def __init__(self, config, script):
        super().__init__(config=config)
        self.script = list(script)
        self.sent = []          # (method, path, cookie-header-at-send-time)

    def _send(self, path, method, body, query, timeout):
        self._ensure_auth()
        self.sent.append((method, path, _jar_header(self._jar)))
        return self.script.pop(0)


def cookie_cfg(cookie="flowcvsidapp=live"):
    return Config(resume_id="R1", cookie=cookie)


class EnvCookieValidationTest(unittest.TestCase):
    def test_bare_cookie_value_is_rejected_with_guidance(self):
        c = ScriptedClient(Config(cookie="s%3Abare-value-no-name"), [])
        with self.assertRaises(AuthError) as ctx:
            c.cookie()
        self.assertIn("flowcvsidapp", str(ctx.exception))

    def test_full_cookie_pair_is_accepted(self):
        c = ScriptedClient(cookie_cfg(), [])
        self.assertIn("flowcvsidapp=live", c.cookie())


class AuthRescueTest(unittest.TestCase):
    def test_stale_env_cookie_falls_back_to_cached_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = os.path.join(tmp, "session")
            with open(session, "w") as f:
                f.write("flowcvsidapp=cached")
            c = ScriptedClient(cookie_cfg("flowcvsidapp=stale"),
                               [(401, b'{"success": false}'),
                                (200, b'{"success": true}')])
            with mock.patch("flowcvcli.client.SESSION_FILE", session), \
                 mock.patch.object(Client, "relogin",
                                   side_effect=AssertionError("relogin called")), \
                 contextlib.redirect_stderr(io.StringIO()) as err:
                env = c.request("resumes/all")
        self.assertTrue(env["success"])
        self.assertIn("flowcvsidapp=stale", c.sent[0][2])    # first try: env cookie
        self.assertIn("flowcvsidapp=cached", c.sent[1][2])   # retry: cached session
        self.assertIn("FLOWCV_COOKIE", err.getvalue())       # told the user why

    def test_relogin_is_the_last_resort(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = ScriptedClient(cookie_cfg("flowcvsidapp=stale"),
                               [(401, b'{"success": false}'),
                                (200, b'{"success": true}')])
            calls = []

            def fake_relogin(self):
                calls.append(1)
                return True

            with mock.patch("flowcvcli.client.SESSION_FILE",
                            os.path.join(tmp, "missing")), \
                 mock.patch.object(Client, "relogin", fake_relogin):
                env = c.request("resumes/all")
        self.assertTrue(env["success"])
        self.assertEqual(calls, [1])


class EnvelopeTest(unittest.TestCase):
    def test_429_raises_a_rate_limit_hint(self):
        c = ScriptedClient(cookie_cfg(), [(429, b"")])
        with self.assertRaises(RateLimitError) as ctx:
            c.request("auth/whatever")
        self.assertIn("429", str(ctx.exception))

    def test_non_json_body_raises_with_status(self):
        c = ScriptedClient(cookie_cfg(), [(500, b"<html>oops")])
        with self.assertRaises(ApiError) as ctx:
            c.request("resumes/all")
        self.assertIn("500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

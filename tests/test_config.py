"""Dotenv loading, tolerance, and precedence."""
import os
import tempfile
import unittest
from unittest import mock

from flowcvcli.config import Config


class DotenvTest(unittest.TestCase):
    def load_with(self, env_text, environ=None):
        """Load Config from an isolated dotenv file: cwd and XDG config home are
        pointed into a temp dir so the developer's real .env files can't leak in."""
        with tempfile.TemporaryDirectory() as tmp:
            envfile = os.path.join(tmp, "envfile")
            with open(envfile, "w") as f:
                f.write(env_text)
            clean = {"FLOWCV_ENV_FILE": envfile, "XDG_CONFIG_HOME": tmp}
            clean.update(environ or {})
            with mock.patch.dict(os.environ, clean, clear=True), \
                 mock.patch("flowcvcli.config.os.getcwd", return_value=tmp):
                return Config.load()

    def test_basic_keys(self):
        cfg = self.load_with("FLOWCV_EMAIL=a@b.c\nFLOWCV_PASSWORD=secret\n")
        self.assertEqual(cfg.email, "a@b.c")
        self.assertEqual(cfg.password, "secret")

    def test_quotes_export_crlf_and_embedded_equals(self):
        cfg = self.load_with('export FLOWCV_COOKIE="flowcvsidapp=a=b"\r\n')
        self.assertEqual(cfg.cookie, "flowcvsidapp=a=b")

    def test_comments_and_blank_lines_are_ignored(self):
        cfg = self.load_with("# comment\n\nFLOWCV_RESUME_ID=rid\n")
        self.assertEqual(cfg.resume_id, "rid")

    def test_real_environment_overrides_the_file(self):
        cfg = self.load_with("FLOWCV_EMAIL=file@x\n",
                             environ={"FLOWCV_EMAIL": "env@x"})
        self.assertEqual(cfg.email, "env@x")


class RequireResumeIdTest(unittest.TestCase):
    def test_missing_resume_id_raises_catchable_error(self):
        from flowcvcli.errors import ApiError
        with self.assertRaises(ApiError):
            Config().require_resume_id()

    def test_present_resume_id_is_returned(self):
        self.assertEqual(Config(resume_id="R1").require_resume_id(), "R1")


if __name__ == "__main__":
    unittest.main()

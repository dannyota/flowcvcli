"""`flowcv doctor`: first-run / auth diagnostics. All offline — the live check's
FlowCV is mocked, and config/session checks run against a temp dir + patched env
(same isolation pattern as tests/test_config.py)."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from flowcvcli.cli import main
from flowcvcli.errors import AuthError


class DoctorTest(unittest.TestCase):
    def run_doctor(self, argv, env=None, session_content=None, session_mode=0o600,
                   curl=True, fc=None):
        """Run `doctor` isolated: temp cwd/config home, patched env, mocked FlowCV.

        Returns (stdout, exit_code). exit_code is 0 unless the command sys.exits.
        """
        out = io.StringIO()
        code = 0
        with tempfile.TemporaryDirectory() as tmp:
            session_path = os.path.join(tmp, "session")
            if session_content is not None:
                fd = os.open(session_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, session_mode)
                with os.fdopen(fd, "w") as f:
                    f.write(session_content)
                os.chmod(session_path, session_mode)   # force exact perms past umask
            clean = {"XDG_CONFIG_HOME": tmp}
            clean.update(env or {})
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, clean, clear=True))
                stack.enter_context(mock.patch("flowcvcli.config.os.getcwd", return_value=tmp))
                stack.enter_context(mock.patch("flowcvcli.config.SESSION_FILE", session_path))
                stack.enter_context(mock.patch("flowcvcli.cli._curl_cffi_available", return_value=curl))
                if fc is not None:
                    stack.enter_context(mock.patch("flowcvcli.cli.FlowCV", return_value=fc))
                try:
                    with contextlib.redirect_stdout(out):
                        main(argv)
                except SystemExit as e:
                    code = e.code
        return out.getvalue(), code

    def _check(self, data, name):
        for c in data["checks"]:
            if c["name"] == name:
                return c
        self.fail(f"no check named {name!r} in {[c['name'] for c in data['checks']]}")

    def _json(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, f"expected 1 json line, got: {text!r}")
        return json.loads(lines[0])

    # ------------------------------------------------------------- all pass
    def test_all_pass(self):
        fc = mock.Mock()
        fc.list_resumes.return_value = [{"id": "R1", "title": "CV"}]
        fc.resume_id = "R1"
        out, code = self.run_doctor(
            ["--json", "doctor"], env={"FLOWCV_COOKIE": "flowcvsidapp=s%3Alive"},
            session_content="flowcvsidapp=s%3Alive", session_mode=0o600, fc=fc)
        data = self._json(out)
        self.assertEqual(code, 0)
        self.assertTrue(data["ok"])
        self.assertTrue(all(c["ok"] for c in data["checks"]))
        self.assertEqual(self._check(data, "live api")["detail"].startswith("auth valid"), True)

    def test_all_pass_human_lines(self):
        fc = mock.Mock()
        fc.list_resumes.return_value = [{"id": "R1"}]
        fc.resume_id = "R1"
        out, code = self.run_doctor(
            ["doctor"], env={"FLOWCV_COOKIE": "flowcvsidapp=x"},
            session_content="flowcvsidapp=x", fc=fc)
        self.assertEqual(code, 0)
        self.assertIn("ok", out)
        self.assertIn("summary:", out)
        self.assertNotIn("FAIL", out)

    # --------------------------------------------------------- bad cookie
    def test_bad_cookie_shape_fails(self):
        out, code = self.run_doctor(
            ["--json", "doctor", "--offline"],
            env={"FLOWCV_COOKIE": "s%3Ajust-a-value-no-name"})
        data = self._json(out)
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertFalse(self._check(data, "env cookie")["ok"])
        self.assertIn("flowcvsidapp", self._check(data, "env cookie")["detail"])

    # ------------------------------------------------- bad session perms
    def test_session_bad_perms_fail_with_chmod_hint(self):
        out, code = self.run_doctor(
            ["doctor", "--offline"], env={"FLOWCV_COOKIE": "flowcvsidapp=x"},
            session_content="flowcvsidapp=x", session_mode=0o644)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("chmod", out)
        self.assertIn("0644", out)

    def test_session_good_perms_json(self):
        out, code = self.run_doctor(
            ["--json", "doctor", "--offline"], env={"FLOWCV_COOKIE": "flowcvsidapp=x"},
            session_content="flowcvsidapp=x", session_mode=0o600)
        data = self._json(out)
        self.assertTrue(self._check(data, "session file")["ok"])

    # ------------------------------------------------------ offline skip
    def test_offline_skips_live_check(self):
        out, code = self.run_doctor(
            ["--json", "doctor", "--offline"], env={"FLOWCV_COOKIE": "flowcvsidapp=x"})
        data = self._json(out)
        self.assertEqual(code, 0)
        live = self._check(data, "live api")
        self.assertIsNone(live["ok"])
        self.assertEqual(live["detail"], "skipped")

    # ---------------------------------------------------- no auth at all
    def test_no_auth_source_fails(self):
        out, code = self.run_doctor(["--json", "doctor", "--offline"])
        data = self._json(out)
        self.assertEqual(code, 1)
        self.assertFalse(self._check(data, "auth source")["ok"])

    # ---------------------------------------------------- live auth fail
    def test_live_auth_failure_fails(self):
        fc = mock.Mock()
        fc.list_resumes.side_effect = AuthError("session expired")
        out, code = self.run_doctor(
            ["--json", "doctor"], env={"FLOWCV_COOKIE": "flowcvsidapp=x"}, fc=fc)
        data = self._json(out)
        self.assertEqual(code, 1)
        live = self._check(data, "live api")
        self.assertFalse(live["ok"])
        self.assertIn("session expired", live["detail"])

    # ------------------------------------------------- json shape / nulls
    def test_json_shape_and_null_for_skipped(self):
        out, _ = self.run_doctor(
            ["--json", "doctor", "--offline"], env={"FLOWCV_COOKIE": "flowcvsidapp=x"})
        data = self._json(out)
        self.assertEqual(set(data.keys()), {"checks", "ok"})
        for c in data["checks"]:
            self.assertEqual(set(c.keys()), {"name", "ok", "detail"})
        # a skipped check serializes ok as JSON null (Python None)
        self.assertIsNone(self._check(data, "live api")["ok"])


if __name__ == "__main__":
    unittest.main()

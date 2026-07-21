"""`flowcv edit`: open $EDITOR on an entry's rich text, save back on change.

`subprocess.call` is patched with fake editors (rewrite / leave / fail); the
FlowCV client is mocked. Offline, no network.
"""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from flowcvcli.markup import md_to_html
from flowcvcli import cli


ENTRY = {"id": "E1234567", "description": md_to_html("- one\n- two")}


def make_fc(entry=None):
    fc = mock.Mock()
    fc.get_resume.return_value = {"content": {}}
    fc.find_entry.return_value = dict(entry or ENTRY)
    fc.set_description.return_value = {"success": True}
    return fc


def rewrite(newmd):
    """A fake editor that overwrites the temp file with `newmd` and exits 0."""
    def _call(args):
        with open(args[-1], "w") as f:
            f.write(newmd)
        return 0
    return _call


def leave(args):
    """A fake editor that changes nothing (exit 0)."""
    return 0


def fail(args):
    """A fake editor that exits non-zero (user aborted)."""
    return 1


def run(argv, fc, call=leave, environ=None):
    out = io.StringIO()
    env = {"EDITOR": "fakeed"} if environ is None else environ
    with mock.patch("flowcvcli.cli.FlowCV", return_value=fc), \
         mock.patch.dict(os.environ, env, clear=True), \
         mock.patch("flowcvcli.cli.subprocess.call", side_effect=call):
        with contextlib.redirect_stdout(out):
            cli.main(argv)
    return out.getvalue()


class EditTest(unittest.TestCase):
    def test_change_saves_markdown_via_set_description(self):
        fc = make_fc()
        out = run(["edit", "work", "E1234567"], fc, call=rewrite("- three\n- four"))
        fc.set_description.assert_called_once()
        args, kwargs = fc.set_description.call_args
        # set_description is the md->html path; it receives the edited MARKDOWN
        self.assertEqual(args[0], "work")
        self.assertEqual(args[1], "E1234567")
        self.assertEqual(args[2], "- three\n- four")
        self.assertEqual(kwargs.get("field"), "description")
        self.assertIn("success=True", out)

    def test_no_change_short_circuits(self):
        fc = make_fc()
        out = run(["edit", "work", "E1234567"], fc, call=leave)
        fc.set_description.assert_not_called()
        self.assertEqual(out, "no changes.\n")

    def test_editor_failure_aborts(self):
        fc = make_fc()
        with self.assertRaises(SystemExit):
            run(["edit", "work", "E1234567"], fc, call=fail)
        fc.set_description.assert_not_called()

    def test_missing_editor_errors(self):
        fc = make_fc()
        with self.assertRaises(SystemExit):
            run(["edit", "work", "E1234567"], fc, environ={})
        fc.set_description.assert_not_called()

    def test_visual_is_a_fallback_for_editor(self):
        fc = make_fc()
        run(["edit", "work", "E1234567"], fc, call=rewrite("- x"),
            environ={"VISUAL": "fakeed"})
        fc.set_description.assert_called_once()

    def test_field_override(self):
        fc = make_fc({"id": "S1", "infoHtml": md_to_html("hi")})
        run(["edit", "skill", "S1", "--field", "infoHtml"], fc, call=rewrite("bye"))
        _args, kwargs = fc.set_description.call_args
        self.assertEqual(kwargs.get("field"), "infoHtml")

    def test_json_change_emits_envelope(self):
        fc = make_fc()
        out = run(["--json", "edit", "work", "E1234567"], fc, call=rewrite("- x"))
        self.assertEqual(json.loads(out), {"success": True})

    def test_json_no_change_emits_changed_false(self):
        fc = make_fc()
        out = run(["--json", "edit", "work", "E1234567"], fc, call=leave)
        self.assertEqual(json.loads(out), {"changed": False})


if __name__ == "__main__":
    unittest.main()

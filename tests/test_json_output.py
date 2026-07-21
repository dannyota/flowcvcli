"""`--json` global flag: default output stays byte-identical; `--json` emits
exactly one JSON document per command; library errors surface as a JSON object.

All offline: `flowcvcli.cli.FlowCV` is mocked, no network is touched.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from flowcvcli.cli import build_parser, main, md_to_html
from flowcvcli.errors import NotFoundError


def run(argv, fc=None):
    """Run main(argv) with FlowCV mocked; return captured stdout."""
    out = io.StringIO()
    with mock.patch("flowcvcli.cli.FlowCV") as m:
        if fc is not None:
            m.return_value = fc
        with contextlib.redirect_stdout(out):
            main(argv)
    return out.getvalue()


def make_fc(**returns):
    fc = mock.Mock()
    for name, value in returns.items():
        getattr(fc, name).return_value = value
    return fc


# ------------------------------------------------------------ parser wiring
class JsonFlagParsingTest(unittest.TestCase):
    def test_json_flag_before_and_after_subcommand(self):
        self.assertTrue(build_parser().parse_args(["--json", "resumes"]).json)
        self.assertTrue(build_parser().parse_args(["resumes", "--json"]).json)

    def test_json_defaults_off(self):
        # default=SUPPRESS: when --json is absent the attribute is unset, so the
        # CLI reads it via getattr(args, "json", False) -> off.
        args = build_parser().parse_args(["resumes"])
        self.assertFalse(getattr(args, "json", False))


# ----------------------------------------------- default output unchanged
class DefaultOutputByteIdenticalTest(unittest.TestCase):
    def test_resumes_default_unchanged(self):
        fc = make_fc(list_resumes=[
            {"id": "R1", "title": "My CV", "webToken": "tok1", "webResumeLive": True}])
        expected = f"  {'R1'}  {'My CV':20}  web:{'tok1'} [live]\n"
        self.assertEqual(run(["resumes"], fc), expected)

    def test_show_default_unchanged(self):
        fc = make_fc(get_resume={"content": {"work": {
            "displayName": "Experience", "entries": [
                {"id": "E1", "jobTitle": "Engineer", "startDateNew": "01/2020",
                 "endDateNew": "Present", "isHidden": False}]}}})
        expected = ("[work] 'Experience' (1 entries)\n"
                    "   E1  Engineer  01/2020–Present\n")
        self.assertEqual(run(["show"], fc), expected)

    def test_rm_default_unchanged(self):
        fc = make_fc(delete_entry={"success": True})
        self.assertEqual(run(["rm", "work", "E1234567"], fc),
                         "rm work/E1234567 -> success=True\n")

    def test_publish_default_unchanged(self):
        fc = make_fc(publish={"success": True},
                     share_url="https://flowcv.com/resume/tok1")
        self.assertEqual(run(["publish"], fc),
                         "publish -> success=True\n  https://flowcv.com/resume/tok1\n")


# ----------------------------------------------------- JSON output shapes
class JsonOutputShapeTest(unittest.TestCase):
    def _one_json(self, text):
        """Assert stdout is exactly one JSON document and return it parsed."""
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, f"expected 1 json line, got: {text!r}")
        return json.loads(lines[0])

    def test_resumes_json(self):
        fc = make_fc(list_resumes=[
            {"id": "R1", "title": "My CV", "webToken": "tok1", "webResumeLive": True},
            {"id": "R2", "title": None, "webToken": None, "webResumeLive": False}])
        data = self._one_json(run(["--json", "resumes"], fc))
        self.assertEqual(data, [
            {"id": "R1", "title": "My CV", "webToken": "tok1", "live": True},
            {"id": "R2", "title": None, "webToken": None, "live": False}])

    def test_show_json(self):
        fc = make_fc(get_resume={"content": {"work": {
            "displayName": "Experience", "entries": [
                {"id": "E1", "jobTitle": "Engineer", "startDateNew": "01/2020",
                 "endDateNew": "Present", "isHidden": True}]}}})
        data = self._one_json(run(["--json", "show"], fc))
        self.assertEqual(data, {"work": {"displayName": "Experience", "entries": [
            {"id": "E1", "label": "Engineer", "start": "01/2020",
             "end": "Present", "hidden": True}]}})

    def test_show_json_filtered_by_section(self):
        fc = make_fc(get_resume={"content": {
            "work": {"displayName": "Experience", "entries": []},
            "education": {"displayName": "Education", "entries": []}}})
        data = self._one_json(run(["--json", "show", "work"], fc))
        self.assertEqual(list(data.keys()), ["work"])

    def test_dump_json(self):
        entry = {"id": "E1", "jobTitle": "Engineer",
                 "description": "<p>Did <strong>things</strong></p>"}
        fc = make_fc(get_resume={}, find_entry=entry)
        data = self._one_json(run(["--json", "dump", "work", "E1"], fc))
        self.assertEqual(data["id"], "E1")
        self.assertEqual(data["jobTitle"], "Engineer")
        self.assertEqual(data["description"], "<p>Did <strong>things</strong></p>")
        self.assertEqual(data["_text"], "Did things")

    def test_new_json(self):
        fc = make_fc(create_resume="NEW123")
        data = self._one_json(run(["--json", "new", "Fresh"], fc))
        self.assertEqual(data, {"id": "NEW123", "success": True})

    def test_duplicate_json(self):
        fc = make_fc(duplicate_resume="DUP123")
        data = self._one_json(run(["--json", "duplicate"], fc))
        self.assertEqual(data, {"id": "DUP123", "success": True})

    def test_add_json(self):
        fc = make_fc(add_entry="ADD123")
        data = self._one_json(run(["--json", "add", "work", "--text", "hi"], fc))
        self.assertEqual(data, {"id": "ADD123", "success": True})

    def test_rm_envelope_json(self):
        fc = make_fc(delete_entry={"success": True, "data": {"n": 1}})
        data = self._one_json(run(["--json", "rm", "work", "E1"], fc))
        self.assertEqual(data, {"success": True, "data": {"n": 1}})

    def test_field_envelope_json(self):
        fc = make_fc(set_field={"success": False, "error": "nope"})
        data = self._one_json(run(["--json", "field", "work", "E1", "x", "--text", "y"], fc))
        self.assertEqual(data, {"success": False, "error": "nope"})

    def test_links_json(self):
        fc = make_fc(list_links=[
            ("github", "GitHub", "https://github.com/x", True),
            ("orcid", "ORCID", "https://orcid.org/y", False)])
        data = self._one_json(run(["--json", "links"], fc))
        self.assertEqual(data, [
            {"key": "github", "display": "GitHub", "link": "https://github.com/x", "shown": True},
            {"key": "orcid", "display": "ORCID", "link": "https://orcid.org/y", "shown": False}])

    def test_templates_json(self):
        fc = make_fc(list_templates=[
            {"id": "t1", "title": "Basic", "isPremium": False},
            {"templateId": "t2", "metaTitle": "Pro", "isPremium": True}])
        data = self._one_json(run(["--json", "templates"], fc))
        self.assertEqual(data, [
            {"id": "t1", "title": "Basic", "premium": False},
            {"id": "t2", "title": "Pro", "premium": True}])

    def test_share_json(self):
        fc = make_fc(web_status={"live": True, "url": "https://flowcv.com/resume/tok1"})
        data = self._one_json(run(["--json", "share"], fc))
        self.assertEqual(data, {"live": True, "url": "https://flowcv.com/resume/tok1"})

    def test_publish_json_single_envelope(self):
        fc = make_fc(publish={"success": True}, share_url="https://flowcv.com/resume/tok1")
        data = self._one_json(run(["--json", "publish"], fc))
        self.assertEqual(data, {"success": True})

    def test_md2html_json(self):
        data = self._one_json(run(["--json", "md2html", "--text", "**bold**"]))
        self.assertEqual(data, {"html": md_to_html("**bold**")})

    def test_export_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backup.json")
            fc = make_fc(export_resume={"title": "X", "content": {}})
            data = self._one_json(run(["--json", "export", "-o", path], fc))
            self.assertEqual(data["saved"], path)
            self.assertEqual(data["bytes"], os.path.getsize(path))
            self.assertGreater(data["bytes"], 0)

    def test_download_json_via_token(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.pdf")
            fc = make_fc(download_public=b"%PDF-1.4xx")
            data = self._one_json(run(["--json", "download", "--token", "T", "-o", path], fc))
            self.assertEqual(data, {"saved": path, "bytes": len(b"%PDF-1.4xx")})


# --------------------------------------------------------- error handling
class ErrorHandlingTest(unittest.TestCase):
    def test_error_json_shape(self):
        fc = make_fc()
        fc.list_resumes.side_effect = NotFoundError("resume 42 not found")
        out = io.StringIO()
        with mock.patch("flowcvcli.cli.FlowCV", return_value=fc):
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--json", "resumes"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(json.loads(out.getvalue()),
                         {"error": "resume 42 not found", "type": "NotFoundError"})

    def test_error_human_unchanged(self):
        fc = make_fc()
        fc.list_resumes.side_effect = NotFoundError("resume 42 not found")
        out = io.StringIO()
        with mock.patch("flowcvcli.cli.FlowCV", return_value=fc):
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as ctx:
                    main(["resumes"])
        self.assertEqual(ctx.exception.code, "resume 42 not found")
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

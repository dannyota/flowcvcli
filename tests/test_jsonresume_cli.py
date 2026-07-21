"""`export`/`import --format jsonresume` CLI wiring.

Offline: FlowCV is mocked. Plain `export`/`import` must stay unchanged; the
jsonresume forms go through to_jsonresume / from_jsonresume.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from flowcvcli.cli import build_parser, main
from flowcvcli.jsonresume import to_jsonresume, from_jsonresume


def make_fc(**returns):
    fc = mock.Mock()
    for name, value in returns.items():
        getattr(fc, name).return_value = value
    return fc


def run(argv, fc):
    out = io.StringIO()
    with mock.patch("flowcvcli.cli.FlowCV", return_value=fc):
        with contextlib.redirect_stdout(out):
            main(argv)
    return out.getvalue()


RESUME = {"id": "R1", "title": "My CV",
          "personalDetails": {"fullName": "Jane Doe", "jobTitle": "Eng",
                              "detailsOrder": []},
          "customization": {"font": {"fontFamily": "Rubik"}}, "content": {}}


class ExportJsonResumeTest(unittest.TestCase):
    def test_export_writes_jsonresume_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            fc = make_fc(export_resume=RESUME)
            run(["export", "--format", "jsonresume", "-o", path], fc)
            with open(path) as f:
                self.assertEqual(json.load(f), to_jsonresume(RESUME))

    def test_default_export_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backup.json")
            fc = make_fc(export_resume=RESUME)
            run(["export", "-o", path], fc)
            with open(path) as f:
                self.assertEqual(json.load(f), RESUME)


class ImportJsonResumeTest(unittest.TestCase):
    def test_import_uses_current_resume_as_base(self):
        jr = {"basics": {"name": "New Name"},
              "work": [{"name": "Acme", "position": "Eng", "startDate": "2020-01"}]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("flowcvcli.jsonresume.uuid.uuid4", return_value="U"):
            path = os.path.join(d, "in.jsonresume.json")
            with open(path, "w") as f:
                json.dump(jr, f)
            fc = make_fc(get_resume=RESUME, import_resume="NEW1")
            run(["import", "--format", "jsonresume", path], fc)
            expected = from_jsonresume(jr, base=RESUME)   # same patched uuid
            fc.get_resume.assert_called()                 # base fetched
            fc.import_resume.assert_called_once()
            (converted,), _kwargs = fc.import_resume.call_args
            self.assertEqual(converted, expected)

    def test_plain_import_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backup.json")
            with open(path, "w") as f:
                json.dump(RESUME, f)
            fc = make_fc(import_resume="NEW2")
            run(["import", path], fc)
            (data,), _kwargs = fc.import_resume.call_args
            self.assertEqual(data, RESUME)
            fc.get_resume.assert_not_called()             # plain path needs no base


class FormatValidationTest(unittest.TestCase):
    def test_export_rejects_unknown_format(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["export", "--format", "pdf"])

    def test_import_rejects_unknown_format(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["import", "x.json", "--format", "pdf"])


if __name__ == "__main__":
    unittest.main()

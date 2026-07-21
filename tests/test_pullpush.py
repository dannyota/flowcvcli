"""Resume-as-code: `flowcv pull` / `flowcv push`.

All offline. A FakeFlowCV records write requests and serves a canned resume, so
each test asserts the exact API calls a push produces. The frontmatter
serializer/parser round-trip is tested as pure functions.
"""
import json
import os
import tempfile
import unittest

from flowcvcli import repo
from flowcvcli.api import FlowCV
from flowcvcli.config import Config
from flowcvcli.markup import md_to_html


# --------------------------------------------------------------- fake client
class FakeFlowCV(FlowCV):
    """Serves a static resume; records every request() (the writes)."""

    def __init__(self, resume):
        super().__init__(config=Config(resume_id=resume.get("id", "R1"),
                                       cookie="flowcvsidapp=x"))
        self._resume = resume
        self.calls = []

    def get_resume(self):
        return json.loads(json.dumps(self._resume))

    def request(self, path, method="GET", body=None, query=None, timeout=30):
        self.calls.append({"path": path, "method": method, "body": body, "query": query})
        return {"success": True, "data": {}}

    def writes(self, path):
        return [c for c in self.calls if c["path"] == path]


def fixture():
    return {
        "id": "R1",
        "personalDetails": {
            "fullName": "Jane Doe",
            "jobTitle": "Engineer",
            "email": "jane@example.com",
            "social": {"orcid": {"display": "ORCID", "link": "https://orcid.org/x"}},
            "detailsOrder": ["displayEmail", "orcid"],
        },
        "content": {
            "profile": {
                "sectionType": "profile", "displayName": "Summary",
                "iconKey": "address-card",
                "entries": [{"id": "P1", "isHidden": False,
                             "text": md_to_html("Hello world.")}],
            },
            "work": {
                "sectionType": "work", "displayName": "Experience",
                "iconKey": "briefcase",
                "entries": [
                    {"id": "W1aaaaaa-1111", "isHidden": False, "jobTitle": "Engineer",
                     "employer": "Acme", "startDateNew": "01/2022", "endDateNew": "Present",
                     "description": md_to_html("- Did a **measurable** thing.")},
                    {"id": "W2bbbbbb-2222", "isHidden": True, "jobTitle": "Intern",
                     "employer": "Beta", "startDateNew": "2019", "endDateNew": "2020",
                     "description": ""},
                ],
            },
        },
    }


# ------------------------------------------------------ frontmatter round-trip
class FrontmatterTest(unittest.TestCase):
    def rt(self, d):
        fm, body = repo.parse_frontmatter(repo.dump_frontmatter(d))
        self.assertEqual(fm, d)
        self.assertEqual(body, "")

    def test_plain_and_typed_values(self):
        self.rt({"a": "hello", "b": "01/2022", "c": "Present"})

    def test_types_are_json_encoded(self):
        self.rt({"n": 12, "f": 1.5, "b": True, "x": None,
                 "lst": ["displayEmail", "orcid"],
                 "obj": {"year": "2018", "hideMonth": True}})

    def test_string_that_looks_like_json_is_forced_quoted(self):
        # "2019" must stay a string, not become int 2019
        d = {"y": "2019", "t": "true", "n": "null"}
        text = repo.dump_frontmatter(d)
        self.assertIn('y: "2019"', text)
        fm, _ = repo.parse_frontmatter(text)
        self.assertEqual(fm, d)
        self.assertIsInstance(fm["y"], str)

    def test_values_with_colons_and_quotes(self):
        self.rt({"note": "a: b: c", "q": 'she said "hi"', "empty": ""})

    def test_whitespace_and_newlines_preserved(self):
        self.rt({"lead": "  spaced  ", "multi": "line1\nline2"})

    def test_body_is_separated_from_frontmatter(self):
        text = repo.dump_frontmatter({"id": "E1"}) + "\n- one\n- two\n"
        fm, body = repo.parse_frontmatter(text)
        self.assertEqual(fm, {"id": "E1"})
        self.assertEqual(body, "- one\n- two")


# ----------------------------------------------------------------------- pull
class PullTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "resume")
        self.fc = FakeFlowCV(fixture())
        repo.pull(self.fc, self.dir)

    def read(self, *parts):
        with open(os.path.join(self.dir, *parts)) as f:
            return f.read()

    def test_personal_md_frontmatter_no_body(self):
        fm, body = repo.parse_frontmatter(self.read("personal.md"))
        self.assertEqual(fm["fullName"], "Jane Doe")
        self.assertEqual(fm["social"], {"orcid": {"display": "ORCID",
                                                  "link": "https://orcid.org/x"}})
        self.assertEqual(fm["detailsOrder"], ["displayEmail", "orcid"])
        self.assertEqual(body, "")

    def test_section_dirs_in_display_order(self):
        names = sorted(n for n in os.listdir(self.dir) if os.path.isdir(
            os.path.join(self.dir, n)))
        self.assertEqual(names, ["00-profile", "01-work"])

    def test_section_meta_file(self):
        fm, _ = repo.parse_frontmatter(self.read("01-work", "_section.md"))
        self.assertEqual(fm, {"displayName": "Experience", "iconKey": "briefcase",
                              "sectionType": "work"})

    def test_entry_file_frontmatter_and_body(self):
        fm, body = repo.parse_frontmatter(self.read("01-work", "00-W1aaaaaa.md"))
        self.assertEqual(fm["id"], "W1aaaaaa-1111")
        self.assertEqual(fm["employer"], "Acme")
        self.assertEqual(fm["isHidden"], False)
        self.assertNotIn("description", fm)          # rich field is the body
        self.assertEqual(body, "- Did a **measurable** thing.")

    def test_manifest_maps_full_ids(self):
        m = json.loads(self.read(".flowcv.json"))
        self.assertEqual(m["resumeId"], "R1")
        self.assertIn("pulledAt", m)
        self.assertEqual(m["entries"]["W1aaaaaa-1111"], "01-work/00-W1aaaaaa.md")
        self.assertEqual(m["entries"]["P1"], "00-profile/00-P1.md")


# --------------------------------------------------------- push: round-trip
class RoundTripTest(unittest.TestCase):
    def test_pull_then_push_is_zero_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "resume")
            repo.pull(FakeFlowCV(fixture()), d)
            fc = FakeFlowCV(fixture())
            actions = repo.push(fc, d)
            self.assertEqual(actions, [])
            self.assertEqual(fc.calls, [])


# ------------------------------------------------------------- push: edits
def _pulled(tmp):
    d = os.path.join(tmp, "resume")
    repo.pull(FakeFlowCV(fixture()), d)
    return d


def _edit(path, transform):
    with open(path) as f:
        text = f.read()
    with open(path, "w") as f:
        f.write(transform(text))


class PushEditTest(unittest.TestCase):
    def test_body_change_saves_entry_with_new_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            _edit(os.path.join(d, "01-work", "00-W1aaaaaa.md"),
                  lambda t: t.replace("- Did a **measurable** thing.",
                                      "- Did another thing."))
            fc = FakeFlowCV(fixture())
            actions = repo.push(fc, d)
            saves = fc.writes("resumes/save_entry")
            self.assertEqual(len(saves), 1)
            entry = saves[0]["body"]["entry"]
            self.assertEqual(entry["id"], "W1aaaaaa-1111")
            self.assertEqual(entry["description"], md_to_html("- Did another thing."))
            self.assertEqual([a["action"] for a in actions], ["update_entry"])

    def test_frontmatter_change_saves_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            _edit(os.path.join(d, "01-work", "00-W1aaaaaa.md"),
                  lambda t: t.replace("employer: Acme", "employer: Acme Corp"))
            fc = FakeFlowCV(fixture())
            repo.push(fc, d)
            saves = fc.writes("resumes/save_entry")
            self.assertEqual(len(saves), 1)
            self.assertEqual(saves[0]["body"]["entry"]["employer"], "Acme Corp")

    def test_order_change_reorders(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            w = os.path.join(d, "01-work")
            os.rename(os.path.join(w, "00-W1aaaaaa.md"), os.path.join(w, "_a.md"))
            os.rename(os.path.join(w, "01-W2bbbbbb.md"), os.path.join(w, "00-W2bbbbbb.md"))
            os.rename(os.path.join(w, "_a.md"), os.path.join(w, "01-W1aaaaaa.md"))
            fc = FakeFlowCV(fixture())
            repo.push(fc, d)
            orders = fc.writes("resumes/save_entries_order")
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["body"]["newEntriesIdsOrder"],
                             ["W2bbbbbb-2222", "W1aaaaaa-1111"])

    def test_deleted_file_deletes_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            os.remove(os.path.join(d, "01-work", "01-W2bbbbbb.md"))
            fc = FakeFlowCV(fixture())
            actions = repo.push(fc, d)
            dels = fc.writes("resumes/delete_entry")
            self.assertEqual(len(dels), 1)
            self.assertEqual(dels[0]["query"]["entryId"], "W2bbbbbb-2222")
            self.assertIn("delete_entry", [a["action"] for a in actions])

    def test_new_file_adds_entry_and_reports_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            new = repo.dump_frontmatter({"jobTitle": "Lead", "employer": "Gamma"}) \
                + "\n- Led the team.\n"
            with open(os.path.join(d, "01-work", "02-new.md"), "w") as f:
                f.write(new)
            fc = FakeFlowCV(fixture())
            actions = repo.push(fc, d)
            saves = fc.writes("resumes/save_entry")
            # create (minimal + section meta) then populate
            self.assertEqual(len(saves), 2)
            self.assertIn("sectionType", saves[0]["body"])
            populate = saves[1]["body"]["entry"]
            self.assertEqual(populate["jobTitle"], "Lead")
            self.assertEqual(populate["description"], md_to_html("- Led the team."))
            add = [a for a in actions if a["action"] == "add_entry"][0]
            self.assertTrue(add["id"])                          # a real new id
            # id written back into the file so a second push is a no-op
            with open(os.path.join(d, "01-work", "02-new.md")) as f:
                fm, _ = repo.parse_frontmatter(f.read())
            self.assertEqual(fm["id"], add["id"])

    def test_section_rename_and_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            _edit(os.path.join(d, "01-work", "_section.md"),
                  lambda t: t.replace("displayName: Experience",
                                      "displayName: Work History")
                             .replace("iconKey: briefcase", "iconKey: wrench"))
            fc = FakeFlowCV(fixture())
            repo.push(fc, d)
            names = fc.writes("resumes/save_section_name")
            icons = fc.writes("resumes/save_section_icon")
            self.assertEqual(names[0]["body"]["displayName"], "Work History")
            self.assertEqual(icons[0]["body"]["iconKey"], "wrench")

    def test_personal_change_saves_personal(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            _edit(os.path.join(d, "personal.md"),
                  lambda t: t.replace("fullName: Jane Doe", "fullName: Jane Q. Doe"))
            fc = FakeFlowCV(fixture())
            repo.push(fc, d)
            pw = fc.writes("resumes/save_personal_details")
            self.assertEqual(len(pw), 1)
            pd = pw[0]["body"]["personalDetails"]
            self.assertEqual(pd["fullName"], "Jane Q. Doe")
            self.assertEqual(pd["email"], "jane@example.com")   # overlay preserves rest

    def test_dry_run_applies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            _edit(os.path.join(d, "01-work", "00-W1aaaaaa.md"),
                  lambda t: t.replace("- Did a **measurable** thing.", "- New."))
            fc = FakeFlowCV(fixture())
            actions = repo.push(fc, d, dry_run=True)
            self.assertEqual(fc.calls, [])                      # nothing applied
            self.assertEqual([a["action"] for a in actions], ["update_entry"])

    def test_entry_matched_by_id_not_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pulled(tmp)
            w = os.path.join(d, "01-work")
            # rename to a misleading prefix; frontmatter id is unchanged
            os.rename(os.path.join(w, "00-W1aaaaaa.md"),
                      os.path.join(w, "00-zzzzzzzz.md"))
            _edit(os.path.join(w, "00-zzzzzzzz.md"),
                  lambda t: t.replace("employer: Acme", "employer: Renamed"))
            fc = FakeFlowCV(fixture())
            repo.push(fc, d)
            saves = fc.writes("resumes/save_entry")
            self.assertEqual(saves[0]["body"]["entry"]["id"], "W1aaaaaa-1111")


# ------------------------------------------------------------------- CLI
class CliTest(unittest.TestCase):
    def _run(self, argv, fc):
        import contextlib
        import io
        from unittest import mock
        from flowcvcli import cli
        out = io.StringIO()
        with mock.patch("flowcvcli.cli.FlowCV", return_value=fc):
            with contextlib.redirect_stdout(out):
                cli.main(argv)
        return out.getvalue()

    def test_pull_then_push_json_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "resume")
            self._run(["pull", d], FakeFlowCV(fixture()))
            _edit(os.path.join(d, "personal.md"),
                  lambda t: t.replace("fullName: Jane Doe", "fullName: Jane R. Doe"))
            out = self._run(["--json", "push", d, "--dry-run"], FakeFlowCV(fixture()))
            data = json.loads(out.strip())
            self.assertIn("actions", data)
            self.assertEqual([a["action"] for a in data["actions"]], ["personal"])

    def test_pull_json_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "resume")
            out = self._run(["--json", "pull", d], FakeFlowCV(fixture()))
            data = json.loads(out.strip())
            self.assertEqual(data["resumeId"], "R1")
            self.assertEqual(data["entries"], 3)
            self.assertTrue(os.path.exists(os.path.join(d, "personal.md")))


if __name__ == "__main__":
    unittest.main()

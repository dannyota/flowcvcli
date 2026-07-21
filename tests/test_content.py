"""Entry/section content operations against a faked client (no network)."""
import json
import unittest

from flowcvcli.api import FlowCV
from flowcvcli.config import Config
from flowcvcli.errors import ApiError


def make_resume(**entry_fields):
    entry = dict(id="E1")
    entry.update(entry_fields)
    return {"id": "R1", "content": {"publication": {
        "sectionType": "publication", "displayName": "Publications",
        "iconKey": "newspaper", "entries": [entry]}}}


class FakeFlowCV(FlowCV):
    """Records request() calls, serves a canned resume, never touches the network."""

    def __init__(self, resume):
        super().__init__(config=Config(resume_id="R1", cookie="flowcvsidapp=x"))
        self._resume = resume
        self.calls = []

    def get_resume(self):
        return json.loads(json.dumps(self._resume))

    def request(self, path, method="GET", body=None, query=None, timeout=30):
        self.calls.append({"path": path, "method": method, "body": body, "query": query})
        return {"success": True, "data": {}}


class SetDateTest(unittest.TestCase):
    def entry_sent(self, fc):
        return fc.calls[-1]["body"]["entry"]

    def test_year_only_hides_month_and_day(self):
        fc = FakeFlowCV(make_resume())
        fc.set_date("publication", "E1", year=2018)
        d = self.entry_sent(fc)["date"]
        self.assertEqual(d["year"], "2018")
        self.assertTrue(d["hideMonth"])
        self.assertTrue(d["hideDay"])

    def test_setting_month_keeps_existing_year(self):
        fc = FakeFlowCV(make_resume(date={"year": "2018", "month": "", "day": "",
                                          "hideMonth": True, "hideDay": True}))
        fc.set_date("publication", "E1", month=3)
        d = self.entry_sent(fc)["date"]
        self.assertEqual(d["year"], "2018")
        self.assertEqual(d["month"], "3")
        self.assertFalse(d["hideMonth"])
        self.assertTrue(d["hideDay"])

    def test_clear_resets_the_date(self):
        fc = FakeFlowCV(make_resume(date={"year": "2018", "month": "3", "day": "1",
                                          "hideMonth": False, "hideDay": False}))
        fc.set_date("publication", "E1", clear=True)
        d = self.entry_sent(fc)["date"]
        self.assertEqual((d["year"], d["month"], d["day"]), ("", "", ""))
        self.assertTrue(d["hideMonth"])
        self.assertTrue(d["hideDay"])


class ReorderSectionsTest(unittest.TestCase):
    def path_written(self, fc):
        return fc.calls[-1]["body"]["customizationUpdates"][0]["path"]

    def test_one_column_writes_sections_sorted(self):
        fc = FakeFlowCV(make_resume())
        fc.reorder_sections(["a", "b"], layout="one")
        self.assertEqual(self.path_written(fc), "sectionOrder.one.sectionsSorted")

    def test_two_column_writes_the_chosen_side(self):
        fc = FakeFlowCV(make_resume())
        fc.reorder_sections(["a", "b"], layout="two", side="left")
        self.assertEqual(self.path_written(fc), "sectionOrder.two.leftSectionsSorted")

    def test_two_column_requires_a_side(self):
        fc = FakeFlowCV(make_resume())
        with self.assertRaises(ApiError):
            fc.reorder_sections(["a", "b"], layout="two")

    def test_side_is_rejected_outside_two_column(self):
        fc = FakeFlowCV(make_resume())
        with self.assertRaises(ApiError):
            fc.reorder_sections(["a"], layout="one", side="left")


class AddEntryTest(unittest.TestCase):
    def test_unknown_section_is_rejected(self):
        fc = FakeFlowCV(make_resume())
        with self.assertRaises(ApiError):
            fc.add_entry("nope")

    def test_customn_creates_a_generic_custom_section(self):
        fc = FakeFlowCV(make_resume())
        fc.add_entry("custom7")
        create = fc.calls[0]["body"]
        self.assertEqual(create["sectionType"], "custom")
        self.assertEqual(create["sectionId"], "custom7")


if __name__ == "__main__":
    unittest.main()

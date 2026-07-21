"""`customize` read forms (no value) and the `icons` command.

Offline: `flowcvcli.cli.FlowCV` is mocked so no network is touched. The write
form (`customize path value`) must stay byte-identical to the old behaviour.
"""
import contextlib
import io
import json
import unittest
from unittest import mock

from flowcvcli.cli import ICON_KEYS, main
from flowcvcli.content import SECTION_META


def run(argv, fc=None):
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


CUST = {"font": {"fontFamily": "Rubik", "headingSize": 18},
        "colors": {"basic": {"single": "#123456"}}}


class CustomizeReadTest(unittest.TestCase):
    def test_no_args_dumps_sorted_leaves(self):
        fc = make_fc(get_customization=CUST)
        self.assertEqual(run(["customize"], fc),
                         'colors.basic.single = "#123456"\n'
                         'font.fontFamily = "Rubik"\n'
                         'font.headingSize = 18\n')

    def test_no_args_json_is_the_whole_tree(self):
        fc = make_fc(get_customization=CUST)
        self.assertEqual(json.loads(run(["--json", "customize"], fc)), CUST)

    def test_path_filters_to_subtree(self):
        fc = make_fc(get_customization=CUST)
        self.assertEqual(run(["customize", "font"], fc),
                         'font.fontFamily = "Rubik"\n'
                         'font.headingSize = 18\n')

    def test_path_json_is_the_subtree(self):
        fc = make_fc(get_customization=CUST)
        self.assertEqual(json.loads(run(["--json", "customize", "font"], fc)),
                         {"fontFamily": "Rubik", "headingSize": 18})

    def test_leaf_path(self):
        fc = make_fc(get_customization=CUST)
        self.assertEqual(run(["customize", "font.fontFamily"], fc),
                         'font.fontFamily = "Rubik"\n')

    def test_unknown_path_is_empty(self):
        fc = make_fc(get_customization=CUST)
        self.assertEqual(run(["customize", "nope"], fc), "")

    def test_read_makes_no_write_call(self):
        fc = make_fc(get_customization=CUST)
        run(["customize", "font"], fc)
        fc.set.assert_not_called()


class CustomizeWriteUnchangedTest(unittest.TestCase):
    def test_write_still_works_and_reports(self):
        fc = make_fc(set={"success": True})
        self.assertEqual(run(["customize", "font.fontFamily", "Rubik"], fc),
                         "customize font.fontFamily=Rubik -> success=True\n")
        fc.set.assert_called_once_with("font.fontFamily", "Rubik")

    def test_write_json_is_the_envelope(self):
        fc = make_fc(set={"success": True})
        self.assertEqual(json.loads(run(["--json", "customize", "a.b", "1"], fc)),
                         {"success": True})


class IconsTest(unittest.TestCase):
    def test_icons_human_one_per_line(self):
        lines = run(["icons"]).splitlines()
        self.assertEqual(lines, list(ICON_KEYS))
        self.assertIn("briefcase", lines)
        self.assertIn("shield-check", lines)

    def test_icons_json_is_a_list(self):
        data = json.loads(run(["--json", "icons"]))
        self.assertEqual(data, list(ICON_KEYS))

    def test_section_meta_icons_are_included(self):
        for _stype, _name, icon in SECTION_META.values():
            self.assertIn(icon, ICON_KEYS)


if __name__ == "__main__":
    unittest.main()

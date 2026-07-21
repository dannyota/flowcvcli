"""CLI parsing: set-key aliases, value coercion, and command flags."""
import contextlib
import io
import unittest
from unittest import mock

from flowcvcli.cli import _coerce, _resolve_set_key, build_parser, cmd_date


class SetKeyAliasTest(unittest.TestCase):
    def test_common_aliases(self):
        self.assertEqual(_resolve_set_key("work", "start"), "startDateNew")
        self.assertEqual(_resolve_set_key("education", "end"), "endDateNew")

    def test_section_aware_aliases(self):
        self.assertEqual(_resolve_set_key("work", "title"), "jobTitle")
        self.assertEqual(_resolve_set_key("education", "company"), "school")
        self.assertEqual(_resolve_set_key("publication", "company"), "publisher")

    def test_customn_uses_the_custom_map(self):
        self.assertEqual(_resolve_set_key("custom7", "title"), "title")
        self.assertEqual(_resolve_set_key("custom7", "link"), "titleLink")

    def test_unknown_keys_pass_through(self):
        self.assertEqual(_resolve_set_key("work", "employer"), "employer")


class CoerceTest(unittest.TestCase):
    def test_json_scalars(self):
        self.assertIs(_coerce("true"), True)
        self.assertEqual(_coerce("12"), 12)

    def test_non_json_stays_string(self):
        self.assertEqual(_coerce("01/2022"), "01/2022")


class ParserTest(unittest.TestCase):
    def test_version_flag(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_download_accepts_pages(self):
        a = build_parser().parse_args(["download", "--pages", "2"])
        self.assertEqual(a.pages, 2)

    def test_date_accepts_clear(self):
        a = build_parser().parse_args(["date", "publication", "E1", "--clear"])
        self.assertTrue(a.clear)

    def test_resume_id_works_before_and_after_the_subcommand(self):
        a = build_parser().parse_args(["--resume-id", "RID", "resumes"])
        self.assertEqual(getattr(a, "resume_id_override", None), "RID")
        a = build_parser().parse_args(["resumes", "--resume-id", "RID"])
        self.assertEqual(getattr(a, "resume_id_override", None), "RID")

    def test_reorder_sections_accepts_side(self):
        a = build_parser().parse_args(["reorder-sections", "a", "b",
                                       "--layout", "two", "--side", "left"])
        self.assertEqual(a.side, "left")

    def test_date_with_nothing_to_change_exits_before_any_network(self):
        a = build_parser().parse_args(["date", "publication", "E1"])
        with mock.patch("flowcvcli.cli.FlowCV",
                        side_effect=AssertionError("network path reached")):
            with self.assertRaises(SystemExit):
                cmd_date(a)


if __name__ == "__main__":
    unittest.main()

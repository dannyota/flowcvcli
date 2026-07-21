"""Markdown -> FlowCV rich-text HTML conversion, and html_to_text."""
import unittest

from flowcvcli.markup import html_to_md, html_to_text, md_to_html

J = ' style="text-align: justify"'


class MdToHtmlTest(unittest.TestCase):
    def test_plain_paragraph(self):
        self.assertEqual(md_to_html("hello"), f"<p{J}>hello</p>")

    def test_blank_lines_split_blocks(self):
        self.assertEqual(md_to_html("a\n\nb"), f"<p{J}>a</p><p{J}>b</p>")

    def test_consecutive_bullets_form_one_list(self):
        out = md_to_html("- a\n- b")
        self.assertEqual(out.count("<ul>"), 1)
        self.assertIn(f"<li{J}><p{J}>a</p></li>", out)
        self.assertIn(f"<li{J}><p{J}>b</p></li>", out)

    def test_inline_bold_and_link_in_paragraph(self):
        out = md_to_html("see **it** at [x](https://x.example)")
        self.assertIn("<strong>it</strong>", out)
        self.assertIn('href="https://x.example"', out)

    def test_escapes_html(self):
        self.assertIn("&lt;script&gt;", md_to_html("<script>"))

    def test_heading_line(self):
        self.assertEqual(md_to_html("## Skills"), f"<p{J}><strong>Skills</strong></p>")

    def test_heading_renders_inline_link(self):
        out = md_to_html("## See [x](https://x.example)")
        self.assertIn('href="https://x.example"', out)

    def test_whole_line_bold_renders_inline_link(self):
        out = md_to_html("**See [x](https://x.example)**")
        self.assertTrue(out.startswith(f"<p{J}><strong>"), out)
        self.assertIn('href="https://x.example"', out)

    def test_bold_italic_line(self):
        self.assertEqual(md_to_html("***Note***"),
                         f"<p{J}><strong><em>Note</em></strong></p>")

    def test_heading_with_inline_bold_does_not_nest_strong(self):
        self.assertEqual(md_to_html("## a **b** c"),
                         f"<p{J}><strong>a b c</strong></p>")

    def test_bold_italic_line_with_inline_bold_does_not_nest_strong(self):
        self.assertEqual(md_to_html("***a **b** c***"),
                         f"<p{J}><strong><em>a b c</em></strong></p>")


class HtmlToTextTest(unittest.TestCase):
    def test_strips_tags_and_unescapes(self):
        self.assertEqual(html_to_text(f"<p{J}>a &amp; <strong>b</strong></p>"), "a & b")

    def test_none_and_empty(self):
        self.assertEqual(html_to_text(None), "")
        self.assertEqual(html_to_text(""), "")


class HtmlToMdTest(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(html_to_md(None), "")
        self.assertEqual(html_to_md(""), "")

    def test_plain_paragraph(self):
        self.assertEqual(html_to_md(f"<p{J}>hello</p>"), "hello")

    def test_blocks_separated_by_blank_line(self):
        self.assertEqual(html_to_md(f"<p{J}>a</p><p{J}>b</p>"), "a\n\nb")

    def test_whole_line_bold(self):
        self.assertEqual(html_to_md(f"<p{J}><strong>Skills</strong></p>"), "**Skills**")

    def test_bold_italic_line(self):
        self.assertEqual(
            html_to_md(f"<p{J}><strong><em>Note</em></strong></p>"), "***Note***")

    def test_bullets_become_dash_lines(self):
        h = f"<ul><li{J}><p{J}>a</p></li><li{J}><p{J}>b</p></li></ul>"
        self.assertEqual(html_to_md(h), "- a\n- b")

    def test_inline_bold(self):
        self.assertEqual(html_to_md(f"<p{J}>see <strong>it</strong></p>"), "see **it**")

    def test_inline_link_drops_target_and_rel(self):
        h = (f'<p{J}>go <a target="_blank" rel="noopener noreferrer nofollow"'
             f' href="https://x.example">x</a></p>')
        out = html_to_md(h)
        self.assertEqual(out, "go [x](https://x.example)")
        self.assertNotIn("target", out)
        self.assertNotIn("rel", out)

    def test_unescapes_entities(self):
        self.assertEqual(
            html_to_md(f"<p{J}>a &amp; b &lt; c &gt; d</p>"), "a & b < c > d")

    def test_unknown_tag_degrades_to_text(self):
        self.assertEqual(
            html_to_md(f'<p{J}><span class="x">hi</span> there</p>'), "hi there")

    def test_attribute_variations_tolerated(self):
        self.assertEqual(html_to_md("<p>x</p>"), "x")
        self.assertEqual(
            html_to_md('<p class="y" style="text-align: justify">x</p>'), "x")

    def test_nested_strong_collapses(self):
        h = f"<p{J}><strong>a <strong>b</strong> c</strong></p>"
        self.assertEqual(html_to_md(h), "**a b c**")

    def test_md_to_html_round_trip_is_stable(self):
        cases = [
            "hello",
            "a\n\nb",
            "- a\n- b",
            "intro\n\n- first\n- second",
            "## Skills",
            "**Whole line bold**",
            "***Bold italic line***",
            "see **it** at [x](https://x.example)",
            "R&D uses <tags> & \"quotes\" and 'apostrophes'",
            "line one\n\nline two\n\n- b1\n- b2\n\n## Heading",
            "## See [x](https://x.example)",
            "**See [x](https://x.example)**",
            "## Skills in **Python** and Go",
            "## a ***b*** c",
            "***a **b** c***",
            "**a **b** c**",
        ]
        for md in cases:
            html = md_to_html(md)
            self.assertEqual(md_to_html(html_to_md(html)), html, md)


if __name__ == "__main__":
    unittest.main()

"""Markdown <-> FlowCV rich-text HTML.

FlowCV stores rich text as justified <p> / <ul><li><p> HTML. `md_to_html`
converts a small markdown dialect into that markup:

  blank line            -> block separator
  "## Heading"          -> bold justified paragraph (a subheader)
  "**Whole line bold**" -> bold justified paragraph
  "***Whole line***"    -> bold + italic justified paragraph (a sub-subheader)
  "- item"              -> bullet (consecutive lines become one <ul>)
  anything else         -> justified paragraph
  inline **bold**       -> <strong>bold</strong> (inside paragraphs and bullets)
  inline [text](url)    -> <a href="url">text</a> (inside paragraphs and bullets)
"""
import html
import re
from html.parser import HTMLParser

J = ' style="text-align: justify"'


def _esc(s):
    """Escape text, then honor inline ***bold-italic***, **bold**, and
    [text](url) links (triple-asterisks before double so they don't clash)."""
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  r'<a target="_blank" rel="noopener noreferrer nofollow" href="\2">\1</a>', s)


def md_to_html(md):
    parts, bullets = [], []

    def flush():
        if bullets:
            lis = "".join(f"<li{J}><p{J}>{_esc(b)}</p></li>" for b in bullets)
            parts.append(f"<ul>{lis}</ul>")
            bullets.clear()

    for raw in (md or "").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("- "):
            bullets.append(line[2:].strip())
            continue
        flush()
        if line.startswith("## "):
            parts.append(f"<p{J}><strong>{_esc(line[3:].strip())}</strong></p>")
        elif len(line) > 6 and line.startswith("***") and line.endswith("***"):
            parts.append(f"<p{J}><strong><em>{_esc(line[3:-3].strip())}</em></strong></p>")
        elif len(line) > 4 and line.startswith("**") and line.endswith("**") and line.count("**") == 2:
            parts.append(f"<p{J}><strong>{_esc(line[2:-2].strip())}</strong></p>")
        else:
            parts.append(f"<p{J}>{_esc(line)}</p>")
    flush()
    return "".join(parts)


class _MdBuilder(HTMLParser):
    """Rebuild md_to_html's markdown dialect from its HTML output."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.bullets, self.buf, self.hrefs = [], [], [], []
        self.in_ul = self.in_p = False

    def handle_starttag(self, tag, attrs):
        if tag == "ul":
            self.in_ul, self.bullets = True, []
        elif tag == "p":
            self.in_p, self.buf = True, []
        elif tag == "strong":
            self.buf.append("**")
        elif tag == "em":
            self.buf.append("*")
        elif tag == "a":
            self.hrefs.append(dict(attrs).get("href") or "")
            self.buf.append("[")

    def handle_endtag(self, tag):
        if tag == "strong":
            self.buf.append("**")
        elif tag == "em":
            self.buf.append("*")
        elif tag == "a":
            self.buf.append("](%s)" % (self.hrefs.pop() if self.hrefs else ""))
        elif tag == "p":
            text, self.in_p = "".join(self.buf).strip(), False
            if self.in_ul:
                self.bullets.append(text)
            elif text:
                self.blocks.append(text)
        elif tag == "ul":
            self.in_ul = False
            if self.bullets:
                self.blocks.append("\n".join("- " + b for b in self.bullets))

    def handle_data(self, data):
        if self.in_p:
            self.buf.append(data)


def html_to_md(html):
    """FlowCV rich-text HTML -> the md_to_html markdown dialect (its inverse).

    Justified <p>/<ul><li><p> blocks become markdown lines separated by blank
    lines; a whole-paragraph <strong> becomes a **bold** line, <strong><em> a
    ***bold-italic*** line, and each <li> a "- " bullet. Inline <strong>,
    <strong><em>, and <a href="u">t</a> become **x**, ***x***, and [t](u)
    (target/rel attrs dropped); text content is HTML-unescaped. Attribute
    variations (with or without style="text-align: justify") and unknown tags
    are tolerated, the latter degrading to their text content.

    The inverse is lossy in one direction: "## H" and "**H**" both produce the
    same <p><strong>H</strong></p>, so a bold paragraph always round-trips to
    the "**H**" form (never "## H"). Re-running md_to_html on the result is
    stable: md_to_html(html_to_md(md_to_html(md))) == md_to_html(md).
    """
    if not html:
        return ""
    b = _MdBuilder()
    b.feed(html)
    b.close()
    return "\n\n".join(b.blocks)


def html_to_text(h):
    return html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", h or ""))).strip()

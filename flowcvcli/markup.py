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
            parts.append(f"<p{J}><strong>{html.escape(line[3:].strip(), quote=False)}</strong></p>")
        elif len(line) > 6 and line.startswith("***") and line.endswith("***"):
            parts.append(f"<p{J}><strong><em>{html.escape(line[3:-3].strip(), quote=False)}</em></strong></p>")
        elif len(line) > 4 and line.startswith("**") and line.endswith("**") and line.count("**") == 2:
            parts.append(f"<p{J}><strong>{html.escape(line[2:-2].strip(), quote=False)}</strong></p>")
        else:
            parts.append(f"<p{J}>{_esc(line)}</p>")
    flush()
    return "".join(parts)


def html_to_text(h):
    return html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", h or ""))).strip()

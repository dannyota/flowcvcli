"""Command-line interface over the FlowCV client.

Run `python3 flowcv.py --help`. Auth comes from .env / env vars
(FLOWCV_COOKIE, or FLOWCV_EMAIL+FLOWCV_PASSWORD). The resume id is optional:
with a single resume the tool auto-selects it; with several, set FLOWCV_RESUME_ID
or pass `--resume-id <id>` (any command accepts it).
"""
import argparse
import json
import os
import sys

from .api import FlowCV
from .client import login as do_login, _write_session
from .content import SECTION_META, label_of
from .markup import html_to_text, md_to_html

ALIASES = {"title": "jobTitle", "company": "employer", "start": "startDateNew",
           "end": "endDateNew", "link": "employerLink"}
TEXT_FIELDS = ("description", "infoHtml", "text")


def _read(file=None, text=None):
    if file:
        with open(file) as f:
            return f.read().strip()
    return text


def _coerce(s):
    """Parse a CLI value as JSON (true/false/number/quoted), else keep as string."""
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return s


def _result(env, label):
    ok = env.get("success") if isinstance(env, dict) else env
    print(f"{label} -> success={ok}")
    if isinstance(env, dict) and not ok:
        print("  !", json.dumps(env)[:200])


def _fc(a):
    return FlowCV(resume_id=getattr(a, "resume_id_override", None))


# ------------------------------------------------------------------ commands
def cmd_login(a):
    fc = _fc(a)
    if not (fc.cfg.email and fc.cfg.password):
        sys.exit("Set FLOWCV_EMAIL and FLOWCV_PASSWORD in .env to use `login`.")
    _write_session(do_login(fc.cfg.email, fc.cfg.password))
    print("login ok -> session cached to .flowcv_session")


def cmd_resumes(a):
    for r in _fc(a).list_resumes():
        live = "live" if r.get("webResumeLive") else "private"
        print(f"  {r.get('id','(no id)')}  {(r.get('title') or '(untitled)'):20}  web:{r.get('webToken','-')} [{live}]")


def cmd_show(a):
    resume = _fc(a).get_resume()
    for sec, obj in (resume.get("content") or {}).items():
        if a.section and sec != a.section:
            continue
        print(f"[{sec}] '{obj.get('displayName')}' ({len(obj.get('entries') or [])} entries)")
        for e in obj.get("entries") or []:
            d = f"  {e.get('startDateNew','')}–{e.get('endDateNew','')}" if e.get("startDateNew") or e.get("endDateNew") else ""
            print(f"   {e.get('id','(no id)')}  {label_of(e)}{d}")


def cmd_dump(a):
    fc = _fc(a)
    e = fc.find_entry(fc.get_resume(), a.section, a.entry)
    for k, v in e.items():
        if k in TEXT_FIELDS:
            print(f"  {k} (text): {html_to_text(v)}")
            print(f"  {k} (html): {v}")
        else:
            print(f"  {k}: {v!r}")


def cmd_add(a):
    sets = {}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        sets[ALIASES.get(k, k)] = v
    new_id = _fc(a).add_entry(a.section, sets=sets, md=_read(a.file, a.text))
    print(f"added {a.section} entry -> {new_id}")


def cmd_rm(a):
    _result(_fc(a).delete_entry(a.section, a.entry), f"rm {a.section}/{a.entry[:8]}")


def cmd_field(a):
    _result(_fc(a).set_field(a.section, a.entry, a.field, _read(a.file, a.text)),
            f"{a.section}/{a.entry[:8]}.{a.field}")


def cmd_desc(a):
    _result(_fc(a).set_description(a.section, a.entry, _read(a.file, a.text), field=a.field),
            f"{a.section}/{a.entry[:8]}.{a.field}")


def cmd_pd(a):
    _result(_fc(a).set_personal_field(a.field, a.text), f"personalDetails.{a.field}")


def cmd_links(a):
    for k, display, link, shown in _fc(a).list_links():
        print(f"  {k}: {display} -> {link} [{'shown' if shown else 'hidden'}]")


def cmd_link(a):
    _result(_fc(a).set_link(a.key, a.display, a.url), f"link {a.key}")


def cmd_unlink(a):
    _result(_fc(a).remove_link(a.key), f"unlink {a.key}")


def cmd_customize(a):
    _result(_fc(a).set(a.path, _coerce(a.value)), f"customize {a.path}={a.value}")


def cmd_avatar(a):
    fc = _fc(a)
    if a.action in ("on", "off"):
        _result(fc.set_avatar_visible(a.action == "on"), f"avatar {a.action}")
    elif a.action == "set":
        if not a.src:
            sys.exit("avatar set needs a URL or file path: `avatar set <url|file>`")
        _result(fc.set_photo(a.src), f"avatar set {a.src[:40]}")
    elif a.action == "remove":
        _result(fc.remove_photo(), "avatar remove")


def _tname(t):
    return t.get("title") or t.get("metaTitle") or t.get("slug") or "(unnamed)"


def cmd_templates(a):
    free = paid = 0
    for t in _fc(a).list_templates():
        if not isinstance(t, dict):
            continue
        premium = bool(t.get("isPremium"))
        paid += premium; free += not premium
        print(f"  {t.get('id') or t.get('templateId')}  [{'PAID' if premium else 'free'}]  {_tname(t)}")
    print(f"\n{free} free, {paid} paid (PAID templates need a FlowCV subscription to apply).")


def cmd_apply_template(a):
    fc = _fc(a)
    t = next((x for x in fc.list_templates()
              if isinstance(x, dict) and (x.get("id") or x.get("templateId")) == a.template_id), None)
    if t and t.get("isPremium"):
        print(f"note: '{_tname(t)}' is a PAID template — applying it may require a FlowCV subscription.")
    _result(fc.apply_template(a.template_id), f"apply-template {a.template_id[:8]}")


def cmd_download(a):
    fc = _fc(a)
    if a.token:                                  # public download of any shared resume
        data = fc.download_public(a.token)
        out = a.output or f"{a.token}.pdf"
        with open(out, "wb") as f:
            f.write(data)
        print(f"saved {out} ({len(data)} bytes)")
    else:
        path = fc.save_pdf(a.output or "resume.pdf", pages=a.pages)
        print(f"saved {path} ({os.path.getsize(path)} bytes)")


def cmd_publish(a):
    fc = _fc(a)
    _result(fc.publish(), "publish")
    print(f"  {fc.share_url()}")


def cmd_unpublish(a):
    _result(_fc(a).unpublish(), "unpublish")


def cmd_share(a):
    st = _fc(a).web_status()
    print(f"web resume: {'LIVE' if st['live'] else 'disabled'}\nshare url : {st['url'] or '(none)'}")


def cmd_md2html(a):
    print(md_to_html(_read(a.file, a.text)))


# -------------------------------------------------------------------- parser
def build_parser():
    # --resume-id on a shared parent so it works BEFORE or AFTER the subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--resume-id", dest="resume_id_override", help="target a specific resume")
    p = argparse.ArgumentParser(prog="flowcv", description=__doc__, parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    add("login").set_defaults(fn=cmd_login)
    add("resumes").set_defaults(fn=cmd_resumes)

    s = add("show"); s.add_argument("section", nargs="?"); s.set_defaults(fn=cmd_show)
    s = add("dump"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_dump)

    s = add("add"); s.add_argument("section")
    s.add_argument("--set", action="append", help="field=value (aliases: title,company,start,end,link)")
    g = s.add_mutually_exclusive_group(); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_add)

    s = add("rm"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_rm)

    s = add("field"); s.add_argument("section"); s.add_argument("entry"); s.add_argument("field")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--file")
    s.set_defaults(fn=cmd_field)

    s = add("desc"); s.add_argument("section"); s.add_argument("entry")
    s.add_argument("--field", default="description")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_desc)

    s = add("pd"); s.add_argument("field"); s.add_argument("--text", required=True); s.set_defaults(fn=cmd_pd)

    add("links").set_defaults(fn=cmd_links)
    s = add("link"); s.add_argument("key"); s.add_argument("display"); s.add_argument("url"); s.set_defaults(fn=cmd_link)
    s = add("unlink"); s.add_argument("key"); s.set_defaults(fn=cmd_unlink)

    s = add("customize"); s.add_argument("path"); s.add_argument("value"); s.set_defaults(fn=cmd_customize)
    s = add("avatar"); s.add_argument("action", choices=["on", "off", "set", "remove"])
    s.add_argument("src", nargs="?", help="URL or file path (for `avatar set`)"); s.set_defaults(fn=cmd_avatar)
    add("templates").set_defaults(fn=cmd_templates)
    s = add("apply-template"); s.add_argument("template_id"); s.set_defaults(fn=cmd_apply_template)

    s = add("download"); s.add_argument("-o", "--output"); s.add_argument("--pages", type=int, default=10)
    s.add_argument("--token", help="download a public resume by its share token (no auth)")
    s.set_defaults(fn=cmd_download)
    add("publish").set_defaults(fn=cmd_publish)
    add("unpublish").set_defaults(fn=cmd_unpublish)
    add("share").set_defaults(fn=cmd_share)

    s = add("md2html")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_md2html)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)

"""Command-line interface over the FlowCV client.

Run `python3 flowcv.py --help`. Auth comes from .env / env vars
(FLOWCV_COOKIE, or FLOWCV_EMAIL+FLOWCV_PASSWORD). The resume id is optional:
with a single resume the tool auto-selects it; with several, set FLOWCV_RESUME_ID
or pass `--resume-id <id>` (any command accepts it).

Output: by default each command prints human-readable text. Pass `--json`
(anywhere, like `--resume-id`) for machine-readable output — every command then
writes exactly ONE JSON document to stdout and nothing else, so scripts and LLM
agents can parse it. Under `--json`, a library error (`FlowCVError`) is written
to stdout as `{"error": ..., "type": ...}` and the process exits 1. CLI-level
argument-validation messages (e.g. a missing `--yes`) still go to stderr as a
plain `sys.exit` — JSON consumers read stdout, so those never pollute the output.
"""
import argparse
import datetime
import json
import os
import re
import sys

from . import __version__
from .api import FlowCV
from .client import login as do_login, _write_session, _jar_header
from .config import (Config, dotenv_files_found, resolve_auth_source,
                     session_file_info)
from .errors import FlowCVError
from .content import SECTION_META, label_of, rich_field
from .markup import html_to_text, md_to_html

# `--set key=value` friendly aliases. `start`/`end` are common to all sections;
# `title`/`company`/`link` map to different real fields per section, so resolve
# them section-aware (the old flat map mis-set custom/publication entries).
_ALIASES_COMMON = {"start": "startDateNew", "end": "endDateNew"}
_ALIASES_BY_SECTION = {
    "work":         {"title": "jobTitle", "company": "employer", "link": "employerLink"},
    "education":    {"title": "degree", "company": "school", "link": "schoolLink"},
    "publication":  {"title": "title", "company": "publisher", "link": "titleLink"},
    "organisation": {"title": "position", "company": "organisationName", "link": "organisationLink"},
    "custom":       {"title": "title", "link": "titleLink"},
}
TEXT_FIELDS = ("description", "infoHtml", "text")


def _resolve_set_key(section, key):
    """Map a friendly --set key to the real entry field for `section`."""
    if key in _ALIASES_COMMON:
        return _ALIASES_COMMON[key]
    sec = "custom" if re.fullmatch(r"custom\d+", section or "") else section
    return _ALIASES_BY_SECTION.get(sec, {}).get(key, key)


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


# Output mode. Set once by main() from `--json`; read by _emit(). A module flag
# keeps each cmd_* free of if/else print forks — commands build a data value and
# a human-print closure, and _emit routes to whichever the mode selects.
_JSON = False


def _emit(data, human):
    """Route output: in --json mode print one JSON document; else run human()."""
    if _JSON:
        print(json.dumps(data, ensure_ascii=False))
    else:
        human()


def _result_human(env, label):
    ok = env.get("success") if isinstance(env, dict) else env
    print(f"{label} -> success={ok}")
    if isinstance(env, dict) and not ok:
        print("  !", json.dumps(env)[:200])


def _result(env, label):
    """Report a mutation: human -> `label -> success=..`; JSON -> the envelope."""
    _emit(env, lambda: _result_human(env, label))


def _fc(a):
    return FlowCV(resume_id=getattr(a, "resume_id_override", None))


# ------------------------------------------------------------------ commands
def cmd_login(a):
    fc = _fc(a)
    if not (fc.cfg.email and fc.cfg.password):
        sys.exit("Set FLOWCV_EMAIL and FLOWCV_PASSWORD in .env to use `login`.")
    _write_session(_jar_header(do_login(fc.cfg.email, fc.cfg.password)))
    _emit({"success": True}, lambda: print("login ok -> session cached to .flowcv_session"))


def cmd_resumes(a):
    resumes = _fc(a).list_resumes()

    def human():
        for r in resumes:
            live = "live" if r.get("webResumeLive") else "private"
            print(f"  {r.get('id','(no id)')}  {(r.get('title') or '(untitled)'):20}  web:{r.get('webToken','-')} [{live}]")
    _emit([{"id": r.get("id"), "title": r.get("title"), "webToken": r.get("webToken"),
            "live": bool(r.get("webResumeLive"))} for r in resumes], human)


def cmd_new(a):
    new_id = _fc(a).create_resume(a.title)
    _emit({"id": new_id, "success": True}, lambda: print(f"created new resume -> {new_id}"))


def cmd_duplicate(a):
    new_id = _fc(a).duplicate_resume(a.title)
    _emit({"id": new_id, "success": True}, lambda: print(f"duplicated -> {new_id}"))


def cmd_rename(a):
    _result(_fc(a).rename_resume(a.title), f"rename resume -> {a.title!r}")


def cmd_delete_resume(a):
    fc = _fc(a)
    rid = fc.resume_id
    if not a.yes:
        sys.exit(f"refusing to delete resume {rid} without --yes (this is permanent).")
    if not a.no_backup:
        fc.snapshot(rid)          # aborts the delete if the snapshot fails (raises)
    _result(fc.delete_resume(rid), f"delete resume {rid[:8]}")


def cmd_show(a):
    content = _fc(a).get_resume().get("content") or {}
    shown = [(sec, obj) for sec, obj in content.items()
             if not a.section or sec == a.section]

    def human():
        for sec, obj in shown:
            print(f"[{sec}] '{obj.get('displayName')}' ({len(obj.get('entries') or [])} entries)")
            for e in obj.get("entries") or []:
                d = f"  {e.get('startDateNew','')}–{e.get('endDateNew','')}" if e.get("startDateNew") or e.get("endDateNew") else ""
                print(f"   {e.get('id','(no id)')}  {label_of(e)}{d}")
    _emit({sec: {"displayName": obj.get("displayName"),
                 "entries": [{"id": e.get("id"), "label": label_of(e),
                              "start": e.get("startDateNew"), "end": e.get("endDateNew"),
                              "hidden": bool(e.get("isHidden"))}
                             for e in obj.get("entries") or []]}
           for sec, obj in shown}, human)


def cmd_dump(a):
    fc = _fc(a)
    e = fc.find_entry(fc.get_resume(), a.section, a.entry)

    def human():
        for k, v in e.items():
            if k in TEXT_FIELDS:
                print(f"  {k} (text): {html_to_text(v)}")
                print(f"  {k} (html): {v}")
            else:
                print(f"  {k}: {v!r}")
    data = dict(e)
    data["_text"] = html_to_text(e.get(rich_field(a.section)))
    _emit(data, human)


def cmd_add(a):
    sets = {}
    for kv in a.set or []:
        if "=" not in kv:
            sys.exit(f"--set expects key=value, got {kv!r}")
        k, _, v = kv.partition("=")
        sets[_resolve_set_key(a.section, k)] = v
    new_id = _fc(a).add_entry(a.section, sets=sets, md=_read(a.file, a.text),
                              section_name=a.section_name, section_icon=a.icon)
    _emit({"id": new_id, "success": True}, lambda: print(f"added {a.section} entry -> {new_id}"))


def cmd_rm(a):
    _result(_fc(a).delete_entry(a.section, a.entry), f"rm {a.section}/{a.entry[:8]}")


def cmd_reorder(a):
    _result(_fc(a).reorder_entries(a.section, a.ids), f"reorder {a.section} ({len(a.ids)} entries)")


def cmd_hide(a):
    _result(_fc(a).hide_entry(a.section, a.entry, hidden=True), f"hide {a.section}/{a.entry[:8]}")


def cmd_show_entry(a):
    _result(_fc(a).hide_entry(a.section, a.entry, hidden=False), f"show {a.section}/{a.entry[:8]}")


def cmd_rename_section(a):
    _result(_fc(a).rename_section(a.section, a.name), f"rename-section {a.section}")


def cmd_section_icon(a):
    _result(_fc(a).set_section_icon(a.section, a.icon), f"section-icon {a.section}={a.icon}")


def cmd_rm_section(a):
    fc = _fc(a)
    if not a.yes:
        sys.exit(f"refusing to delete section {a.section!r} and all its entries without --yes.")
    if not a.no_backup:
        fc.snapshot()             # aborts the delete if the snapshot fails (raises)
    _result(fc.delete_section(a.section), f"rm-section {a.section}")


def cmd_reorder_sections(a):
    fc = _fc(a)
    if not a.ids:                                   # no ids -> print current order
        resume = fc.get_resume()
        so = (resume.get("customization") or {}).get("sectionOrder") or {}
        content = resume.get("content") or {}
        name = lambda sid: (content.get(sid) or {}).get("displayName", "")

        def human():
            print(f"section order ({a.layout}):")
            if a.layout == "two":
                lay = so.get("two") or {}
                for side in ("leftSectionsSorted", "rightSectionsSorted"):
                    print(f"  {side}:")
                    for sid in lay.get(side) or []:
                        print(f"    {sid}  {name(sid)}")
            else:
                for sid in (so.get(a.layout) or {}).get("sectionsSorted") or []:
                    print(f"  {sid}  {name(sid)}")
        cols = lambda ids: [{"id": sid, "name": name(sid)} for sid in ids or []]
        if a.layout == "two":
            lay = so.get("two") or {}
            data = {"layout": "two",
                    "leftSectionsSorted": cols(lay.get("leftSectionsSorted")),
                    "rightSectionsSorted": cols(lay.get("rightSectionsSorted"))}
        else:
            data = {"layout": a.layout,
                    "sectionsSorted": cols((so.get(a.layout) or {}).get("sectionsSorted"))}
        _emit(data, human)
        return
    if a.layout == "two" and not a.side:
        sys.exit("--layout two stores each column separately — add --side left or --side right.")
    if a.side and a.layout != "two":
        sys.exit("--side only applies to --layout two.")
    _result(fc.reorder_sections(a.ids, layout=a.layout, side=a.side),
            f"reorder-sections ({a.layout}{'/' + a.side if a.side else ''})")


def cmd_field(a):
    _result(_fc(a).set_field(a.section, a.entry, a.field, _read(a.file, a.text)),
            f"{a.section}/{a.entry[:8]}.{a.field}")


def cmd_desc(a):
    field = a.field or rich_field(a.section)        # auto: profile->text, skill->infoHtml
    _result(_fc(a).set_description(a.section, a.entry, _read(a.file, a.text), field=field),
            f"{a.section}/{a.entry[:8]}.{field}")


def cmd_date(a):
    if not (a.year or a.month or a.day or a.clear):
        sys.exit("nothing to change: pass --year/--month/--day, or --clear to reset the date.")
    _result(_fc(a).set_date(a.section, a.entry, year=a.year, month=a.month, day=a.day,
                            clear=a.clear),
            f"{a.section}/{a.entry[:8]}.date")


def cmd_export(a):
    out = a.output or "resume-backup.json"
    with open(out, "w") as f:
        json.dump(_fc(a).export_resume(), f, indent=2, ensure_ascii=False)
    n = os.path.getsize(out)
    _emit({"saved": out, "bytes": n}, lambda: print(f"exported resume -> {out} ({n} bytes)"))


def cmd_import(a):
    with open(a.file) as f:
        data = json.load(f)
    new_id = _fc(a).import_resume(data, title=a.title)
    _emit({"id": new_id, "success": True},
          lambda: print(f"restored backup into a NEW resume -> {new_id} (current resume untouched)"))


def cmd_pd(a):
    _result(_fc(a).set_personal_field(a.field, _read(a.file, a.text)), f"personalDetails.{a.field}")


def cmd_links(a):
    links = _fc(a).list_links()

    def human():
        for k, display, link, shown in links:
            print(f"  {k}: {display} -> {link} [{'shown' if shown else 'hidden'}]")
    _emit([{"key": k, "display": display, "link": link, "shown": shown}
           for k, display, link, shown in links], human)


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
    templates = [t for t in _fc(a).list_templates() if isinstance(t, dict)]

    def human():
        free = paid = 0
        for t in templates:
            premium = bool(t.get("isPremium"))
            paid += premium; free += not premium
            print(f"  {t.get('id') or t.get('templateId')}  [{'PAID' if premium else 'free'}]  {_tname(t)}")
        print(f"\n{free} free, {paid} paid (PAID templates need a FlowCV subscription to apply).")
    _emit([{"id": t.get("id") or t.get("templateId"), "title": _tname(t),
            "premium": bool(t.get("isPremium"))} for t in templates], human)


def cmd_apply_template(a):
    # apply_template refuses a paid template unless --force (it would corrupt a free resume)
    _result(_fc(a).apply_template(a.template_id, force=a.force), f"apply-template {a.template_id[:8]}")


def cmd_download(a):
    fc = _fc(a)
    if a.token:                                  # public download of any shared resume
        data = fc.download_public(a.token)
        out = a.output or f"{a.token}.pdf"
        with open(out, "wb") as f:
            f.write(data)
        n = len(data)
    else:
        out = fc.save_pdf(a.output or "resume.pdf", pages=a.pages)
        n = os.path.getsize(out)
    _emit({"saved": out, "bytes": n}, lambda: print(f"saved {out} ({n} bytes)"))


def cmd_publish(a):
    fc = _fc(a)
    env = fc.publish()

    def human():
        _result_human(env, "publish")
        print(f"  {fc.share_url()}")
    _emit(env, human)


def cmd_unpublish(a):
    _result(_fc(a).unpublish(), "unpublish")


def cmd_share(a):
    st = _fc(a).web_status()
    _emit(st, lambda: print(f"web resume: {'LIVE' if st['live'] else 'disabled'}\n"
                            f"share url : {st['url'] or '(none)'}"))


def cmd_md2html(a):
    html = md_to_html(_read(a.file, a.text))
    _emit({"html": html}, lambda: print(html))


def cmd_backups(a):
    backups = _fc(a).list_backups(all_resumes=a.all)

    def human():
        if not backups:
            print("no snapshots yet (they're auto-saved before rm-section / delete-resume)")
            return
        for b in backups:
            when = datetime.datetime.fromtimestamp(b["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {when}  {b['size']:>8}  {b['path']}")
    _emit(backups, human)


# ---- doctor: first-run / auth diagnostics --------------------------------
def _curl_cffi_available():
    """True if curl_cffi imports — only credential (email/password) login needs it."""
    try:
        import curl_cffi   # noqa: F401
        return True
    except Exception:
        return False


def _check(name, ok, detail):
    """A single doctor result: ok True=pass, False=fail, None=skipped/not-applicable."""
    return {"name": name, "ok": ok, "detail": detail}


def _doctor_auth_check(cfg, source):
    where = "; ".join(dotenv_files_found()) or "(none found)"
    if source:
        return _check("auth source", True, f"dotenv: {where}; using {source}")
    return _check("auth source", False, f"dotenv: {where}; no auth resolved — set "
                  "FLOWCV_COOKIE, or FLOWCV_EMAIL + FLOWCV_PASSWORD")


def _doctor_env_cookie_check(cfg):
    if not cfg.cookie:
        return _check("env cookie", None, "no FLOWCV_COOKIE set")
    if "flowcvsidapp=" in cfg.cookie:
        return _check("env cookie", True, "FLOWCV_COOKIE carries flowcvsidapp=")
    return _check("env cookie", False, "FLOWCV_COOKIE has no flowcvsidapp= — paste the "
                  "full name=value pair from DevTools, not just the value")


def _doctor_session_check():
    info = session_file_info()
    path = info["path"]
    if not info["exists"]:
        return _check("session file", None, f"no cached session ({path})")
    if info["mode"] != 0o600:
        return _check("session file", False, f"{path} perms are {info['mode']:04o}, "
                      f"expected 0600 — run: chmod 600 {path}")
    return _check("session file", True, f"{path} (0600, {info['age_days']:.0f} day(s) old)")


def _doctor_curl_cffi_check(source):
    if _curl_cffi_available():
        return _check("curl_cffi", True, "importable (used for email/password login)")
    if source and source.startswith("credentials"):
        return _check("curl_cffi", False, "NOT installed — required for email/password "
                      "login; run: pip install curl_cffi")
    return _check("curl_cffi", None, "not installed (only needed for `login` with "
                  "email/password)")


def _doctor_live_check(a, offline):
    if offline:
        return _check("live api", None, "skipped")
    try:
        fc = _fc(a)
        n = len(fc.list_resumes())
    except FlowCVError as e:
        return _check("live api", False, f"auth check failed: {e}")
    try:
        idnote = f"resume id {fc.resume_id} resolves"
    except FlowCVError as e:
        idnote = f"resume id unresolved ({e})"
    return _check("live api", True, f"auth valid — {n} resume(s); {idnote}")


def cmd_doctor(a):
    cfg = Config.load()
    source = resolve_auth_source(cfg)
    checks = [_doctor_auth_check(cfg, source),
              _doctor_env_cookie_check(cfg),
              _doctor_session_check(),
              _doctor_curl_cffi_check(source),
              _doctor_live_check(a, a.offline)]
    ok = all(c["ok"] is not False for c in checks)   # skipped (None) never fails

    def human():
        width = max(len(c["name"]) for c in checks)
        for c in checks:
            status = "ok" if c["ok"] else ("--" if c["ok"] is None else "FAIL")
            print(f"{status:<4}  {c['name']:<{width}}  {c['detail']}")
        n_ok = sum(c["ok"] is True for c in checks)
        n_fail = sum(c["ok"] is False for c in checks)
        n_skip = sum(c["ok"] is None for c in checks)
        print(f"summary: {n_ok} ok, {n_fail} failed, {n_skip} skipped")
    _emit({"checks": checks, "ok": ok}, human)
    if not ok:
        sys.exit(1)


# -------------------------------------------------------------------- parser
def build_parser():
    # --resume-id on a shared parent so it works BEFORE or AFTER the subcommand
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: the subparser shares this flag via parents=[]; a plain default
    # would be re-applied by the subcommand's parse and clobber a value given
    # BEFORE the subcommand (same issue as --json; read via getattr).
    common.add_argument("--resume-id", dest="resume_id_override",
                        default=argparse.SUPPRESS, help="target a specific resume")
    # default=SUPPRESS so this shared flag works BEFORE or AFTER the subcommand:
    # a plain default would be re-applied by the subparser and clobber a value the
    # top-level parser already set (read via getattr(args, "json", False)).
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable JSON output")
    p = argparse.ArgumentParser(prog="flowcv", description=__doc__, parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    add("login").set_defaults(fn=cmd_login)
    add("resumes").set_defaults(fn=cmd_resumes)

    s = add("new"); s.add_argument("title"); s.set_defaults(fn=cmd_new)
    s = add("duplicate"); s.add_argument("title", nargs="?"); s.set_defaults(fn=cmd_duplicate)
    s = add("rename"); s.add_argument("title"); s.set_defaults(fn=cmd_rename)
    s = add("delete-resume"); s.add_argument("--yes", action="store_true", help="confirm permanent deletion")
    s.add_argument("--no-backup", action="store_true", help="skip the auto-snapshot taken before deleting")
    s.set_defaults(fn=cmd_delete_resume)

    s = add("show"); s.add_argument("section", nargs="?"); s.set_defaults(fn=cmd_show)
    s = add("dump"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_dump)

    s = add("add"); s.add_argument("section")
    s.add_argument("--set", action="append", help="field=value (section-aware aliases: title,company,start,end,link)")
    s.add_argument("--section-name", help="display name to use if this creates a new section")
    s.add_argument("--icon", help="icon key to use if this creates a new section, e.g. code")
    g = s.add_mutually_exclusive_group(); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_add)

    s = add("rm"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_rm)

    s = add("reorder"); s.add_argument("section")
    s.add_argument("ids", nargs="+", help="entry ids in the desired order (all of the section's ids)")
    s.set_defaults(fn=cmd_reorder)
    s = add("hide"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_hide)
    s = add("show-entry"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_show_entry)
    s = add("rename-section"); s.add_argument("section"); s.add_argument("name"); s.set_defaults(fn=cmd_rename_section)
    s = add("section-icon"); s.add_argument("section"); s.add_argument("icon", help="icon key, e.g. briefcase")
    s.set_defaults(fn=cmd_section_icon)
    s = add("rm-section"); s.add_argument("section")
    s.add_argument("--yes", action="store_true", help="confirm deleting the section + its entries")
    s.add_argument("--no-backup", action="store_true", help="skip the auto-snapshot taken before deleting")
    s.set_defaults(fn=cmd_rm_section)
    s = add("reorder-sections")
    s.add_argument("ids", nargs="*", help="section ids in the desired order (omit to print the current order)")
    s.add_argument("--layout", default="one", help="column layout (one|two|mix; default one)")
    s.add_argument("--side", choices=["left", "right"],
                   help="which column to reorder (required with --layout two)")
    s.set_defaults(fn=cmd_reorder_sections)

    s = add("field"); s.add_argument("section"); s.add_argument("entry"); s.add_argument("field")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--file")
    s.set_defaults(fn=cmd_field)

    s = add("desc"); s.add_argument("section"); s.add_argument("entry")
    s.add_argument("--field", default=None,
                   help="rich-text field (default: auto by section — profile=text, skill=infoHtml, else description)")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_desc)

    s = add("date"); s.add_argument("section"); s.add_argument("entry")
    s.add_argument("--year"); s.add_argument("--month"); s.add_argument("--day")
    s.add_argument("--clear", action="store_true", help="reset the date before applying the parts given")
    s.set_defaults(fn=cmd_date)

    s = add("pd"); s.add_argument("field")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--file")
    s.set_defaults(fn=cmd_pd)

    add("links").set_defaults(fn=cmd_links)
    s = add("link"); s.add_argument("key"); s.add_argument("display"); s.add_argument("url"); s.set_defaults(fn=cmd_link)
    s = add("unlink"); s.add_argument("key"); s.set_defaults(fn=cmd_unlink)

    s = add("customize"); s.add_argument("path"); s.add_argument("value"); s.set_defaults(fn=cmd_customize)
    s = add("avatar"); s.add_argument("action", choices=["on", "off", "set", "remove"])
    s.add_argument("src", nargs="?", help="URL or file path (for `avatar set`)"); s.set_defaults(fn=cmd_avatar)
    add("templates").set_defaults(fn=cmd_templates)
    s = add("apply-template"); s.add_argument("template_id")
    s.add_argument("--force", action="store_true", help="apply even a paid template (needs a subscription)")
    s.set_defaults(fn=cmd_apply_template)

    s = add("download"); s.add_argument("-o", "--output")
    s.add_argument("--token", help="download a public resume by its share token (no auth)")
    s.add_argument("--pages", type=int, default=10, help="max pages to render (default 10)")
    s.set_defaults(fn=cmd_download)
    add("publish").set_defaults(fn=cmd_publish)
    add("unpublish").set_defaults(fn=cmd_unpublish)
    add("share").set_defaults(fn=cmd_share)

    s = add("export"); s.add_argument("-o", "--output", help="output JSON file (default resume-backup.json)")
    s.set_defaults(fn=cmd_export)
    s = add("import"); s.add_argument("file", help="a JSON backup produced by `export`")
    s.add_argument("--title", help="title for the restored resume (default: '<name> (restored)')")
    s.set_defaults(fn=cmd_import)

    s = add("backups", description="List local resume snapshots (auto-saved before "
            "rm-section / delete-resume). Restore one into a NEW resume with "
            "`flowcv import <file>`.")
    s.add_argument("--all", action="store_true", help="list snapshots for all resumes, not just the current one")
    s.set_defaults(fn=cmd_backups)

    s = add("doctor", description="Diagnose auth and first-run setup: dotenv files, "
            "auth source, session file perms/age, curl_cffi, and a live API check.")
    s.add_argument("--offline", action="store_true", help="skip the live API check")
    s.set_defaults(fn=cmd_doctor)

    s = add("md2html")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_md2html)
    return p


def main(argv=None):
    global _JSON
    args = build_parser().parse_args(argv)
    _JSON = bool(getattr(args, "json", False))
    try:
        args.fn(args)
    except FlowCVError as e:      # library errors -> exit 1
        if _JSON:                 # JSON mode: one error object on stdout
            print(json.dumps({"error": str(e), "type": type(e).__name__}, ensure_ascii=False))
            sys.exit(1)
        sys.exit(str(e))          # human mode: argparse-style message on stderr

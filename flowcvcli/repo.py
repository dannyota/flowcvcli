"""Resume as code: materialize a resume as a Markdown tree (`pull`) and apply
local edits back (`push`). See docs/PULLPUSH.md for the file layout and the
round-trip guarantee.

Serializer/parser/differ are pure functions; `pull`/`push` take a FlowCV client.
"""
import json
import os
import re
import shutil
import uuid

from .content import rich_field
from .markup import html_to_md, md_to_html

MANIFEST = ".flowcv.json"
PERSONAL = "personal.md"
SECTION_FILE = "_section.md"
_SECTION_DIR = re.compile(r"^\d\d-(.+)$")


# ----------------------------------------------------- frontmatter (no PyYAML)
def _json_parses(s):
    try:
        json.loads(s)
        return True
    except (ValueError, TypeError):
        return False


def _dump_val(v):
    """A value is written verbatim only when it's a string that round-trips;
    otherwise json.dumps it (numbers/bools/null/lists/dicts, or any string that
    would parse as JSON, has edge whitespace, or contains a newline)."""
    if (isinstance(v, str) and v == v.strip() and "\n" not in v
            and not _json_parses(v)):
        return v
    return json.dumps(v, ensure_ascii=False)


def _parse_val(text):
    """Inverse of _dump_val: json.loads, or the raw text on failure (plain str)."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def dump_frontmatter(d):
    """Serialize a flat dict to a `---`-fenced frontmatter block (trailing \\n)."""
    lines = ["---"]
    for k, v in d.items():
        lines.append(f"{k}: {_dump_val(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_frontmatter(text):
    """Return (fields_dict, body_str). No leading `---` fence -> ({}, text)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fm, i = {}, 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if line.strip():
            key, sep, raw = line.partition(":")
            if sep:
                # _dump_val writes "key: value"; drop exactly that one space
                val = raw[1:] if raw.startswith(" ") else raw
                fm[key.strip()] = _parse_val(val)
        i += 1
    body = "\n".join(lines[i + 1:]) if i < len(lines) else ""
    return fm, body.strip("\n")


# ------------------------------------------------------ entry / section <-> md
def _ordered(entry, rf):
    """Frontmatter fields for an entry (all but the rich field), id first."""
    keys = [k for k in entry if k != rf]
    keys.sort(key=lambda k: (k != "id", k != "isHidden"))  # id, isHidden, then rest
    return {k: entry[k] for k in keys}


def entry_to_md(entry, section):
    rf = rich_field(section)
    text = dump_frontmatter(_ordered(entry, rf))
    body = html_to_md(entry.get(rf) or "")
    if body:
        text += "\n" + body + "\n"
    return text


def md_to_entry(text):
    """Return (frontmatter_fields, body_markdown)."""
    return parse_frontmatter(text)


def section_to_md(sec):
    return dump_frontmatter({"displayName": sec.get("displayName"),
                             "iconKey": sec.get("iconKey"),
                             "sectionType": sec.get("sectionType")})


# --------------------------------------------------------------------- pull
def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def _clean(root):
    """Remove our own managed files/dirs (NN-* section dirs, personal.md,
    manifest), leaving anything else in the directory untouched."""
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if _SECTION_DIR.match(name) and os.path.isdir(p):
            shutil.rmtree(p)
        elif name in (PERSONAL, MANIFEST):
            os.remove(p)


def pull(fc, root):
    """Write the resume tree under `root`; return a summary dict."""
    with fc.batch():
        resume = fc.get_resume()
    os.makedirs(root, exist_ok=True)
    _clean(root)

    _write(os.path.join(root, PERSONAL),
           dump_frontmatter(resume.get("personalDetails") or {}))

    content = resume.get("content") or {}
    manifest = {}
    for si, (sid, sec) in enumerate(content.items()):
        secdir = "%02d-%s" % (si, sid)
        os.makedirs(os.path.join(root, secdir), exist_ok=True)
        _write(os.path.join(root, secdir, SECTION_FILE), section_to_md(sec))
        for ei, entry in enumerate(sec.get("entries") or []):
            eid = entry.get("id") or ""
            rel = "%s/%02d-%s.md" % (secdir, ei, eid[:8])
            _write(os.path.join(root, secdir, os.path.basename(rel)),
                   entry_to_md(entry, sid))
            manifest[eid] = rel

    _write(os.path.join(root, MANIFEST), json.dumps(
        {"resumeId": resume.get("id"), "pulledAt": fc.now_iso(),
         "entries": manifest}, indent=2, ensure_ascii=False) + "\n")
    return {"dir": root, "resumeId": resume.get("id"),
            "sections": len(content), "entries": len(manifest)}


# --------------------------------------------------------------------- push
def _read(path):
    with open(path) as f:
        return f.read()


def _entry_files(secpath):
    """(nn, name) entry files in a section dir, in NN order (skips _section.md)."""
    out = []
    for name in os.listdir(secpath):
        if name == SECTION_FILE or not name.endswith(".md"):
            continue
        m = re.match(r"^(\d+)-", name)
        out.append((int(m.group(1)) if m else 1 << 30, name))
    out.sort()
    return out


def _load_local(root):
    """Parse the tree: personal fields + [(sid, section_fields, [(fields, body, name)])]."""
    personal, _ = parse_frontmatter(_read(os.path.join(root, PERSONAL))) \
        if os.path.exists(os.path.join(root, PERSONAL)) else ({}, "")
    sections = []
    for name in sorted(os.listdir(root)):
        m = _SECTION_DIR.match(name)
        secpath = os.path.join(root, name)
        if not (m and os.path.isdir(secpath)):
            continue
        sid = m.group(1)
        smeta, _ = parse_frontmatter(_read(os.path.join(secpath, SECTION_FILE)))
        entries = []
        for _nn, fname in _entry_files(secpath):
            fm, body = parse_frontmatter(_read(os.path.join(secpath, fname)))
            entries.append((fm, body, fname))
        sections.append((sid, name, smeta, entries))
    return personal, sections


def push(fc, root, dry_run=False):
    """Diff the tree under `root` against the live resume; apply only changes.

    One read under batch(): all diffs are computed against that snapshot, then
    applied with low-level writers (no re-reads). Returns the list of actions.
    """
    actions = []

    def act(record, apply_fn):
        actions.append(record)
        if not dry_run:
            apply_fn()

    personal, sections = _load_local(root)
    manifest = {}
    # One read for the diff (batch reuses it for any reorder that refetches).
    with fc.batch():
        resume = fc.get_resume()
        content = resume.get("content") or {}

        # ---- personal (overlay onto live personalDetails) ----
        live_pd = resume.get("personalDetails") or {}
        if any(live_pd.get(k) != v for k, v in personal.items()):
            merged = dict(live_pd)
            merged.update(personal)
            act({"action": "personal"}, lambda pd=merged: fc.save_personal(pd))

        # ---- sections ----
        for sid, dirname, smeta, entries in sections:
            live_sec = content.get(sid)
            if live_sec is None:                 # never create a section
                actions.append({"action": "skip_section", "section": sid,
                                "reason": "not a live section"})
                continue
            _push_section_meta(fc, sid, live_sec, smeta, act)
            _push_entries(fc, sid, dirname, live_sec, entries, root, act,
                          dry_run, manifest)

    if manifest and not dry_run:
        _update_manifest(root, manifest)
    return actions


def _push_section_meta(fc, sid, live_sec, smeta, act):
    name = smeta.get("displayName")
    if name is not None and name != live_sec.get("displayName"):
        act({"action": "section_rename", "section": sid, "displayName": name},
            lambda: fc.rename_section(sid, name))
    icon = smeta.get("iconKey")
    if icon is not None and icon != live_sec.get("iconKey"):
        act({"action": "section_icon", "section": sid, "iconKey": icon},
            lambda: fc.set_section_icon(sid, icon))


def _push_entries(fc, sid, dirname, live_sec, entries, root, act, dry_run, manifest):
    rf = rich_field(sid)
    live_entries = {e.get("id"): e for e in live_sec.get("entries") or []}
    live_order = [e.get("id") for e in live_sec.get("entries") or []]
    file_order = []        # ids in file (NN) order; new entries get their fresh id
    file_ids = set()

    for fm, body, fname in entries:
        eid = fm.get("id")
        if eid and eid in live_entries:
            file_ids.add(eid)
            file_order.append(eid)
            _push_existing(fc, sid, rf, live_entries[eid], fm, body, act)
        elif eid:                      # id present but no live match -> skip
            act({"action": "skip_entry", "section": sid, "id": eid,
                 "reason": "no live entry with this id"}, lambda: None)
        else:                          # new file -> create (id generated locally)
            new_id = _add_entry(fc, sid, live_sec, fm, body, rf, dry_run)
            file_order.append(new_id)
            act({"action": "add_entry", "section": sid, "file": fname,
                 "id": new_id}, lambda: None)
            if new_id and not dry_run:
                _rewrite_id(os.path.join(root, dirname, fname), fm, body, new_id)
                manifest[new_id] = "%s/%s" % (dirname, fname)

    # deletions: live ids no file references
    for eid in live_order:
        if eid not in file_ids:
            act({"action": "delete_entry", "section": sid, "id": eid},
                lambda e=eid: fc.delete_entry(sid, e))

    # reorder: compare desired file order to the order push will leave behind
    # (surviving live order + new ids appended, mirroring add_entry).
    survivors = [e for e in live_order if e in file_ids]
    new_ids = [e for e in file_order if e not in live_entries]
    projected = survivors + new_ids
    if file_order != projected and len(file_order) > 1:
        act({"action": "reorder", "section": sid, "order": file_order},
            lambda o=list(file_order): fc.reorder_entries(sid, o))


# Bookkeeping timestamps: pulled into frontmatter for information, but never a
# reason to write — the server bumps updatedAt on every save, so diffing it
# would make each push echo forever (verified live).
_DIFF_SKIP = ("updatedAt", "createdAt")


def _push_existing(fc, sid, rf, live, fm, body, act):
    changed = [k for k, v in fm.items()
               if k not in _DIFF_SKIP and live.get(k) != v]
    body_changed = body.strip() != html_to_md(live.get(rf) or "").strip()
    if not changed and not body_changed:
        return
    entry = dict(live)
    entry.update(fm)
    if body_changed:
        entry[rf] = md_to_html(body)
    if "updatedAt" in entry:
        entry["updatedAt"] = fc.now_iso()

    def apply():
        fc.save_entry(sid, entry)
    act({"action": "update_entry", "section": sid, "id": live.get("id"),
         "fields": changed, "body": body_changed}, apply)


def _add_entry(fc, sid, live_sec, fm, body, rf, dry_run):
    """Create an entry in an existing section (two save_entry calls); return id."""
    if dry_run:
        return None
    new_id = str(uuid.uuid4())
    fc.save_entry(sid, {"id": new_id, "isHidden": False}, extra={
        "sectionType": live_sec.get("sectionType"),
        "sectionDisplayName": live_sec.get("displayName"),
        "sectionIconKey": live_sec.get("iconKey")})
    now = fc.now_iso()
    entry = {"id": new_id, "isHidden": False, "showPlaceholder": False,
             "createdAt": now, "updatedAt": now}
    entry.update({k: v for k, v in fm.items() if k != "id"})
    if body:
        entry[rf] = md_to_html(body)
    fc.save_entry(sid, entry)
    return new_id


def _rewrite_id(path, fm, body, new_id):
    """Write the assigned id back into a new entry's file so a re-push is a no-op."""
    fields = {"id": new_id}
    fields.update({k: v for k, v in fm.items() if k != "id"})
    text = dump_frontmatter(fields)
    if body:
        text += "\n" + body + "\n"
    _write(path, text)


def _update_manifest(root, added):
    path = os.path.join(root, MANIFEST)
    try:
        m = json.loads(_read(path))
    except (OSError, ValueError):
        m = {"entries": {}}
    m.setdefault("entries", {}).update(added)
    _write(path, json.dumps(m, indent=2, ensure_ascii=False) + "\n")

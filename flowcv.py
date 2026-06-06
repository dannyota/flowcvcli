#!/usr/bin/env python3
"""flowcv-cli — fetch, inspect, and edit a FlowCV resume from the command line.

It talks to FlowCV's private JSON API (the same calls the web app makes), so it
works for ANY FlowCV resume — supply your own resume id + session cookie.

Configuration (.env next to this script, or env vars; gitignore the secrets):
        FLOWCV_RESUME_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  Auth — pick ONE:
        FLOWCV_COOKIE=flowcvsidapp=s%3A...        # the session cookie only, OR
        FLOWCV_EMAIL=you@example.com              # log in with credentials;
        FLOWCV_PASSWORD=...                       # session is cached to .flowcv_session
  No resume id? Run `resumes` to list them, then set FLOWCV_RESUME_ID or pass --resume-id.

How to get them (Chrome/Firefox DevTools):
  * RESUME_ID  — open the resume; it's the UUID in the editor URL.
  * COOKIE     — DevTools > Application > Cookies > app.flowcv.com >
                 copy the `flowcvsidapp` value as `flowcvsidapp=<value>`.
                 That single cookie is the auth; it expires — refresh when GET 401s.

Commands
  login                                 log in with FLOWCV_EMAIL/PASSWORD, cache session to .flowcv_session
  resumes                               list all resumes on the account (id, title, web token)
  get                                   fetch -> resume_raw.json (+ timestamped backup)
  show [section]                        list sections + entries (id + label + dates)
  dump <section> <id>                   print one entry (readable text + raw fields)
  (any command accepts --resume-id <id> to target a specific resume)

  desc <section> <id> [--field F] (--file md | --text s)
                                        markdown -> FlowCV HTML, write to a field
                                        (default field: description; use --field text for the summary)
  field <section> <id> <field> (--text v | --file f)
                                        set a raw scalar/HTML field value

  pd <field> --text V                   set a personalDetails scalar (jobTitle, phone, address, fullName, ...)
  links                                 list header links (social entries) + display order
  link <key> <display> <url>            add/update a header link (key e.g. orcid, googlescholar, github)
  unlink <key>                          remove (delete) a header link
  linkedin <display>                    relabel the LinkedIn link (display only)

  add <section> [--file md | --text s] [--set k=v ...]
                                        create a new entry (appends to bottom) and populate it
                                        aliases for --set: title,company,start,end,link
  rm <section> <id>                     delete an entry

  share                                 show web-resume status + public share URL
  publish                               enable the public web resume (prints share URL)
  unpublish                             disable the public web resume
  download [-o FILE] [--pages N]        download the rendered PDF (default resume.pdf)

  md2html (--file F | --text S)         convert markdown -> FlowCV HTML and print (offline, no write)

Markdown mini-format (for `desc` / `add`)
  blank line separates blocks · "## Heading" or "**Whole line bold**" -> bold subheader
  "- text" -> bullets (consecutive = one list) · anything else -> paragraph
  inline **bold** works inside paragraphs and bullets
"""
import argparse
import copy
import datetime
import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "https://app.flowcv.com/api/resumes"
ROOT = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/148.0.0.0 Safari/537.36")
J = ' style="text-align: justify"'
ALIASES = {"title": "jobTitle", "company": "employer", "start": "startDateNew",
           "end": "endDateNew", "link": "employerLink"}
# sectionId -> (sectionType, default displayName, iconKey) for creating sections that
# don't exist yet (the values FlowCV uses when you "Add content").
SECTION_META = {
    "profile": ("profile", "Summary", "address-card"),
    "work": ("work", "Professional Experience", "briefcase"),
    "education": ("education", "Education", "graduation-cap"),
    "skill": ("skill", "Skills", "head-side-brain"),
    "publication": ("publication", "Publications", "newspaper"),
    "organisation": ("organisation", "Organisations", "house-user"),
    "custom1": ("custom", "Custom", "star"),
}

API = "https://app.flowcv.com/api"
SESSION_FILE = os.path.join(ROOT, ".flowcv_session")
_CFG = None


def _load_dotenv():
    fv = {}
    for name in (".env", ".flowcv_env"):  # .env preferred; .flowcv_env kept for back-compat
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.rstrip("\n")
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)   # split first '='; cookie value may contain '='
                    fv.setdefault(k.strip(), v)
    return fv


def _conf(fv, *keys):
    for k in keys:
        v = os.environ.get(k) or fv.get(k)
        if v:
            return v
    return None


def _multipart(fields):
    boundary = "----flowcvcli" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out += [f"--{boundary}", f'Content-Disposition: form-data; name="{k}"', "", v]
    out += [f"--{boundary}--", ""]
    return boundary, "\r\n".join(out).encode()


def login(email, password):
    """POST /api/auth/login (multipart email+password) -> session cookie string."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = {"user-agent": UA, "origin": "https://app.flowcv.com",
            "accept": "application/json, text/plain, */*"}
    opener.open(urllib.request.Request(f"{API}/auth/init_user", headers=base), timeout=30).read()
    boundary, body = _multipart({"email": email, "password": password,
                                 "resumeData": "undefined", "letterData": "undefined",
                                 "resumeImg": "", "letterImg": ""})
    h = dict(base, **{"content-type": f"multipart/form-data; boundary={boundary}"})
    resp = opener.open(urllib.request.Request(f"{API}/auth/login", data=body, headers=h, method="POST"), timeout=30)
    data = json.loads(resp.read().decode())
    if not data.get("success"):
        sys.exit(f"login failed: {json.dumps(data)[:200]}")
    cookie = "; ".join(f"{c.name}={c.value}" for c in jar if c.name == "flowcvsidapp")
    if "flowcvsidapp" not in cookie:
        sys.exit("login succeeded but no session cookie was set")
    return cookie


def cfg():
    """Resolve auth + resume id. Cookie precedence: env/file COOKIE > cached session >
    fresh login with EMAIL+PASSWORD (cached to .flowcv_session)."""
    global _CFG
    if _CFG is not None:
        return _CFG
    fv = _load_dotenv()
    rid = _conf(fv, "FLOWCV_RESUME_ID", "RESUME_ID")
    email = _conf(fv, "FLOWCV_EMAIL", "EMAIL")
    password = _conf(fv, "FLOWCV_PASSWORD", "PASSWORD")
    cookie = _conf(fv, "FLOWCV_COOKIE", "COOKIE")
    if not cookie and os.path.exists(SESSION_FILE):
        cookie = open(SESSION_FILE).read().strip() or None
    if not cookie and email and password:
        cookie = login(email, password)
        with open(SESSION_FILE, "w") as f:
            f.write(cookie)
    if not cookie:
        sys.exit("No auth. Set FLOWCV_COOKIE, or FLOWCV_EMAIL + FLOWCV_PASSWORD, in .env. See --help.")
    _CFG = {"resume_id": rid, "cookie": cookie, "email": email, "password": password}
    return _CFG


def resume_id():
    rid = cfg()["resume_id"]
    if not rid:
        sys.exit("This command needs a resume id. Set FLOWCV_RESUME_ID (or pass --resume-id).")
    return rid


def _relogin():
    """Session expired -> drop cache and log in again with stored credentials."""
    c = cfg()
    if not (c.get("email") and c.get("password")):
        return False
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass
    c["cookie"] = login(c["email"], c["password"])
    with open(SESSION_FILE, "w") as f:
        f.write(c["cookie"])
    return True


# ------------------------------------------------------------------------- http
def _req(path, method="GET", body=None, query=None):
    url = f"{BASE}/{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"accept": "application/json, text/plain, */*", "user-agent": UA,
               "cookie": cfg()["cookie"], "origin": "https://app.flowcv.com"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def now_iso():
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


# ------------------------------------------------------------------- resume ops
def get_resume(save=True):
    status, text = _req(resume_id())
    if status in (401, 403) and _relogin():
        status, text = _req(resume_id())
    if status != 200:
        sys.exit(f"GET failed: HTTP {status} (session expired? refresh FLOWCV_COOKIE, "
                 f"or set FLOWCV_EMAIL/PASSWORD for auto re-login)\n{text[:200]}")
    if save:
        with open(os.path.join(ROOT, "resume_raw.json"), "w") as f:
            f.write(text)
    return status, json.loads(text)


def list_resumes():
    status, text = _req("all")
    data = json.loads(text)
    if not data.get("success"):
        sys.exit(f"list failed: {json.dumps(data)[:200]}")
    return data["data"]["resumes"]


def content(resume):
    return resume["data"]["resume"]["content"]


def find_section(resume, section):
    c = content(resume)
    if section not in c:
        sys.exit(f"no such section '{section}'. available: {', '.join(c)}")
    return c[section]


def find_entry(resume, section, entry_id):
    for e in find_section(resume, section)["entries"]:
        if e.get("id") == entry_id:
            return e
    sys.exit(f"entry {entry_id} not found in {section}")


def save_entry(section, entry, extra=None):
    body = {"resumeId": resume_id(), "sectionId": section, "entry": entry}
    if extra:
        body.update(extra)
    status, text = _req("save_entry", method="PATCH", body=body)
    return status, json.loads(text)


def save_personal_details(pd):
    status, text = _req("save_personal_details", method="PATCH",
                        body={"resumeId": resume_id(), "personalDetails": pd})
    return status, json.loads(text)


def delete_entry(section, entry_id):
    status, text = _req("delete_entry", method="DELETE",
                        query={"resumeId": resume_id(), "sectionId": section, "entryId": entry_id})
    return status, json.loads(text)


def publish_web_resume(publish):
    status, text = _req("publish_web_resume", method="PATCH",
                        body={"publish": bool(publish), "resumeId": resume_id()})
    return status, json.loads(text)


def share_url(resume):
    token = resume["data"]["resume"].get("webToken")
    return f"https://flowcv.com/resume/{token}" if token else None


def download_pdf(pages):
    """GET /api/resumes/download -> PDF bytes (with re-login retry on expiry)."""
    def go():
        url = f"{BASE}/download?" + urllib.parse.urlencode(
            {"resumeId": resume_id(), "previewPageCount": pages})
        req = urllib.request.Request(url, headers={
            "accept": "application/json, text/plain, */*", "user-agent": UA,
            "cookie": cfg()["cookie"]})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    status, data = go()
    if status in (401, 403) and _relogin():
        status, data = go()
    return status, data


def _ok(label, status, resp):
    flag = resp.get("success")
    print(f"{label} -> HTTP {status} success={flag}")
    if not flag:
        print(f"  ! {json.dumps(resp)[:200]}")
    return flag


# ---------------------------------------------------------------- markdown/html
def _esc(s):
    """Escape text, then honor inline **bold**."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(s, quote=False))


def md_to_html(md):
    parts, bullets = [], []

    def flush():
        if bullets:
            lis = "".join(f"<li{J}><p{J}>{_esc(b)}</p></li>" for b in bullets)
            parts.append(f"<ul>{lis}</ul>")
            bullets.clear()

    for raw in md.splitlines():
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
        elif len(line) > 4 and line.startswith("**") and line.endswith("**"):
            parts.append(f"<p{J}><strong>{html.escape(line[2:-2].strip(), quote=False)}</strong></p>")
        else:
            parts.append(f"<p{J}>{_esc(line)}</p>")
    flush()
    return "".join(parts)


def html_to_text(h):
    return re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", h or "")).replace("&amp;", "&").strip()


def _read(file=None, text=None):
    if file:
        with open(file) as f:
            return f.read().strip()
    return text


def label_of(e):
    for k in ("jobTitle", "employer", "title", "degree", "skill", "position",
              "publicationTitle", "organisationName"):
        if e.get(k):
            return e[k]
    return "(empty)"


# ---------------------------------------------------------------------- commands
def cmd_get(a):
    get_resume()
    backup = f"backup_resume_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
    with open(os.path.join(ROOT, backup), "w") as f, open(os.path.join(ROOT, "resume_raw.json")) as src:
        f.write(src.read())
    print(f"GET ok -> resume_raw.json (backup: {backup})")


def cmd_show(a):
    _, resume = get_resume(save=False)
    for sec, obj in content(resume).items():
        if a.section and sec != a.section:
            continue
        print(f"[{sec}] '{obj.get('displayName')}' ({len(obj['entries'])} entries)")
        for e in obj["entries"]:
            d = f"  {e.get('startDateNew','')}–{e.get('endDateNew','')}" if e.get("startDateNew") or e.get("endDateNew") else ""
            print(f"   {e['id']}  {label_of(e)}{d}")


def cmd_dump(a):
    _, resume = get_resume(save=False)
    for k, v in find_entry(resume, a.section, a.entry).items():
        if k in ("description", "infoHtml", "text"):
            print(f"  {k} (text): {html_to_text(v)}")
            print(f"  {k} (html): {v}")
        else:
            print(f"  {k}: {v!r}")


def cmd_field(a):
    _, resume = get_resume(save=False)
    e = copy.deepcopy(find_entry(resume, a.section, a.entry))
    e[a.field] = _read(a.file, a.text)
    if "updatedAt" in e:
        e["updatedAt"] = now_iso()
    _ok(f"{a.section}/{a.entry[:8]}.{a.field}", *save_entry(a.section, e))


def cmd_desc(a):
    _, resume = get_resume(save=False)
    e = copy.deepcopy(find_entry(resume, a.section, a.entry))
    e[a.field] = md_to_html(_read(a.file, a.text))
    if "updatedAt" in e:
        e["updatedAt"] = now_iso()
    _ok(f"{a.section}/{a.entry[:8]}.{a.field}", *save_entry(a.section, e))


def cmd_pd(a):
    _, resume = get_resume(save=False)
    pd = copy.deepcopy(resume["data"]["resume"]["personalDetails"])
    pd[a.field] = a.text
    _ok(f"personalDetails.{a.field}", *save_personal_details(pd))


def cmd_links(a):
    _, resume = get_resume(save=False)
    pd = resume["data"]["resume"]["personalDetails"]
    order = pd.get("detailsOrder", [])
    print("detailsOrder:", " ".join(order))
    for k, v in pd.get("social", {}).items():
        tag = "shown" if k in order else "hidden"
        print(f"  {k}: {v.get('display')} -> {v.get('link')} [{tag}]")


def cmd_link(a):
    """Add/update a header link as a social entry (orcid, googlescholar, github, ...)."""
    _, resume = get_resume(save=False)
    pd = copy.deepcopy(resume["data"]["resume"]["personalDetails"])
    social = json.loads(json.dumps(pd.get("social", {})))
    social[a.key] = {"display": a.display, "link": a.url}
    pd["social"] = social
    order = list(pd.get("detailsOrder", []))
    if a.key not in order:
        order.append(a.key)
    pd["detailsOrder"] = order
    _ok(f"link {a.key} ({a.display})", *save_personal_details(pd))


def cmd_unlink(a):
    """Remove (delete) a header link from social + detailsOrder."""
    _, resume = get_resume(save=False)
    pd = copy.deepcopy(resume["data"]["resume"]["personalDetails"])
    social = json.loads(json.dumps(pd.get("social", {})))
    if social.pop(a.key, None) is None:
        sys.exit(f"no social link '{a.key}' (have: {', '.join(social) or 'none'})")
    pd["social"] = social
    pd["detailsOrder"] = [k for k in pd.get("detailsOrder", []) if k != a.key]
    _ok(f"unlink {a.key}", *save_personal_details(pd))


def cmd_linkedin(a):
    _, resume = get_resume(save=False)
    pd = copy.deepcopy(resume["data"]["resume"]["personalDetails"])
    social = json.loads(json.dumps(pd.get("social", {})))
    social.setdefault("linkedIn", {})["display"] = a.display
    pd["social"] = social
    _ok(f"linkedIn.display={a.display}", *save_personal_details(pd))


def cmd_add(a):
    _, resume = get_resume(save=False)
    c = content(resume)
    if a.section in c:                       # existing section -> reuse its meta
        sec = c[a.section]
        meta = {"sectionType": sec.get("sectionType"), "sectionDisplayName": sec.get("displayName"),
                "sectionIconKey": sec.get("iconKey")}
    elif a.section in SECTION_META:          # new section -> create it from the registry
        st, dn, ik = SECTION_META[a.section]
        meta = {"sectionType": st, "sectionDisplayName": dn, "sectionIconKey": ik}
    else:
        sys.exit(f"unknown section '{a.section}'. Existing: {', '.join(c)}. "
                 f"Creatable: {', '.join(SECTION_META)}.")
    new_id = str(uuid.uuid4())
    if not _ok("create blank", *save_entry(a.section, {"id": new_id, "isHidden": False}, extra=meta)):
        sys.exit("create failed")
    e = {"id": new_id, "isHidden": False, "showPlaceholder": False,
         "createdAt": now_iso(), "updatedAt": now_iso()}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        e[ALIASES.get(k, k)] = v
    if a.file or a.text:
        e["description"] = md_to_html(_read(a.file, a.text))
    _ok(f"populate {label_of(e)}", *save_entry(a.section, e))
    print(f"  new id: {new_id}")


def cmd_rm(a):
    _ok(f"delete {a.section}/{a.entry[:8]}", *delete_entry(a.section, a.entry))


def cmd_share(a):
    _, resume = get_resume(save=False)
    live = resume["data"]["resume"].get("webResumeLive")
    print(f"web resume: {'LIVE' if live else 'disabled'}")
    print(f"share url : {share_url(resume) or '(no web token)'}")


def cmd_publish(a):
    if _ok("publish", *publish_web_resume(True)):
        _, resume = get_resume(save=False)
        print(f"  live at: {share_url(resume)}")


def cmd_unpublish(a):
    _ok("unpublish", *publish_web_resume(False))


def cmd_resumes(a):
    for r in list_resumes():
        live = "live" if r.get("webResumeLive") else "private"
        print(f"  {r['id']}  {(r.get('title') or '(untitled)'):20}  web:{r.get('webToken','-')} [{live}]")


def cmd_login(a):
    c = cfg()
    if not (c.get("email") and c.get("password")):
        sys.exit("Set FLOWCV_EMAIL and FLOWCV_PASSWORD in .env to use `login`.")
    with open(SESSION_FILE, "w") as f:
        f.write(login(c["email"], c["password"]))
    print("login ok -> session cached to .flowcv_session")


def cmd_download(a):
    status, data = download_pdf(a.pages)
    if status != 200 or data[:4] != b"%PDF":
        sys.exit(f"download failed: HTTP {status} ({data[:120]!r})")
    out = a.output or "resume.pdf"
    with open(out, "wb") as f:
        f.write(data)
    print(f"saved {out} ({len(data)} bytes)")


def cmd_md2html(a):
    print(md_to_html(_read(a.file, a.text)))


def build_parser():
    p = argparse.ArgumentParser(prog="flowcv", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resume-id", dest="resume_id_override", help="override FLOWCV_RESUME_ID for this run")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("get").set_defaults(fn=cmd_get)
    sub.add_parser("resumes").set_defaults(fn=cmd_resumes)
    sub.add_parser("login").set_defaults(fn=cmd_login)
    s = sub.add_parser("show"); s.add_argument("section", nargs="?"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("dump"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_dump)
    s = sub.add_parser("field"); s.add_argument("section"); s.add_argument("entry"); s.add_argument("field")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--file")
    s.set_defaults(fn=cmd_field)
    s = sub.add_parser("desc"); s.add_argument("section"); s.add_argument("entry")
    s.add_argument("--field", default="description")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_desc)
    s = sub.add_parser("pd"); s.add_argument("field"); s.add_argument("--text", required=True); s.set_defaults(fn=cmd_pd)
    sub.add_parser("links").set_defaults(fn=cmd_links)
    s = sub.add_parser("link"); s.add_argument("key"); s.add_argument("display"); s.add_argument("url")
    s.set_defaults(fn=cmd_link)
    s = sub.add_parser("unlink"); s.add_argument("key"); s.set_defaults(fn=cmd_unlink)
    s = sub.add_parser("linkedin"); s.add_argument("display"); s.set_defaults(fn=cmd_linkedin)
    s = sub.add_parser("add"); s.add_argument("section")
    s.add_argument("--set", action="append", help="field=value (repeatable; aliases: title,company,start,end,link)")
    g = s.add_mutually_exclusive_group(); g.add_argument("--file"); g.add_argument("--text"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("rm"); s.add_argument("section"); s.add_argument("entry"); s.set_defaults(fn=cmd_rm)
    sub.add_parser("share").set_defaults(fn=cmd_share)
    sub.add_parser("publish").set_defaults(fn=cmd_publish)
    sub.add_parser("unpublish").set_defaults(fn=cmd_unpublish)
    s = sub.add_parser("download"); s.add_argument("-o", "--output")
    s.add_argument("--pages", type=int, default=10); s.set_defaults(fn=cmd_download)
    s = sub.add_parser("md2html")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--file"); g.add_argument("--text")
    s.set_defaults(fn=cmd_md2html)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    if getattr(args, "resume_id_override", None):
        os.environ["FLOWCV_RESUME_ID"] = args.resume_id_override
    args.fn(args)

# flowcvcli

[![PyPI](https://img.shields.io/pypi/v/flowcvcli.svg)](https://pypi.org/project/flowcvcli/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://pypi.org/project/flowcvcli/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Control a [FlowCV](https://flowcv.com) resume from the **command line** or from
**Python** — content, header & links, **customization**, **templates**,
**avatar**, reorder/hide, multi-resume management, **backup/restore**, publish, and **PDF export**.
It drives FlowCV's private JSON API (the same calls the web app makes), so it
works for any FlowCV resume with your own session. **Zero dependencies** (Python
standard library only), so it's easy to drop into scripts and LLM agents.

> Unofficial and not affiliated with FlowCV. It uses FlowCV's undocumented
> internal API and may break if that changes; use it with your own account and at
> your own risk (mind FlowCV's Terms of Service). See [`docs/API.md`](docs/API.md)
> for the reverse-engineered API and [`docs/RENDERING.md`](docs/RENDERING.md) for
> how the editor renders the live preview and persists edits.

## Install

```bash
pip install flowcvcli          # installs the `flowcv` command
```

Or run from source without installing:

```bash
git clone https://github.com/dannyota/flowcvcli && cd flowcvcli
python3 flowcv.py --help       # equivalent to the `flowcv` command
```

## Configure

Put a `.env` in the directory you run `flowcv` from (or in
`~/.config/flowcvcli/.env`). Real environment variables override it.

```dotenv
# Auth — pick ONE:
FLOWCV_COOKIE=flowcvsidapp=s%3A...     # your session cookie, OR
# FLOWCV_EMAIL=you@example.com         # log in with credentials instead
# FLOWCV_PASSWORD=...                  #   (session cached to ~/.config/flowcvcli/session)

# FLOWCV_RESUME_ID=...                 # optional; only if your account has several resumes
```

- **Cookie**: DevTools → Application → Cookies → `app.flowcv.com` → copy the
  `flowcvsidapp` value. That single cookie is the auth.
- **Credentials**: with `FLOWCV_EMAIL` + `FLOWCV_PASSWORD` the tool logs in and
  caches the session (re-login is automatic when the cookie expires). The cache
  is written `0600` to `~/.config/flowcvcli/session` (override with
  `$FLOWCV_SESSION_FILE`).
- **Resume id** is optional: with one resume it's auto-selected; with several,
  set `FLOWCV_RESUME_ID` or pass `--resume-id <id>` (run `flowcv resumes` to list).

## CLI

```bash
flowcv resumes                       # list resumes (id, title, share token)
flowcv show [section]                # sections + entries (ids, labels, dates)
flowcv dump <section> <id>           # one entry, fields + rich text

# manage resumes (multi-resume / paid plans)
flowcv new "My Second Resume"        # new resume (same details+style, no content) -> prints id
flowcv duplicate ["Copy title"]      # full copy of the current resume
flowcv rename "New Title"            # rename the current resume
flowcv delete-resume --yes           # permanent (refuses without --yes)

# content (markdown mini-format below); `add` creates the section if needed.
# --set aliases (title/company/link) resolve per section (work->jobTitle, publication->title…)
flowcv add work --set title="Engineer" --set company="Acme" \
       --set start=01/2022 --set end=Present --text $'- Did a measurable thing.'
flowcv add custom2 --section-name "Open Source" --icon code --text "…"   # heading+icon at creation
flowcv desc work <id> --file role.md           # rich text; --field is optional (auto: profile=text, skill=infoHtml)
flowcv date publication <id> --year 2018       # structured date; merges (only passed parts change), --clear resets
flowcv field work <id> employer --text "Acme Corp"
flowcv rm work <id>

# reorder / hide / sections
flowcv reorder work <id3> <id1> <id2>     # set entry order (all of the section's ids)
flowcv hide work <id> ; flowcv show-entry work <id>
flowcv rename-section skill "Core Skills"
flowcv section-icon skill head-side-brain
flowcv rm-section custom1 --yes           # delete a section + its entries
flowcv reorder-sections profile work skill education   # set one-column order (no args = print current)
flowcv reorder-sections work skill --layout two --side left   # two-column: order one column at a time

# header details & links (links are social entries: orcid, googlescholar, github…)
flowcv pd jobTitle --text "Security Leader"
flowcv link orcid ORCID https://orcid.org/0000-0000-0000-0000
flowcv unlink orcid ; flowcv links

# avatar
flowcv avatar set https://example.com/me.png   # upload from URL or file
flowcv avatar on | off | remove

# styling (a delta into resume.customization) and templates
flowcv customize font.fontFamily "Source Sans Pro"
flowcv customize colors.basic.single '"#0e374e"'
flowcv templates                     # lists each as [free] / [PAID] (paid needs a subscription)
flowcv apply-template <templateId>   # warns first if the template is paid

# render & share
flowcv download -o resume.pdf        # the rendered PDF (--pages N caps rendered pages; default 10)
flowcv download --token <webToken> -o out.pdf   # any PUBLIC resume by its share token (no auth)
flowcv share | publish | unpublish

# backup / restore
flowcv export -o backup.json          # full resume snapshot (JSON) — keep one before big edits
flowcv import backup.json             # restore the snapshot into a NEW resume (non-destructive)

flowcv login                          # refresh the cached session
flowcv md2html --file role.md         # preview HTML (offline)
```

Any command takes `--resume-id <id>` to target a specific resume, and `--json`
(before or after the subcommand) to emit exactly one machine-readable JSON
document instead of human text — errors become `{"error", "type"}` on stdout
with exit 1. (From source, replace `flowcv` with `python3 flowcv.py`.)

## Library (for scripts & LLM agents)

```python
from flowcvcli import FlowCV

fc = FlowCV()                                   # or FlowCV(resume_id="...")
fc.set_personal_field("fullName", "Jane Doe")
fc.add_entry("work", sets={"jobTitle": "Engineer", "employer": "Acme",
                           "startDateNew": "01/2022", "endDateNew": "Present"},
             md="- Shipped a thing with **measurable** impact.")
fc.set("font.fontFamily", "Source Sans Pro")    # a customization delta
fc.set_photo("https://example.com/me.png")      # avatar from URL
fc.apply_template("a3fb6c37-...")               # a design from list_templates()
fc.save_pdf("resume.pdf")                        # render to PDF

# structure & resume management
fc.reorder_entries("work", ["id3", "id1", "id2"])   # set entry order
fc.rename_section("skill", "Core Skills"); fc.delete_section("custom1")
fc.hide_entry("work", "id", hidden=True)
new_id = fc.create_resume("Second Resume")          # or fc.duplicate_resume()
fc.rename_resume("New Title"); fc.delete_resume()    # delete is permanent
fc.set_date("publication", "id", year=2018)         # structured date (year-only)

# backup / restore
import json
json.dump(fc.export_resume(), open("backup.json", "w"))   # full snapshot
new_id = fc.import_resume(json.load(open("backup.json")))  # restore into a NEW resume

# many edits? batch caches the read (1 GET instead of N against the rate limit)
with fc.batch():
    fc.set_field("work", "id", "employer", "Acme Corp")
    fc.set_date("publication", "id", year=2018)

# errors are normal exceptions (they never SystemExit your process):
from flowcvcli import FlowCVError, AuthError, RateLimitError, NotFoundError
try:
    fc.find_entry(fc.get_resume(), "work", "bad-id")
except NotFoundError as e:
    print(e)                                    # all subclass FlowCVError
```

### Build → render → check → improve

The PDF *is* the rendered output. An agent can write content, `save_pdf(...)`,
**open the PDF to see the actual layout**, then adjust and re-render — a closed
feedback loop for building a resume from raw info.

## Markdown mini-format (`desc` / `add`)

| You write | You get |
|---|---|
| blank line | block separator |
| `## Heading` / `**Whole line bold**` | bold subheader |
| `***Whole line***` | bold + italic subheader |
| `- item` | bullet (consecutive = one list) |
| anything else | justified paragraph |
| `**bold**` / `***bold-italic***` inline | `<strong>` / `<strong><em>…</em></strong>` |
| `[text](url)` inline | link |

## How it works

- **Read-modify-write**: edits fetch the resume, change one part, and send it
  back — unrelated fields are never touched.
- New entries append to the bottom of their section; use `reorder` to change order.
- The on-screen preview is client-side HTML; the **PDF download is a separate
  server render** of the same data (details in [`docs/RENDERING.md`](docs/RENDERING.md)).

> **Scope:** this tool covers **resumes**. The same FlowCV account also has Cover
> Letters, Job Tracker, Email Signatures and Personal Websites (separate APIs —
> see `docs/API.md` "Other FlowCV products"); documented but not implemented here.

## Project layout

```
flowcvcli/             # the package (import flowcvcli)
  config.py            #   resolve resume id + auth from .env / env vars
  client.py            #   HTTP, login, cookie-jar session, retry, get_resume
  markup.py            #   markdown <-> FlowCV rich-text HTML
  content.py           #   sections & entries (add/edit/reorder/hide/sections)
  personal.py          #   header details & links
  customization.py     #   styling deltas & templates
  photo.py             #   avatar upload / toggle
  resume.py            #   list, create/duplicate/rename/delete, download, publish
  api.py               #   FlowCV = Client + all mixins
  cli.py / __main__.py #   the `flowcv` command
docs/API.md            # reverse-engineered API reference
docs/RENDERING.md      # how the editor renders the preview & debounces saves
flowcv.py              # source-tree entry point (python3 flowcv.py …)
```

## License

[MIT](LICENSE) © dannyota

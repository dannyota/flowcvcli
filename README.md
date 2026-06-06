# flowcv-cli

Control a [FlowCV](https://flowcv.com) resume from the command line **or** from
Python — content, header, links, **customization**, **templates**, **avatar**,
and PDF render. It drives FlowCV's private JSON API (the same calls the web app
makes), so it works for any FlowCV resume with your own session.

> Unofficial; undocumented API; for personal use. Standard library only
> (Python 3.8+) — no `pip install`. Auth is your own `flowcvsidapp` session
> cookie (or email/password). See [`docs/API.md`](docs/API.md) for the API and
> [`docs/RENDERING.md`](docs/RENDERING.md) for how the live preview renders/saves.

## Layout

```
flowcv.py              # thin entry point (python3 flowcv.py …)
flowcvcli/             # the package
  config.py            #   resolve resume id + auth from .env / env vars
  client.py            #   HTTP, login, session cache, 401 re-login, get_resume
  markup.py            #   markdown <-> FlowCV rich-text HTML
  content.py           #   ContentMixin   — sections & entries
  personal.py          #   PersonalMixin  — header details & links
  customization.py     #   CustomizationMixin — styling deltas & templates
  photo.py             #   PhotoMixin     — avatar upload / toggle
  resume.py            #   ResumeMixin    — list, download, publish, share
  api.py               #   FlowCV = Client + all mixins
  cli.py               #   argparse CLI over FlowCV
docs/API.md            # reverse-engineered API reference
docs/RENDERING.md      # how the editor renders the live preview & debounces saves
```

> Scope: this tool covers **resumes**. The same FlowCV account/session also has
> Cover Letters, Job Tracker, Email Signatures and Personal Websites (separate
> APIs — see `docs/API.md` "Other FlowCV products"); those are documented but not
> yet implemented here.

## Setup

```bash
cp .env.example .env
```

```dotenv
FLOWCV_RESUME_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# auth — pick ONE:
FLOWCV_COOKIE=flowcvsidapp=s%3A...          # the session cookie only, OR
FLOWCV_EMAIL=you@example.com                # log in with credentials
FLOWCV_PASSWORD=...                         # (session cached to .flowcv_session)
```

- **RESUME_ID** is **optional** — with one resume the tool auto-selects it; set it
  (or pass `--resume-id`) only if your account has several (`flowcv.py resumes`
  lists them and a multi-resume run will prompt you to choose).
- **COOKIE** — DevTools → Application → Cookies → `app.flowcv.com` → the
  `flowcvsidapp` value. That single cookie is the auth; it expires (re-login is
  automatic when email/password are set). Env vars override `.env`. Secrets are
  gitignored.

> `download` with no `--token` renders **your own** resume; `download --token
> <webToken>` fetches **any public** resume (e.g. to test or pull a candidate's).

## CLI

```bash
python3 flowcv.py resumes                       # list resumes (id, title, share token)
python3 flowcv.py show [section]                # sections + entries (ids, labels, dates)
python3 flowcv.py dump <section> <id>           # one entry, fields + rich text

# content (markdown mini-format below); `add` creates the section if needed
python3 flowcv.py add work --set title="Engineer" --set company="Acme" \
        --set start=01/2022 --set end=Present --text $'- Did a measurable thing.'
python3 flowcv.py desc work <id> --file role.md
python3 flowcv.py field work <id> employer --text "Acme Corp"
python3 flowcv.py rm work <id>

# header details & links (links are social entries: orcid, googlescholar, github…)
python3 flowcv.py pd jobTitle --text "Security Leader"
python3 flowcv.py link orcid ORCID https://orcid.org/0000-0000-0000-0000
python3 flowcv.py unlink orcid ; python3 flowcv.py links

# avatar
python3 flowcv.py avatar set https://example.com/me.png   # upload from URL or file
python3 flowcv.py avatar on | off | remove

# styling (a delta into resume.customization) and templates
python3 flowcv.py customize font.fontFamily "Source Sans Pro"
python3 flowcv.py customize colors.basic.single '"#0e374e"'
python3 flowcv.py templates                     # lists each as [free] / [PAID] (paid needs a subscription)
python3 flowcv.py apply-template <templateId>   # warns first if the template is paid

# render & share
python3 flowcv.py download -o resume.pdf        # the rendered PDF
python3 flowcv.py download --token <webToken> -o out.pdf   # any PUBLIC resume by its share token (no auth)
python3 flowcv.py share | publish | unpublish

python3 flowcv.py login                          # refresh the cached session
python3 flowcv.py md2html --file role.md         # preview HTML (offline)
```

Any command takes `--resume-id <id>` to target a specific resume.

## Library (for LLM agents / scripts)

```python
from flowcvcli import FlowCV

fc = FlowCV()                                   # or FlowCV(resume_id="...")
fc.set_personal_field("fullName", "Jane Doe")
fc.add_entry("work", sets={"jobTitle": "Engineer", "employer": "Acme",
                           "startDateNew": "01/2022", "endDateNew": "Present"},
             md="- Shipped a thing with **measurable** impact.")
fc.set("font.fontFamily", "Source Sans Pro")    # a customization delta
fc.set_photo("https://example.com/me.png")      # avatar from URL
fc.apply_template("a3fb6c37-...")               # a design from `list_templates()`
fc.save_pdf("resume.pdf")                        # render
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
| `- item` | bullet (consecutive = one list) |
| anything else | justified paragraph |
| `**bold**` inline | `<strong>bold</strong>` |

## Notes

- **Read-modify-write**: edits fetch the resume, change one part, and send it
  back — unrelated fields are never touched.
- New entries append to the bottom of their section (no reorder endpoint).
- After editing, re-export the PDF from the web app too if you want the
  account's stored copy refreshed; `download` already renders the current state.

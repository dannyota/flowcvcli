# flowcv-cli

A small, dependency-free Python CLI to fetch, inspect, and edit a
[FlowCV](https://flowcv.com) resume from the terminal. It uses FlowCV's private
JSON API (the same requests the web editor makes), so it works for **any** FlowCV
resume — you just supply your own resume id and session cookie.

> Unofficial. Uses an undocumented API and your own session — for personal use.
> Standard library only (Python 3.8+); no `pip install` needed.

## Setup

1. Copy the example config and fill it in:

   ```bash
   cp .env.example .env
   ```

   ```dotenv
   FLOWCV_RESUME_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   FLOWCV_COOKIE=flowcvsidapp=s%3A...
   ```

   - **RESUME_ID** — the UUID in your FlowCV editor URL (`app.flowcv.com/resumes/<id>`).
   - **COOKIE** — DevTools → Application → Cookies → `app.flowcv.com` → copy the
     **`flowcvsidapp`** value as `flowcvsidapp=<value>`. That single session cookie
     is the only auth needed (not `i18n`/`loggedin`/`appVersion`). It expires —
     refresh it when `get` returns HTTP 401.

   You can also pass config via the `FLOWCV_RESUME_ID` / `FLOWCV_COOKIE` environment
   variables (they override `.env`). `.env` is gitignored.

## Usage

```bash
python3 flowcv.py get                       # fetch -> resume_raw.json (+ timestamped backup)
python3 flowcv.py show                       # list every section, entry id, label, dates
python3 flowcv.py show work                  # one section
python3 flowcv.py dump work <entryId>        # full entry (readable text + raw fields)
```

Edit an entry's rich-text body from a markdown file:

```bash
python3 flowcv.py desc work <entryId> --file role.md
python3 flowcv.py desc profile <entryId> --field text --file summary.md   # the summary
```

Set a single field (raw value), header details, or links:

```bash
python3 flowcv.py field work <entryId> employer --text "ACME Corp"
python3 flowcv.py pd jobTitle --text "Security Leader — Governance, Operations & Automation"
```

Header links are stored as `social` entries (`linkedIn`, `orcid`, `googlescholar`,
`github`, …), each shown per `detailsOrder`:

```bash
python3 flowcv.py links                                   # list links + display order
python3 flowcv.py link orcid ORCID https://orcid.org/0000-0000-0000-0000
python3 flowcv.py link googlescholar "Google Scholar" "https://scholar.google.com/citations?user=XXXX"
python3 flowcv.py unlink googlescholar                    # remove (delete) a link
python3 flowcv.py linkedin LinkedIn                       # relabel LinkedIn (display only)
```

Add or remove entries:

```bash
python3 flowcv.py add work --file role.md \
  --set title="Software Engineer" --set company="ACME" --set start=01/2020 --set end=12/2021
python3 flowcv.py rm work <entryId>
```

Public web resume (sharing):

```bash
python3 flowcv.py share        # status + public URL (https://flowcv.com/resume/<webToken>)
python3 flowcv.py publish      # enable the public web resume
python3 flowcv.py unpublish    # disable it
```

Preview the HTML a markdown file produces (offline, no network):

```bash
python3 flowcv.py md2html --file role.md
```

## Markdown mini-format

Used by `desc` and `add`:

| You write | You get |
|---|---|
| blank line | block separator |
| `## Heading` or `**Whole line bold**` | bold paragraph (a subheader) |
| `- item` | bullet (consecutive lines = one list) |
| anything else | justified paragraph |
| `**bold**` inline | `<strong>bold</strong>` |

Example `role.md`:

```markdown
Short role intro line.

**Highlights**
- Did a measurable thing with **clear** impact.
- Shipped another thing.
```

## Notes

- **Read-modify-write.** Every edit command GETs the whole resume, changes only
  the target part, and PATCHes it back — unrelated fields are never touched.
  (`personalDetails` is saved as one object, so the tool always sends the full
  object with just your change applied.)
- Every write prints `success=True/False`. `get` saves a timestamped backup so
  changes are reversible.
- After editing, re-export the PDF from the FlowCV web app — the API stores the
  content; the PDF is rendered client-side.
- New entries always **append to the bottom** of their section. There is no
  reorder endpoint; to reorder, reassign content across the existing slots.
```

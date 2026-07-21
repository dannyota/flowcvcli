# Resume as code — `flowcv pull` / `flowcv push`

Materialize a FlowCV resume as an editable, git-diffable tree of Markdown files,
edit it locally, then push only the changes back. Last-writer-wins; there is no
3-way merge — `push --dry-run` is the review tool.

## File layout (`./resume/` by default)

```
resume/
  .flowcv.json                 # manifest: resumeId, pulledAt, {entryId: relpath}
  personal.md                  # personalDetails as frontmatter, NO body
  00-profile/
    _section.md                # frontmatter: displayName, iconKey, sectionType
    00-<id8>.md                # one entry: frontmatter (scalars) + markdown body
  01-work/
    _section.md
    00-<id8>.md
    01-<id8>.md
  …
```

- Section dirs are `NN-<sectionId>`, `NN` = 2-digit index in the resume's
  `content` order (display order). Entry files are `NN-<first 8 of id>.md`,
  `NN` = the entry's index within the section (its order).
- **Filenames are cosmetic** — ordering + a human hint. The authoritative entry
  id is the `id` in each file's frontmatter; the manifest maps every full id to
  its file. `push` addresses entries by that id, never by the filename.

## Frontmatter format (tiny, no PyYAML)

Plain `key: value` lines between `---` fences. A value is written **verbatim**
when it is a string that survives the round-trip; otherwise it is
`json.dumps`-encoded (numbers, bools, null, lists, dicts, and any string that
would otherwise parse as JSON, has leading/trailing space, or contains a
newline). Parsing is the exact inverse: `json.loads` the value; on failure it is
a plain string. So `startDateNew: 01/2022` and `endDateNew: Present` stay plain,
`isHidden: false` is a bool, `endDateNew: "2019"` is forced-quoted to stay a
string, and `date: {"year": "2018", …}` is JSON. `personal.md` puts the whole
`personalDetails` object (scalars, `social`, `detailsOrder`, `photo`, …) into
frontmatter this way.

## Entry body

The body is `html_to_md` of the entry's rich-text field (`text` for profile,
`infoHtml` for skill, else `description`; see `content.rich_field`). All other
fields are frontmatter. On push the body is compared in **markdown** space
(`html_to_md(live)` vs the file), and only re-encoded with `md_to_html` when it
differs — this is what makes the round-trip stable despite `md_to_html` /
`html_to_md` not being byte-inverse on non-canonical server HTML.

## `push` — diff one snapshot, apply only changes

One `get_resume()` under `batch()`; every diff is computed against that snapshot,
then applied with low-level writers (no re-reads):

| Change detected | API call |
|---|---|
| entry frontmatter field and/or body differs | `save_entry` (merged onto the live entry, `updatedAt` bumped) |
| entry file deleted (live id not referenced by any file) | `delete_entry` |
| entry file with **no** `id` in frontmatter | create (two `save_entry` calls); new id written back into the file + manifest |
| section entry order (file `NN` order) differs | `reorder_entries` |
| `_section.md` displayName / iconKey differs | `rename_section` / `set_section_icon` |
| `personal.md` differs | `save_personal` (merged onto live `personalDetails`) |

Semantics: **overlay, never destroy.** Frontmatter/personal keys you delete from
a file are left untouched on the server; `push` never deletes a section or the
resume, and never creates a section (folders whose sectionId isn't live are
skipped). A frontmatter `id` that matches no live entry is skipped with a note.
`--dry-run` computes and prints/`--json`-emits the actions without applying any.

## Round-trip guarantee

`pull` then an immediate `push` yields **zero actions**. `pull` writes every live
field verbatim (frontmatter serialization is an exact inverse) and the body as
`html_to_md(live)`; `push` compares frontmatter parsed-value-equal and the body
in markdown space, so nothing differs. Caveats that keep this true:

- Bodies are diffed as markdown, not re-encoded HTML (so `md_to_html`/`html_to_md`
  non-canonical drift never triggers a write). After a real body edit is pushed,
  the server HTML is canonical and every later round-trip stays stable
  (`md_to_html(html_to_md(md_to_html(x))) == md_to_html(x)`; see `markup.py`).
- `push` overlays onto the live object, so server-only keys absent from a file
  (e.g. a new `personalDetails` field) are preserved, not diffed.
- The manifest `pulledAt` is **informational only** — there is no conflict
  detection. If the server changed since your pull, `push` overwrites with your
  local values (last-writer-wins); run `push --dry-run` first to review.

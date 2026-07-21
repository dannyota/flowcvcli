# PLAN

Convention: this file lists **outstanding work only**. When an item (or phase) is
done, delete it from this file — git history is the record of completed work.
Every item lands with tests (stdlib `unittest`, offline, mocked HTTP — no new
runtime deps; run `python3 -m unittest discover -s tests -t .`).

## Phase 3 — features (by value)

- [ ] *(in progress — background agent)* **`flowcv customize` read path.**
      No args → dump current `customization`
      tree (optionally filtered by path prefix) so users stop guessing dot-paths.
      Plus `flowcv icons` listing valid `iconKey`s (harvest from templates catalog
      or hardcode the known set).
- [ ] *(in progress — background agent)* **`flowcv edit <section> <entry>`.**
      Dump rich text to a temp `.md`, open
      `$EDITOR`, save back via `desc` on close. Reuse `dump`+`set_description`.
      The `markup.html_to_md` reverse converter it needs is DONE (tested,
      round-trip-stable); only the CLI wiring remains.
- [ ] *(in progress — background agent)* **JSON Resume interop — CLI wiring
      only.** The library module is DONE
      (`flowcvcli/jsonresume.py`: `to_jsonresume`/`from_jsonresume`, 35 tests,
      lossiness documented). Remaining: `export --format jsonresume` /
      `import --format jsonresume` in cli.py (goes through `from_jsonresume`
      with the current resume as base → `import_resume`), export `to_jsonresume`/
      `from_jsonresume` (and `html_to_md`) from `__init__`, README note.
- [ ] **Resume-as-code: `flowcv pull` / `flowcv push`.** Export to a directory of
      Markdown files (one per entry, YAML frontmatter for fields, sections as
      folders); `push` diffs local vs remote and applies only changes. Makes the
      resume git-diffable. Design doc first (file layout, id mapping, delete
      semantics).
- [ ] **Cover letters** *(exploratory)*. The login POST already carries
      `letterData`; FlowCV letters likely mirror the resumes API
      (`letters/save_entry`-style). Needs live API discovery in DevTools first —
      capture endpoints into `docs/API.md`, then mirror the resume mixin pattern.
      Blocked on a session with the user available to sanity-check captures.

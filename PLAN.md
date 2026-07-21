# PLAN

Convention: this file lists **outstanding work only**. When an item (or phase) is
done, delete it from this file — git history is the record of completed work.
Every item lands with tests (stdlib `unittest`, offline, mocked HTTP — no new
runtime deps; run `python3 -m unittest discover -s tests -t .`).

## Phase 2 — library & robustness

- [ ] **Batch context.** Each `set_field`/`set_date`/`hide_entry`/`desc` does a
      full `get_resume()` → N edits = 2N requests against a rate-limited API.
      Add `with fc.batch():` (or `fc.cached_resume()`) that fetches once and
      reuses; invalidate on writes that change structure.
- [ ] **429 handling.** Plumb response headers through `_send`; on 429 honor
      `Retry-After` with one polite retry before giving up (cap the wait, e.g. 60s).
- [ ] **`flowcv doctor`.** Check: auth source + validity (cheap `resumes/all`),
      session file age/perms, curl_cffi importable, resume id resolves, appVersion
      fetch. Print pass/fail lines; exit non-zero on failure.

## Phase 3 — features (by value)

- [ ] **`--json` global flag.** Machine-readable output for every command (the
      README targets LLM agents/scripts). Emit the envelope/ids/entries as JSON to
      stdout; human text unchanged by default. Route all prints through a small
      output helper so commands don't branch everywhere.
- [ ] **Auto-snapshot before destructive ops.** Before `rm-section`,
      `delete-resume`, `import`-overwrites: `export_resume()` to
      `~/.local/state/flowcvcli/backups/<resume-id>-<ts>.json` (0600, keep last N).
      `flowcv backups` to list, `flowcv restore <file>` = existing import.
- [ ] **`flowcv customize` read path.** No args → dump current `customization`
      tree (optionally filtered by path prefix) so users stop guessing dot-paths.
      Plus `flowcv icons` listing valid `iconKey`s (harvest from templates catalog
      or hardcode the known set).
- [ ] **`flowcv edit <section> <entry>`.** Dump rich text to a temp `.md`, open
      `$EDITOR`, save back via `desc` on close. Reuse `dump`+`set_description`.
      The `markup.html_to_md` reverse converter it needs is DONE (tested,
      round-trip-stable, exported from `__init__`); only the CLI wiring remains.
- [ ] **JSON Resume interop.** `export --format jsonresume` / `import --format
      jsonresume` mapping FlowCV sections ⇄ jsonresume.org schema (lossy is fine;
      document what maps).
- [ ] **Resume-as-code: `flowcv pull` / `flowcv push`.** Export to a directory of
      Markdown files (one per entry, YAML frontmatter for fields, sections as
      folders); `push` diffs local vs remote and applies only changes. Makes the
      resume git-diffable. Design doc first (file layout, id mapping, delete
      semantics).
- [ ] **Cover letters** *(exploratory)*. The login POST already carries
      `letterData`; FlowCV letters likely mirror the resumes API
      (`letters/save_entry`-style). Needs live API discovery in DevTools first —
      capture endpoints into `docs/API.md`, then mirror the resume mixin pattern.

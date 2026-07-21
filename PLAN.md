# PLAN

Convention: this file lists **outstanding work only**. When an item (or phase) is
done, delete it from this file — git history is the record of completed work.
Every item lands with tests (stdlib `unittest`, offline, mocked HTTP — no new
runtime deps; run `python3 -m unittest discover -s tests -t .`).

## Phase 3 — features (by value)

- [ ] **Cover letters** *(exploratory — BLOCKED on live API discovery)*. The
      login POST already carries `letterData`; FlowCV letters likely mirror the
      resumes API (`letters/save_entry`-style). Needs the letter editor's
      requests captured (user's DevTools, or an approved live probe with the
      user's session) into `docs/API.md`, then mirror the resume mixin pattern.

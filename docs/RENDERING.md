# How FlowCV renders the resume (live preview & save)

Observed directly in the editor (`app.flowcv.com/resume/...`) with the browser's
network + DOM inspected while editing. This explains *what actually draws the
resume*, *when it updates*, and *when it saves* — and what that means for this
tool.

## TL;DR

- The on-screen resume is **plain HTML/DOM rendered by React in the browser** —
  not an image, `<canvas>`, `<iframe>`, `<embed>`, or server-rendered PDF.
  (Verified: 0 canvases, 0 iframes, 0 embeds on the page.)
- Editing updates **React state**, which re-renders the editor *and* the preview
  **instantly, with no network request**. Rendering is purely client-side.
- Saving is **separate from rendering**: after a short debounce (~1 s idle) or on
  blur / route change, **one** PATCH persists the change (`save_entry`,
  `save_personal_details`, or `save_customization`). The visual was already
  updated before this fired.
- The **downloaded PDF is a different, server-side render** (`GET
  /resumes/download`) built from the *same* resume JSON, so it matches the
  on-screen HTML.

## The data flow

```
                     load editor
  GET /api/resumes/{id}  ───────────────►  resume JSON
        (content + personalDetails + customization)
                                              │
                                              ▼
                            React store (single source of truth)
                              │                         │
              ┌───────────────┘                         └───────────────┐
              ▼                                                          ▼
   left panel: edit form                                  right panel: live preview
   (ProseMirror rich-text for                             (HTML "page" element,
    summary/descriptions)                                  styled from customization)
              │                                                          ▲
              │ keystroke → update store ────────────────────────────────┘
              │ (instant, no network)
              ▼
   debounce ~1s / blur / navigate
              │
              ▼
   PATCH save_entry | save_personal_details | save_customization   (persist only)
```

The editor boots by fetching the full resume once (`GET /api/resumes/{id}`).
Everything after that is driven by the in-memory React store. The edit form and
the preview are two views of that **same** store, which is why a keystroke shows
up in both at once.

## Rendering: client-side HTML, not PDF

The preview is a normal DOM subtree (headings, `<p>`, `<ul><li>`, `<strong>`,
`<img>` for icons/photo). Design is applied as CSS derived from the resume's
`customization` object:

- The resume "page" is a **fixed-width HTML element** (~794 px ≈ A4 at 96 dpi)
  **scaled to fit** the viewport via a CSS `transform: matrix(scale)` with
  `transform-origin: top-left` (observed scale ≈ 1.015, width ≈ 806 px).
- **Fonts are web fonts loaded on demand** (e.g. DM Sans, Roboto, Alegreya,
  Inter). `customization.font.fontFamily` / `font.selected` choose them.
- Multi-page (A4/Letter) flow, columns, colors, spacing, headings, icons — all
  pure CSS computed from `customization`. Nothing is rasterized in the browser.

Because the page is real HTML, the accessibility tree contains the full resume
text — that is how this tool and any screen reader can read the rendered output.

## Live editing: instant, zero-network

Typing into a field updates the React store, and **both** the form and the
preview re-render synchronously. We confirmed this by typing a marker into the
summary: it appeared in the DOM **immediately and in two places** (editor +
preview) before any request was sent. There is **no render round-trip** to the
server and no per-keystroke save.

Rich-text fields (summary, entry descriptions) are edited with **ProseMirror**;
its document is serialized to the same HTML the API stores (`<p style="text-align:
justify">…</p>`, `<ul><li><p>…</p></li></ul>`, `<strong>…</strong>`).

## Saving: debounced, coalesced, decoupled

Persistence is independent of the visual update. After a brief idle (~1 s), or
when the field loses focus or you navigate away, the app sends **one** PATCH with
the **whole** changed object:

| You edit | App sends (debounced) |
|---|---|
| an entry (summary, job bullet, skill, …) | `PATCH /api/resumes/save_entry` (full entry) |
| header / contact / links / photo | `PATCH /api/resumes/save_personal_details` (full `personalDetails`) |
| any design control | `PATCH /api/resumes/save_customization` (`customizationUpdates:[{path,value}]` deltas) |

Observed: typing 16 characters produced exactly **one** `save_entry` PATCH, not
16 — edits are coalesced. The server response is just an envelope; the browser
does **not** re-fetch or re-render from it (the store already holds the truth).

## The downloaded PDF is a separate render

The **Download** button hits `GET /api/resumes/download?resumeId&previewPageCount`
and returns a **server-generated PDF** built from the same resume JSON. So there
are two renderers that consume the same data:

- **Browser (HTML/CSS)** — the live, editable preview.
- **Server (PDF)** — the downloadable file (and the public `/api/public/
  download_resume?token=` PDF).

They share the `customization`, so they look the same; the PDF is just the
print-fidelity output.

## What this means for this tool (and any API client)

- **The resume JSON is the single source of truth.** Our PATCH calls
  (`save_entry` / `save_personal_details` / `save_customization`) are *exactly*
  what the web app sends on debounce — we are writing the same data the same way.
- **There is nothing to "re-render" or "refresh" after a write.** Any browser
  that (re)loads the editor does `GET /resumes/{id}` and re-renders from the new
  JSON. The change is live for the next reader the moment the PATCH succeeds.
- **To see the visual result programmatically**, fetch the **PDF** (`download` for
  your own resume, `public/download_resume?token=` for a shared one) — that is the
  server render of the same data. There is no HTML-snapshot endpoint; the HTML
  view only exists inside the React app.
- **Send the full object** on save (the app does). Partial objects replace the
  whole field — see `save_personal_details` and `save_entry` notes in `API.md`.

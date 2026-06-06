# FlowCV private API — reference

Reverse-engineered from the FlowCV web app (`app.flowcv.com`). Unofficial; for
personal use. Base: `https://app.flowcv.com/api`. All app endpoints are
same-origin and authenticated by the **`flowcvsidapp`** session cookie alone
(other cookies — `i18n`, `loggedin`, `appVersion` — are not needed for auth).

Standard JSON envelope: `{ "success": bool, "data": ..., "error": "", "code": int }`.
A missing endpoint returns `code:404`; an existing endpoint with a bad/empty body
returns `code:500` (handler ran, validation failed) — useful for probing.

For **how the editor renders the live preview and when it persists edits**, see
[`RENDERING.md`](RENDERING.md). Short version: the preview is client-side React
HTML (no PDF/canvas), edits update instantly with no network, and saves are
debounced into the `save_entry` / `save_personal_details` / `save_customization`
PATCHes documented below — i.e. exactly what this tool sends.

**Editor boot sequence** (what the SPA fetches on load): `GET /auth/init_user`,
`GET /resumes/all`, `GET /letters/all`, `GET /trackers/all`, `GET /signatures/all`,
`GET /websites/all`, `GET /users/fetch_subscription_infos`,
`GET /users/invoices/pending_review`, then `GET /resumes/{id}` for the open resume.

## Auth

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/auth/init_user` | — | seeds an (anonymous) session cookie. The web app calls it before login, but it is **optional** — login works standalone (the browser request skips it). |
| POST | `/auth/login` | `multipart/form-data`: `email`, `password` (+ empty `resumeData=undefined`, `letterData=undefined`, `resumeImg`, `letterImg`) | sets `flowcvsidapp` cookie on success. **Rate-limited per source IP** (≈100/day) — exhausting it on one machine doesn't affect another. |

Login flow: (optionally GET `init_user` for an anonymous session) → POST `login`
on the same cookie jar → the jar now holds the authenticated `flowcvsidapp`.
`init_user` is best-effort; a failure there must not block the login.

## Resumes (resume-level)

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/resumes/all` | — | `data.resumes[]` (id, title, webToken, webResumeLive, order, …) |
| GET | `/resumes/{resumeId}` | — | `data.resume` (full resume object) |
| POST | `/resumes/create` | `{clientResume: {…full resume object…}}` | create a resume. The body must be a **complete** resume object (every NOT-NULL column), so the reliable way is to **clone a full existing resume** (`GET /resumes/{id}`), reassign `id`+`uuid`, set `title`, empty `content` (or keep it for a duplicate), and **drop** `webToken`/`feedbackToken`/`createdAt`/`updatedAt` (server regenerates). A hand-built partial body fails with Postgres `23502` (not-null). Note: the one-resume free-plan cap is **not** enforced on this endpoint. |
| POST | `/resumes/duplicate` | `{resumeId}` | native duplicate — but returned a generic error in testing; duplicating via `create` (clone, keep `content`) is what this tool does instead. |
| PATCH | `/resumes/rename_resume` | `{resumeId, resumeTitle}` | rename a resume |
| DELETE | `/resumes/delete_resume?resumeId={id}` | — | **permanently delete** a resume (irreversible) |
| PATCH | `/resumes/apply_template` | `{resumeId, templateId, customization: {…template's full customization…}, personalDetails: {…current…}}` | applies a design. `templateId` + `customization` come from the template list (below). |
| PATCH | `/resumes/publish_web_resume` | `{publish: bool, resumeId}` | toggle the public web resume |
| GET | `/resumes/download?resumeId={id}&previewPageCount={n}` | — | **PDF bytes** (`application/pdf`). `previewPageCount` does not truncate; any value returns the full doc. |
| GET | `/api/public/download_resume?token={webToken}` | — | **public** PDF of any *shared* resume by its web token — no auth/ownership needed. (Only when the resume's download is enabled; otherwise 400.) |
| DELETE | `/resumes/delete_entry?resumeId&sectionId&entryId` | — | delete a content entry (see below) |

The full-resume GET also exposes `webToken` (public URL
`https://flowcv.com/resume/{webToken}`), `webResumeLive`, `feedbackToken`. Top-level
resume keys (for the `create` clone): `id, userId, mongoId, title, order,
feedbackToken, webToken, uuid, feedbackEnabled, webResumeLive,
webResumeDownloadBtn, webResumeSearchIndex, webResumeCached, personalDetails,
content, customization, feedback, businessDetails, downloads,
usingBusinessTemplateId, schemaVersion, lastChangeAt, createdAt, updatedAt, lng,
tags`.

## Content (sections & entries)

`data.resume.content` is a map of `sectionId → { entries[], iconKey, displayName,
sectionType }`. Known sections: `profile` (Summary), `work` (Experience),
`education`, `skill`, `publication`, `organisation`, `custom1` (sectionType
`custom`), plus language/certificate/interest/project/course/award/reference/
declaration.

| Method | Path | Body | Notes |
|---|---|---|---|
| PATCH | `/resumes/save_entry` | `{resumeId, sectionId, entry}` | **update** an existing entry (send the whole entry object). |
| PATCH | `/resumes/save_entry` | `{resumeId, sectionId, entry:{id, isHidden:false}, sectionType, sectionDisplayName, sectionIconKey}` | **create** an entry — required extra section-meta fields. If the section doesn't exist yet, this also **creates the section**. New entries append to the bottom. Populate fields with a follow-up update call. |
| DELETE | `/resumes/delete_entry?resumeId&sectionId&entryId` | — | delete an entry |
| PATCH | `/resumes/save_entries_order` | `{resumeId, sectionId, newEntriesIdsOrder:[id,…], disableAutoSort:true}` | **reorder entries** within a section (the array order). `disableAutoSort` keeps the manual order (else FlowCV auto-sorts by date). |
| PATCH | `/resumes/save_section_name` | `{resumeId, sectionId, displayName}` | **rename** a section heading |
| PATCH | `/resumes/save_section_icon` | `{resumeId, sectionId, iconKey}` | change a section's icon |
| DELETE | `/resumes/delete_section?resumeId&sectionId` | — | **delete a whole section** and all its entries |

To **hide/show** a single entry, `save_entry` it with `entry.isHidden = true|false`
(it stays in the resume but is omitted from output). **Reorder sections** by
writing `customization.sectionOrder.<layout>.sectionsSorted` (a list of section
ids) via `save_customization` — section order lives in `customization`, keyed per
column layout (`one`, `two`, `mix`), not in `content`. (`save_section` exists too
but 500s on every body shape tried; the granular `save_section_*` endpoints above
are what the app actually uses. `reorder_entries`/`reorder_sections`/`rename_section`
are all 404 — the real names are `save_entries_order`/`save_section_name`.)

Section meta (`sectionType`, `displayName`, `iconKey`) for creating sections:
`profile`→(profile, Summary, address-card), `work`→(work, Professional
Experience, briefcase), `education`→(education, Education, graduation-cap),
`skill`→(skill, Skills, head-side-brain), `publication`→(publication,
Publications, newspaper), `organisation`→(organisation, Organisations,
house-user), `custom1`→(custom, Custom, star).

Rich-text fields are HTML: `<p style="text-align: justify">…</p>` for paragraphs,
`<p…><strong>…</strong></p>` for bold subheaders, `<ul><li…><p…>…</p></li></ul>`
for bullets. `profile` entries use a `text` field; `skill` entries use `skill`
(title) + `infoHtml`; most others use `description`.

No reorder endpoint (`reorder_entries` 404s). To reorder, reassign entry content
across the existing array slots.

## Personal details & header links

| Method | Path | Body |
|---|---|---|
| PATCH | `/resumes/save_personal_details` | `{resumeId, personalDetails: {…full object…}}` |

Always send the **full** `personalDetails` object with only the target field
changed (it replaces the whole object). Header links live in
`personalDetails.social` as `{platform: {display, link}}` (e.g. `linkedIn`,
`orcid`, `googlescholar`) and are shown per `personalDetails.detailsOrder`
(e.g. `["displayEmail","phone","address","linkedIn","orcid","googlescholar"]`).
The legacy single link is `personalDetails.website` + `websiteLink`.

## Photo / avatar

| Method | Path | Body |
|---|---|---|
| POST | `/resumes/upload_profile_pic` | `multipart/form-data`: `resumeId` + `file` (image bytes) → `{data:{imageId:"avatar/….png"}}` |

Then save the id into `personalDetails.photo` (via `save_personal_details`):
`{imageId, shape:"round", xPct, yPct, widthPct, heightPct, originalWidth, originalHeight}`
(use a whole-image crop: xPct≈yPct≈0.0005, widthPct≈heightPct≈0.999). Toggle
display with the customization delta `header.photo.show` = `true|false`.

## Customization (styling)

| Method | Path | Body |
|---|---|---|
| PATCH | `/resumes/save_customization` | `{resumeId, customizationUpdates: [{path, value}, …]}` |

**Delta API**: each update is a dot-`path` into `resume.customization` and a new
`value`. Examples:
- Columns: `layout.colsFromDetails.top|left|right` = `"one"|"two"`
- Font: `font.fontFamily` = `"Source Sans Pro"`, `font.selected` = `"serif"|"sans"`
- Colors: `colors.basic.single` = `"#0e374e"`, `colors.mode` = `"basic"|"advanced"`
- Spacing: `spacing.fontSize`, `spacing.lineHeight`, `spacing.marginHorizontal`
- Headings: `heading.style` = `"line"|"box"`, `heading.capitalization`
- Page: `pageFormat` = `"A4"|"Letter"`

The full `customization` schema is visible in `GET /resumes/{id}` (under
`data.resume.customization`) and in the `create` default.

The **Customize** panel groups (each = one or more delta paths under
`customization`) are: **Document** (page format, date format), **Templates**
(browse/apply, below), **Layout** (`layout.colsFromDetails…` columns one/two/mix,
per-section placement), **Font Size**, **Spacing** (`spacing.*`), **Entry Layout**,
**Section Headings** (`heading.style`, `heading.capitalization`, heading icons),
**Font** — separate **body font** and **name font** — **Colors**
(`colors.mode`/`colors.basic.single`, accent, and *Color Area*: full / page /
header / border), **Header** (text alignment, details arrangement, icon style),
**Photo** (`header.photo.show`), **Link Styling**, **Footer** (toggle page
numbers / email / name), and per-**Section** customizations. "Create template"
publishes the current design as a shareable template. The panel also has
**undo/redo**. All of these are just `save_customization` deltas — discover exact
paths by diffing `data.resume.customization` before/after a change in the UI.

## Templates

| Method | Path | Returns |
|---|---|---|
| GET | `/pubcache/published-resume-templates` | the full template catalog (id, title, customization, `isPremium`, …) |
| GET | `/api/resume-templates/get_shared_template?resumeId={id}` | the template shared/applied to a resume |

Each catalog entry has **`isPremium`** (bool): `false` = free, `true` = needs a
FlowCV subscription to apply. Show this to users before they apply one.

To apply a template: pick its `templateId` + `customization` from the catalog and
PATCH `apply_template` (above).

## Download & share menu (resume editor)

The editor's top-right controls map to these endpoints:

| UI control | Endpoint / effect |
|---|---|
| **Download** button | `GET /resumes/download` → PDF (server render). Shows a "✅ downloaded" modal after. |
| ⋯ → **Download via email** | emails the PDF to the account (send-email endpoint; body not captured). |
| ⋯ → **Get shareable link** | the **web resume**: *Enable sharing* = `publish_web_resume {publish}`; link is `https://flowcv.com/resume/{webToken}`; *Display download button* gates the public `public/download_resume?token=` PDF (off → 400). |

## AI Tools (per resume, Pro plan) — `/resume/ai-tools`

Gated behind the **Pro** subscription ("AI features are available on our Pro
plan"). Two tools observed (both Beta): **Translate resume** (create a translated
copy in another language, layout intact) and **Check spelling & grammar** (scan +
fix suggestions). Endpoints not captured (Pro-gated on the test account).

## Other FlowCV products (same account & session, separate APIs)

FlowCV is more than resumes. The same `flowcvsidapp` session authenticates these
sibling products — each with its own `…/all` list endpoint, all fetched on editor
load. This tool currently covers **resumes only**; these are documented for
discovery, not yet implemented:

| Product | List endpoint | UI |
|---|---|---|
| **Cover Letters** | `GET /api/letters/all` | `/cover-letters` |
| **Job Tracker** | `GET /api/trackers/all` | `/job-tracker` |
| **Email Signatures** | `GET /api/signatures/all` | email-signature generator |
| **Personal Websites** | `GET /api/websites/all` | personal-site builder |

Account/billing: `GET /api/users/fetch_subscription_infos` (plan + entitlements;
free accounts get one resume, premium templates and AI gated),
`GET /api/users/invoices/pending_review`. The user object from `auth/login` also
carries `paid`, `activePlans`, AB-test flags, and `numberOfLogins`.

> Free vs paid recap: first resume is free forever; additional resumes, premium
> templates (`isPremium`), AI Tools, and likely the public-download button are
> Pro features. Show users the free/paid split before they hit a 400 or upsell.

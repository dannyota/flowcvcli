# FlowCV private API — reference

Reverse-engineered from the FlowCV web app (`app.flowcv.com`). Unofficial; for
personal use. Base: `https://app.flowcv.com/api`. All app endpoints are
same-origin and authenticated by the **`flowcvsidapp`** session cookie alone
(other cookies — `i18n`, `loggedin`, `appVersion` — are not needed for auth).

Standard JSON envelope: `{ "success": bool, "data": ..., "error": "", "code": int }`.
A missing endpoint returns `code:404`; an existing endpoint with a bad/empty body
returns `code:500` (handler ran, validation failed) — useful for probing.

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
| POST | `/resumes/create` | `{clientResume: {…full default resume…}}` | creates a blank resume; server assigns real id. The default object has `title`, empty `personalDetails`/`content`, and a full default `customization`. |
| PATCH | `/resumes/apply_template` | `{resumeId, templateId, customization: {…template's full customization…}, personalDetails: {…current…}}` | applies a design. `templateId` + `customization` come from the template list (below). |
| PATCH | `/resumes/rename_resume` | `{resumeId, …}` exists (body shape TODO — not `{title}`) | rename |
| PATCH | `/resumes/publish_web_resume` | `{publish: bool, resumeId}` | toggle the public web resume |
| GET | `/resumes/download?resumeId={id}&previewPageCount={n}` | — | **PDF bytes** (`application/pdf`). `previewPageCount` does not truncate; any value returns the full doc. |
| GET | `/api/public/download_resume?token={webToken}` | — | **public** PDF of any *shared* resume by its web token — no auth/ownership needed. (Only when the resume's download is enabled; otherwise 400.) |
| DELETE | `/resumes/delete_entry?resumeId&sectionId&entryId` | — | delete a content entry (see below) |

The full-resume GET also exposes `webToken` (public URL
`https://flowcv.com/resume/{webToken}`), `webResumeLive`, `feedbackToken`.

> Not yet captured: delete-**resume** endpoint (the card "⋯ → Delete" — not
> `delete_resume`/`remove_resume`/`DELETE /resumes/{id}`, all 404), `save_section`
> body (endpoint exists), `rename_resume` body.

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

## Templates

| Method | Path | Returns |
|---|---|---|
| GET | `/pubcache/published-resume-templates` | the full template catalog (id, title, customization, `isPremium`, …) |
| GET | `/api/resume-templates/get_shared_template?resumeId={id}` | the template shared/applied to a resume |

Each catalog entry has **`isPremium`** (bool): `false` = free, `true` = needs a
FlowCV subscription to apply. Show this to users before they apply one.

To apply a template: pick its `templateId` + `customization` from the catalog and
PATCH `apply_template` (above).

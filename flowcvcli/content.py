"""Content sections & entries: create / update / delete resume entries.

A resume's `content` is a map of `sectionId -> {entries[], sectionType,
displayName, iconKey}`. Entries are addressed by their `id`. Writes are
read-modify-write where the API replaces the whole entry; create uses
`save_entry` with extra section-meta so a missing section is created too.

Mixes into Client; uses self.get_resume / self.request / self.resume_id.
"""
import uuid

from .markup import md_to_html

# sectionId -> (sectionType, displayName, iconKey) for creating sections.
SECTION_META = {
    "profile": ("profile", "Summary", "address-card"),
    "work": ("work", "Professional Experience", "briefcase"),
    "education": ("education", "Education", "graduation-cap"),
    "skill": ("skill", "Skills", "head-side-brain"),
    "publication": ("publication", "Publications", "newspaper"),
    "organisation": ("organisation", "Organisations", "house-user"),
    "custom1": ("custom", "Custom", "star"),
}


def label_of(entry):
    """Best human label for an entry across section shapes."""
    for k in ("jobTitle", "employer", "title", "degree", "skill",
              "position", "publicationTitle", "organisationName"):
        v = entry.get(k)
        if v:
            return v
    return "(empty)"


class ContentMixin:
    # ---- lookups ----------------------------------------------------------
    def find_section(self, resume, section):
        """Return the section object from resume.content (or exit)."""
        sec = (resume.get("content") or {}).get(section)
        if sec is None:
            raise SystemExit(f"section not found: {section}")
        return sec

    def find_entry(self, resume, section, entry_id):
        """Return the entry dict with id == entry_id in section (or exit)."""
        sec = self.find_section(resume, section)
        for entry in sec.get("entries") or []:
            if entry.get("id") == entry_id:
                return entry
        raise SystemExit(f"entry not found: {section}/{entry_id}")

    # ---- low-level writes -------------------------------------------------
    def save_entry(self, section, entry, extra=None):
        """PATCH save_entry; updates the entry (or creates it with `extra`)."""
        body = {"resumeId": self.resume_id, "sectionId": section, "entry": entry}
        if extra:
            body.update(extra)
        return self.request("resumes/save_entry", method="PATCH", body=body)

    def delete_entry(self, section, entry_id):
        """DELETE delete_entry by (resumeId, sectionId, entryId)."""
        query = {"resumeId": self.resume_id, "sectionId": section,
                 "entryId": entry_id}
        return self.request("resumes/delete_entry", method="DELETE", query=query)

    # ---- high-level helpers ----------------------------------------------
    def add_entry(self, section, sets=None, md=None):
        """Create an entry (and the section if needed); return the new id.

        `sets` are entry fields to populate; `md` becomes a `description`
        HTML field. Creates the entry first (so a missing section is made),
        then fills it with a follow-up update.
        """
        resume = self.get_resume()
        existing = (resume.get("content") or {}).get(section)
        if existing:
            section_type = existing.get("sectionType")
            display_name = existing.get("displayName")
            icon_key = existing.get("iconKey")
        elif section in SECTION_META:
            section_type, display_name, icon_key = SECTION_META[section]
        else:
            raise SystemExit(f"unknown section (no meta): {section}")

        new_id = str(uuid.uuid4())
        # Create: minimal entry + section meta (also creates the section).
        self.save_entry(section, {"id": new_id, "isHidden": False}, extra={
            "sectionType": section_type,
            "sectionDisplayName": display_name,
            "sectionIconKey": icon_key,
        })

        now = self.now_iso()
        entry = {"id": new_id, "isHidden": False, "showPlaceholder": False,
                 "createdAt": now, "updatedAt": now}
        entry.update(sets or {})
        if md:
            # rich text lives in a section-specific field (profile->text, skill->infoHtml)
            field = {"profile": "text", "skill": "infoHtml"}.get(section, "description")
            entry[field] = md_to_html(md)
        self.save_entry(section, entry)
        return new_id

    def set_field(self, section, entry_id, field, value):
        """Read-modify-write a single entry field; bump updatedAt if present."""
        resume = self.get_resume()
        entry = dict(self.find_entry(resume, section, entry_id))
        entry[field] = value
        if "updatedAt" in entry:
            entry["updatedAt"] = self.now_iso()
        return self.save_entry(section, entry)

    def set_description(self, section, entry_id, md, field="description"):
        """Set a rich-text field to md_to_html(md) on an entry."""
        return self.set_field(section, entry_id, field, md_to_html(md))

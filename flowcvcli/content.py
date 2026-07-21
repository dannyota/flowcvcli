"""Content sections & entries: create / update / delete resume entries.

A resume's `content` is a map of `sectionId -> {entries[], sectionType,
displayName, iconKey}`. Entries are addressed by their `id`. Writes are
read-modify-write where the API replaces the whole entry; create uses
`save_entry` with extra section-meta so a missing section is created too.

Mixes into Client; uses self.get_resume / self.request / self.resume_id.
"""
import re
import uuid

from .errors import ApiError, NotFoundError
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

# Per-section rich-text field: most sections store rich text in `description`,
# but the summary uses `text` and skills use `infoHtml`.
RICH_TEXT_FIELD = {"profile": "text", "skill": "infoHtml"}


def rich_field(section):
    """The entry field that holds rich text for `section` (default 'description')."""
    return RICH_TEXT_FIELD.get(section, "description")


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
            raise NotFoundError(f"section not found: {section}")
        return sec

    def find_entry(self, resume, section, entry_id):
        """Return the entry dict with id == entry_id in section (or exit)."""
        sec = self.find_section(resume, section)
        for entry in sec.get("entries") or []:
            if entry.get("id") == entry_id:
                return entry
        raise NotFoundError(f"entry not found: {section}/{entry_id}")

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
    def add_entry(self, section, sets=None, md=None, section_name=None, section_icon=None):
        """Create an entry (and the section if needed); return the new id.

        `sets` are entry fields to populate; `md` becomes the section's rich-text
        field. Creates the entry first (so a missing section is made), then fills
        it with a follow-up update. When the section is created, `section_name`
        and `section_icon` override its default heading/icon (no follow-up
        rename-section / section-icon needed).
        """
        resume = self.get_resume()
        existing = (resume.get("content") or {}).get(section)
        if existing:
            section_type = existing.get("sectionType")
            display_name = existing.get("displayName")
            icon_key = existing.get("iconKey")
        elif section in SECTION_META:
            section_type, display_name, icon_key = SECTION_META[section]
        elif re.fullmatch(r"custom\d+", section):
            # FlowCV supports multiple custom sections (custom1, custom2, …);
            # only custom1 is pre-declared in SECTION_META. Create any other
            # customN as a generic custom section.
            section_type, display_name, icon_key = "custom", "Custom", "star"
        else:
            raise ApiError(f"unknown section (no meta): {section}")
        if section_name is not None:
            display_name = section_name
        if section_icon is not None:
            icon_key = section_icon

        new_id = str(uuid.uuid4())
        # Create: minimal entry + section meta (also creates the section).
        env = self.save_entry(section, {"id": new_id, "isHidden": False}, extra={
            "sectionType": section_type,
            "sectionDisplayName": display_name,
            "sectionIconKey": icon_key,
        })
        if not env.get("success"):
            raise ApiError(f"could not create {section} entry: {env}")

        now = self.now_iso()
        entry = {"id": new_id, "isHidden": False, "showPlaceholder": False,
                 "createdAt": now, "updatedAt": now}
        entry.update(sets or {})
        if md:
            entry[rich_field(section)] = md_to_html(md)
        env = self.save_entry(section, entry)
        if not env.get("success"):
            raise ApiError(f"created {section} entry {new_id} but failed to populate it: {env}")
        return new_id

    def set_field(self, section, entry_id, field, value):
        """Read-modify-write a single entry field; bump updatedAt if present."""
        resume = self.get_resume()
        entry = dict(self.find_entry(resume, section, entry_id))
        entry[field] = value
        if "updatedAt" in entry:
            entry["updatedAt"] = self.now_iso()
        return self.save_entry(section, entry)

    def set_description(self, section, entry_id, md, field=None):
        """Set a rich-text field to md_to_html(md) on an entry. When `field` is
        omitted, it defaults to the section's rich-text field (profile->text,
        skill->infoHtml, else description)."""
        return self.set_field(section, entry_id, field or rich_field(section), md_to_html(md))

    def set_date(self, section, entry_id, year=None, month=None, day=None, clear=False):
        """Merge into an entry's structured `date` object (publications, etc.).

        Only the parts passed change: a given month/day is also unhidden; parts
        never set stay hidden, so `set_date(..., year=2018)` on a fresh entry
        renders year-only. `clear=True` resets the whole date first.
        """
        resume = self.get_resume()
        entry = dict(self.find_entry(resume, section, entry_id))
        date = {} if clear else dict(entry.get("date") or {})
        date.setdefault("year", "")
        date.setdefault("month", "")
        date.setdefault("day", "")
        date.setdefault("hideMonth", True)
        date.setdefault("hideDay", True)
        if year is not None:
            date["year"] = str(year)
        if month is not None:
            date["month"] = str(month)
            date["hideMonth"] = False
        if day is not None:
            date["day"] = str(day)
            date["hideDay"] = False
        entry["date"] = date
        if "updatedAt" in entry:
            entry["updatedAt"] = self.now_iso()
        return self.save_entry(section, entry)

    def hide_entry(self, section, entry_id, hidden=True):
        """Show/hide an entry (sets its `isHidden`). Hidden entries stay in the
        resume but are omitted from the rendered output."""
        return self.set_field(section, entry_id, "isHidden", bool(hidden))

    # ---- section-level ops ------------------------------------------------
    def reorder_entries(self, section, order):
        """Set the order of entries in a section. `order` is the list of entry
        ids in the desired order (must be a permutation of the section's ids).

        PATCH save_entries_order with `disableAutoSort` so the manual order sticks
        (FlowCV otherwise auto-sorts by date)."""
        resume = self.get_resume()
        have = [e.get("id") for e in self.find_section(resume, section).get("entries") or []]
        order = list(order)
        if set(order) != set(have):
            raise ApiError(f"reorder ids must be exactly the section's entries.\n"
                           f"  given:   {order}\n  section: {have}")
        return self.request("resumes/save_entries_order", method="PATCH",
                            body={"resumeId": self.resume_id, "sectionId": section,
                                  "newEntriesIdsOrder": order, "disableAutoSort": True})

    def rename_section(self, section, display_name):
        """PATCH save_section_name — change a section's heading text."""
        return self.request("resumes/save_section_name", method="PATCH",
                            body={"resumeId": self.resume_id, "sectionId": section,
                                  "displayName": display_name})

    def set_section_icon(self, section, icon_key):
        """PATCH save_section_icon — change a section's icon (e.g. 'briefcase')."""
        return self.request("resumes/save_section_icon", method="PATCH",
                            body={"resumeId": self.resume_id, "sectionId": section,
                                  "iconKey": icon_key})

    def delete_section(self, section):
        """DELETE delete_section — remove a whole section and all its entries."""
        return self.request("resumes/delete_section", method="DELETE",
                            query={"resumeId": self.resume_id, "sectionId": section})

    def reorder_sections(self, section_ids, layout="one", side=None):
        """Set the section order for a column layout. Single-column layouts store
        one list (`sectionOrder.<layout>.sectionsSorted`); the 'two' layout stores
        each column separately (`leftSectionsSorted`/`rightSectionsSorted`), so it
        needs `side` ('left' or 'right') and orders just that column.

        Sections are ordered in `resume.customization.sectionOrder`, not in
        `content`, so this is a `save_customization` delta."""
        if layout == "two":
            if side not in ("left", "right"):
                raise ApiError("the two-column layout stores each column separately — "
                               "pass side='left' or side='right' (CLI: --side).")
            return self.set(f"sectionOrder.two.{side}SectionsSorted", list(section_ids))
        if side:
            raise ApiError(f"side= only applies to the 'two' layout, not {layout!r}.")
        return self.set(f"sectionOrder.{layout}.sectionsSorted", list(section_ids))

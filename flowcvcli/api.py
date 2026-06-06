"""FlowCV — the high-level client, composed from the Client core + feature mixins.

LLM / library use:
    from flowcvcli import FlowCV
    fc = FlowCV()                      # auth + resume id from .env / env vars
    fc = FlowCV(resume_id="...")       # target a specific resume
    fc.add_entry("work", sets={"jobTitle": "Engineer", "employer": "Acme",
                               "startDateNew": "01/2022", "endDateNew": "Present"},
                 md="- Did a measurable thing.")
    fc.set_personal_field("fullName", "Jane Doe")
    fc.set_link("orcid", "ORCID", "https://orcid.org/0000-0000-0000-0000")
    fc.set("font.fontFamily", "Source Sans Pro")     # a customization delta
    fc.save_pdf("resume.pdf")                          # render + view
"""
from .client import Client
from .content import ContentMixin
from .customization import CustomizationMixin
from .personal import PersonalMixin
from .photo import PhotoMixin
from .resume import ResumeMixin


class FlowCV(Client, ResumeMixin, ContentMixin, PersonalMixin,
             CustomizationMixin, PhotoMixin):
    """One object that controls a FlowCV resume end to end."""

    # convenience: toggle the header photo/avatar on or off (a customization delta)
    def set_avatar_visible(self, visible):
        return self.set("header.photo.show", bool(visible))

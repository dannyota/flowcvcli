"""Header personal details & links.

`personalDetails` is a single object saved whole via PATCH
`resumes/save_personal_details`. The API replaces the object wholesale, so every
write follows the read-modify-write pattern: fetch the full object, change the
target field, send it all back.

Header links live in `personalDetails.social` as `{key: {display, link}}` and are
shown in the order given by `personalDetails.detailsOrder`.
"""
import copy

from .errors import NotFoundError


class PersonalMixin:
    # ---- core read/write --------------------------------------------------
    def _pd(self):
        """Return a deepcopy of the resume's personalDetails object."""
        return copy.deepcopy(self.get_resume()["personalDetails"])

    def save_personal(self, pd):
        """PATCH the full personalDetails object back. Return the envelope."""
        return self.request("resumes/save_personal_details", method="PATCH",
                            body={"resumeId": self.resume_id, "personalDetails": pd})

    # ---- scalar fields ----------------------------------------------------
    def set_personal_field(self, field, value):
        """Set one scalar field on the full pd and save. Return the envelope."""
        pd = self._pd()
        pd[field] = value
        return self.save_personal(pd)

    # ---- header links -----------------------------------------------------
    def set_link(self, key, display, url):
        """Add/update a header link (pd.social[key]={display,link}).

        Ensures `key` is present in pd.detailsOrder (appended if absent). Saves
        and returns the envelope.
        """
        pd = self._pd()
        social = copy.deepcopy(pd.get("social") or {})
        social[key] = {"display": display, "link": url}
        pd["social"] = social
        order = pd.get("detailsOrder") or []
        if key not in order:
            order = order + [key]
        pd["detailsOrder"] = order
        return self.save_personal(pd)

    def remove_link(self, key):
        """Delete a header link and drop it from detailsOrder. NotFoundError if absent."""
        pd = self._pd()
        social = pd.get("social") or {}
        if key not in social:
            raise NotFoundError(f"No header link {key!r}.")
        del social[key]
        pd["social"] = social
        pd["detailsOrder"] = [k for k in (pd.get("detailsOrder") or []) if k != key]
        return self.save_personal(pd)

    def list_links(self):
        """Return [(key, display, link, shown_bool)] from pd.social/detailsOrder."""
        pd = self.get_resume()["personalDetails"]
        social = pd.get("social") or {}
        order = pd.get("detailsOrder") or []
        return [(k, v.get("display", ""), v.get("link", ""), k in order)
                for k, v in social.items()]

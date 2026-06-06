"""Customization: styling deltas & template application.

FlowCV stores all design in `resume.customization` (font, colors, layout,
spacing, headings, page format, …). Updates go through a **delta API**: each
change is a dot-`path` into that object plus a new `value`, sent to
`save_customization`. Templates are full customization presets pulled from a
public catalog and applied via `apply_template`.
"""

TEMPLATE_CATALOG = "https://app.flowcv.com/pubcache/published-resume-templates"


class CustomizationMixin:
    """Styling & template operations (mixed into Client)."""

    def customize(self, updates):
        """Apply a batch of customization deltas. Return the envelope dict.

        `updates` is a list of (path, value) tuples or {"path", "value"} dicts;
        `path` is a dot-path into `resume.customization`
        (e.g. "font.fontFamily", "colors.basic.single").
        """
        deltas = []
        for u in updates:
            if isinstance(u, dict):
                deltas.append({"path": u["path"], "value": u["value"]})
            else:
                path, value = u
                deltas.append({"path": path, "value": value})
        body = {"resumeId": self.resume_id, "customizationUpdates": deltas}
        return self.request("resumes/save_customization", method="PATCH", body=body)

    def set(self, path, value):
        """Apply a single customization delta. Return the envelope dict."""
        return self.customize([(path, value)])

    def get_customization(self):
        """Return the current `resume.customization` object."""
        return self.get_resume()["customization"]

    def list_templates(self):
        """Return the published template catalog as a list of template dicts.

        Each template has at least an id/name and a `customization`. Defensive
        about the response shape: the catalog may come back as a bare JSON list
        or wrapped in a standard `{success, data}` envelope.
        """
        resp = self.request(TEMPLATE_CATALOG)
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict):
            data = resp.get("data", resp)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("templates", "items", "results"):
                    if isinstance(data.get(key), list):
                        return data[key]
        return []

    def apply_template(self, template_id):
        """Apply a published template by id. Return the envelope dict.

        Looks the template up in the catalog, then PATCHes `apply_template` with
        its full `customization` and the resume's current `personalDetails`.
        Raises SystemExit if no template matches `template_id`.
        """
        tpl = next((t for t in self.list_templates() if t.get("id") == template_id), None)
        if tpl is None:
            raise SystemExit(f"template not found: {template_id!r}")
        body = {
            "resumeId": self.resume_id,
            "templateId": template_id,
            "customization": tpl.get("customization"),
            "personalDetails": self.get_resume()["personalDetails"],
        }
        return self.request("resumes/apply_template", method="PATCH", body=body)

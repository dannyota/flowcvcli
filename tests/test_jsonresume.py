"""JSON Resume (jsonresume.org v1.0.0) <-> FlowCV resume-object interop.

Offline, stdlib-only. Fixtures are representative dict fragments: a realistic
FlowCV resume object and a realistic JSON Resume document. Rich text is built
with the real markup converters so round-trip assertions use true HTML.
"""
import copy
import unittest

from flowcvcli.jsonresume import to_jsonresume, from_jsonresume
from flowcvcli.markup import md_to_html, html_to_md

SCHEMA = "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json"


def flowcv_resume():
    """A realistic FlowCV resume object fragment covering every mapped section
    plus a hidden entry, an all-hidden (empty-after-filter) section, and an
    unmapped section (language)."""
    return {
        "id": "R1",
        "title": "My CV",
        "personalDetails": {
            "fullName": "Jane Doe",
            "jobTitle": "Staff Engineer",
            "email": "jane@example.com",
            "phone": "+1 555 0100",
            "address": "1 Main St",
            "city": "Boston",
            "country": "USA",
            "photo": {"imageId": "avatar/x.png"},
            "social": {"linkedIn": {"display": "LinkedIn",
                                    "link": "https://linkedin.com/in/jane"}},
            "detailsOrder": ["displayEmail", "phone", "address", "linkedIn"],
        },
        "content": {
            "profile": {"sectionType": "profile", "displayName": "Summary",
                        "iconKey": "address-card", "entries": [
                {"id": "P1", "isHidden": False,
                 "text": md_to_html("Experienced **engineer** who ships.")}]},
            "work": {"sectionType": "work", "displayName": "Experience",
                     "iconKey": "briefcase", "entries": [
                {"id": "W1", "isHidden": False, "employer": "Acme",
                 "jobTitle": "Engineer", "employerLink": "https://acme.example",
                 "startDateNew": "01/2020", "endDateNew": "Present",
                 "description": md_to_html("- Built things\n- Shipped more")},
                {"id": "W2", "isHidden": True, "employer": "Hidden Co",
                 "jobTitle": "Intern", "startDateNew": "01/2018",
                 "endDateNew": "12/2018"}]},
            "education": {"sectionType": "education", "displayName": "Education",
                          "iconKey": "graduation-cap", "entries": [
                {"id": "E1", "isHidden": False, "school": "MIT",
                 "schoolLink": "https://mit.edu", "degree": "BSc CS",
                 "startDateNew": "09/2014", "endDateNew": "06/2018"}]},
            "skill": {"sectionType": "skill", "displayName": "Skills",
                      "iconKey": "head-side-brain", "entries": [
                {"id": "S1", "isHidden": False, "skill": "Python",
                 "skillLevel": "Expert", "infoHtml": ""},
                {"id": "S2", "isHidden": False, "skill": "Go", "infoHtml": ""}]},
            "publication": {"sectionType": "publication",
                            "displayName": "Publications", "iconKey": "newspaper",
                            "entries": [
                {"id": "PUB1", "isHidden": False, "title": "My Paper",
                 "publisher": "IEEE", "titleLink": "https://doi.example",
                 "date": {"year": "2021", "month": "3", "day": "",
                          "hideMonth": False, "hideDay": True},
                 "description": md_to_html("A short abstract.")}]},
            "organisation": {"sectionType": "organisation",
                             "displayName": "Organisations", "iconKey": "house-user",
                             "entries": [
                {"id": "O1", "isHidden": False, "organisationName": "Red Cross",
                 "position": "Volunteer", "organisationLink": "https://redcross.example",
                 "startDateNew": "01/2019", "endDateNew": "01/2020",
                 "description": md_to_html("Helped out.")}]},
            "custom1": {"sectionType": "custom", "displayName": "Projects",
                        "iconKey": "star", "entries": [
                {"id": "C1", "isHidden": False, "title": "CoolApp",
                 "titleLink": "https://cool.example",
                 "description": md_to_html("A cool app.")}]},
            "certificate": {"sectionType": "certificate", "displayName": "Certs",
                            "iconKey": "certificate", "entries": [
                {"id": "X1", "isHidden": True, "title": "AWS"}]},
            "language": {"sectionType": "language", "displayName": "Languages",
                         "iconKey": "language", "entries": [
                {"id": "L1", "isHidden": False, "language": "English"}]},
        },
    }


def jsonresume_doc():
    """A realistic JSON Resume document."""
    return {
        "$schema": SCHEMA,
        "basics": {
            "name": "John Smith",
            "label": "Data Scientist",
            "email": "john@example.com",
            "phone": "+44 20 0000",
            "summary": "A **data** person.",
            "location": {"address": "5 High St", "city": "London",
                         "countryCode": "UK"},
            "profiles": [{"network": "GitHub", "url": "https://github.com/js",
                          "username": ""}],
        },
        "work": [
            {"name": "BigCorp", "position": "Lead", "url": "https://big.example",
             "startDate": "2021-03", "endDate": "2023-08",
             "summary": "Led a team."},
            {"name": "SmallCo", "position": "Dev", "startDate": "2019-01"},
        ],
        "education": [
            {"institution": "Oxford", "url": "https://ox.ac.uk",
             "studyType": "MSc", "startDate": "2016", "endDate": "2018"}],
        "skills": [
            {"name": "SQL", "level": "Advanced", "keywords": []},
            {"name": "Rust", "keywords": []}],
        "publications": [
            {"name": "Deep Nets", "publisher": "ACM",
             "releaseDate": "2022-05", "url": "https://doi.example/2",
             "summary": "Networks."}],
        "volunteer": [
            {"organization": "Food Bank", "position": "Helper",
             "url": "https://fb.example", "startDate": "2020-01",
             "summary": "Sorted food."}],
        "projects": [
            {"name": "Widget", "description": "A widget.",
             "url": "https://widget.example"}],
        # Unmapped sections must be ignored without error.
        "awards": [{"title": "Best Paper"}],
        "certificates": [{"name": "PMP"}],
        "languages": [{"language": "French"}],
        "interests": [{"name": "Chess"}],
        "references": [{"name": "A Person"}],
    }


# ----------------------------------------------------- to_jsonresume (export)
class ToJsonResumeTest(unittest.TestCase):
    def setUp(self):
        self.jr = to_jsonresume(flowcv_resume())

    def test_schema_and_shape(self):
        self.assertEqual(self.jr["$schema"], SCHEMA)
        self.assertIn("basics", self.jr)

    def test_basics_fields(self):
        b = self.jr["basics"]
        self.assertEqual(b["name"], "Jane Doe")
        self.assertEqual(b["label"], "Staff Engineer")
        self.assertEqual(b["email"], "jane@example.com")
        self.assertEqual(b["phone"], "+1 555 0100")

    def test_basics_location(self):
        loc = self.jr["basics"]["location"]
        self.assertEqual(loc, {"address": "1 Main St", "city": "Boston",
                               "countryCode": "USA"})

    def test_basics_profiles_from_social(self):
        self.assertEqual(self.jr["basics"]["profiles"], [
            {"network": "LinkedIn", "url": "https://linkedin.com/in/jane",
             "username": ""}])

    def test_basics_summary_from_profile(self):
        self.assertEqual(self.jr["basics"]["summary"],
                         "Experienced **engineer** who ships.")

    def test_photo_skipped(self):
        self.assertNotIn("photo", self.jr["basics"])
        self.assertNotIn("image", self.jr["basics"])

    def test_work_mapping_and_hidden_excluded(self):
        self.assertEqual(self.jr["work"], [
            {"name": "Acme", "position": "Engineer", "url": "https://acme.example",
             "startDate": "2020-01",
             "summary": "- Built things\n- Shipped more"}])

    def test_work_present_omits_enddate(self):
        self.assertNotIn("endDate", self.jr["work"][0])

    def test_education_mapping(self):
        self.assertEqual(self.jr["education"], [
            {"institution": "MIT", "url": "https://mit.edu", "studyType": "BSc CS",
             "startDate": "2014-09", "endDate": "2018-06"}])

    def test_skills_mapping_level_optional(self):
        self.assertEqual(self.jr["skills"], [
            {"name": "Python", "level": "Expert", "keywords": []},
            {"name": "Go", "keywords": []}])

    def test_publication_releasedate_from_structured_date(self):
        self.assertEqual(self.jr["publications"], [
            {"name": "My Paper", "publisher": "IEEE", "releaseDate": "2021-03",
             "url": "https://doi.example", "summary": "A short abstract."}])

    def test_volunteer_from_organisation(self):
        self.assertEqual(self.jr["volunteer"], [
            {"organization": "Red Cross", "position": "Volunteer",
             "url": "https://redcross.example", "startDate": "2019-01",
             "endDate": "2020-01", "summary": "Helped out."}])

    def test_projects_from_custom(self):
        self.assertEqual(self.jr["projects"], [
            {"name": "CoolApp", "description": "A cool app.",
             "url": "https://cool.example"}])

    def test_unmapped_sections_absent(self):
        for k in ("languages", "certificates", "awards", "references", "interests"):
            self.assertNotIn(k, self.jr)

    def test_empty_section_omitted(self):
        r = flowcv_resume()
        # Hide the only visible work entry -> work has no visible entries.
        r["content"]["work"]["entries"] = [
            {"id": "W1", "isHidden": True, "employer": "Acme",
             "jobTitle": "Engineer"}]
        jr = to_jsonresume(r)
        self.assertNotIn("work", jr)

    def test_missing_sections_omitted(self):
        jr = to_jsonresume({"personalDetails": {"fullName": "X"}, "content": {}})
        for k in ("work", "education", "skills", "publications", "volunteer",
                  "projects"):
            self.assertNotIn(k, jr)


# --------------------------------------------------- from_jsonresume (import)
def base_resume():
    """A full FlowCV resume object to import into (content gets replaced)."""
    r = flowcv_resume()
    r["uuid"] = "u-1"
    r["customization"] = {"font": {"selected": "sans"}}
    return r


class FromJsonResumeTest(unittest.TestCase):
    def setUp(self):
        self.base = base_resume()
        self.res = from_jsonresume(jsonresume_doc(), self.base)

    def test_deep_copies_base(self):
        before = copy.deepcopy(self.base)
        self.res["personalDetails"]["fullName"] = "MUTATED"
        self.res["content"]["work"]["entries"].append({"id": "zzz"})
        self.res["customization"]["font"]["selected"] = "serif"
        self.assertEqual(self.base, before)

    def test_preserves_base_identity_and_design(self):
        self.assertEqual(self.res["id"], "R1")
        self.assertEqual(self.res["uuid"], "u-1")
        self.assertEqual(self.res["customization"], {"font": {"selected": "sans"}})

    def test_personal_details_overwritten(self):
        pd = self.res["personalDetails"]
        self.assertEqual(pd["fullName"], "John Smith")
        self.assertEqual(pd["jobTitle"], "Data Scientist")
        self.assertEqual(pd["email"], "john@example.com")
        self.assertEqual(pd["phone"], "+44 20 0000")
        self.assertEqual(pd["address"], "5 High St")
        self.assertEqual(pd["city"], "London")
        self.assertEqual(pd["country"], "UK")

    def test_profiles_to_social(self):
        social = self.res["personalDetails"]["social"]
        self.assertIn("github", social)
        self.assertEqual(social["github"],
                         {"display": "GitHub", "link": "https://github.com/js"})
        self.assertIn("github", self.res["personalDetails"]["detailsOrder"])

    def test_summary_to_profile_section(self):
        prof = self.res["content"]["profile"]
        self.assertEqual(prof["sectionType"], "profile")
        self.assertEqual(prof["displayName"], "Summary")
        self.assertEqual(prof["iconKey"], "address-card")
        self.assertEqual(prof["entries"][0]["text"], md_to_html("A **data** person."))

    def test_section_shapes_valid(self):
        for sid, stype, name, icon in [
            ("work", "work", "Professional Experience", "briefcase"),
            ("education", "education", "Education", "graduation-cap"),
            ("skill", "skill", "Skills", "head-side-brain"),
            ("publication", "publication", "Publications", "newspaper"),
            ("organisation", "organisation", "Organisations", "house-user"),
            ("custom1", "custom", "Custom", "star"),
        ]:
            sec = self.res["content"][sid]
            self.assertEqual(sec["sectionType"], stype)
            self.assertEqual(sec["displayName"], name)
            self.assertEqual(sec["iconKey"], icon)
            self.assertIsInstance(sec["entries"], list)

    def test_entries_have_uuid_ids_and_not_hidden(self):
        ids = set()
        for sid in ("work", "education", "skill", "publication", "organisation",
                    "custom1", "profile"):
            for e in self.res["content"][sid]["entries"]:
                self.assertFalse(e["isHidden"])
                self.assertIn("id", e)
                self.assertRegex(e["id"], r"[0-9a-f-]{36}")
                self.assertNotIn(e["id"], ids)  # unique across all entries
                ids.add(e["id"])

    def test_work_dates_and_present(self):
        entries = self.res["content"]["work"]["entries"]
        self.assertEqual(entries[0]["employer"], "BigCorp")
        self.assertEqual(entries[0]["jobTitle"], "Lead")
        self.assertEqual(entries[0]["employerLink"], "https://big.example")
        self.assertEqual(entries[0]["startDateNew"], "03/2021")
        self.assertEqual(entries[0]["endDateNew"], "08/2023")
        # Missing endDate for work -> "Present".
        self.assertEqual(entries[1]["startDateNew"], "01/2019")
        self.assertEqual(entries[1]["endDateNew"], "Present")

    def test_education_dates_year_only(self):
        e = self.res["content"]["education"]["entries"][0]
        self.assertEqual(e["school"], "Oxford")
        self.assertEqual(e["degree"], "MSc")
        self.assertEqual(e["startDateNew"], "2016")
        self.assertEqual(e["endDateNew"], "2018")

    def test_skills_level_optional(self):
        entries = self.res["content"]["skill"]["entries"]
        self.assertEqual(entries[0]["skill"], "SQL")
        self.assertEqual(entries[0]["skillLevel"], "Advanced")
        self.assertEqual(entries[1]["skill"], "Rust")
        self.assertNotIn("skillLevel", entries[1])

    def test_publication_structured_date(self):
        e = self.res["content"]["publication"]["entries"][0]
        self.assertEqual(e["title"], "Deep Nets")
        self.assertEqual(e["publisher"], "ACM")
        self.assertEqual(e["date"], {"year": "2022", "month": "5", "day": "",
                                     "hideMonth": False, "hideDay": True})

    def test_volunteer_to_organisation(self):
        e = self.res["content"]["organisation"]["entries"][0]
        self.assertEqual(e["organisationName"], "Food Bank")
        self.assertEqual(e["position"], "Helper")
        self.assertEqual(e["startDateNew"], "01/2020")
        self.assertEqual(e["endDateNew"], "Present")  # missing end for volunteer

    def test_projects_to_custom(self):
        e = self.res["content"]["custom1"]["entries"][0]
        self.assertEqual(e["title"], "Widget")
        self.assertEqual(e["titleLink"], "https://widget.example")
        self.assertEqual(e["description"], md_to_html("A widget."))

    def test_unknown_sections_ignored(self):
        # awards/certificates/languages/interests/references never appear.
        content = self.res["content"]
        for sid in ("award", "awards", "certificate", "certificates",
                    "language", "languages", "interest", "interests",
                    "reference", "references"):
            self.assertNotIn(sid, content)

    def test_empty_jsonresume_yields_empty_content(self):
        res = from_jsonresume({"basics": {}}, base_resume())
        self.assertEqual(res["content"], {})

    def test_missing_summary_no_profile_section(self):
        jr = jsonresume_doc()
        jr["basics"].pop("summary")
        res = from_jsonresume(jr, base_resume())
        self.assertNotIn("profile", res["content"])


# ------------------------------------------------------------- round trips
class RoundTripTest(unittest.TestCase):
    def test_work_names_positions_dates_preserved(self):
        jr = jsonresume_doc()
        back = to_jsonresume(from_jsonresume(jr, base_resume()))
        got = [{k: w.get(k) for k in ("name", "position", "startDate", "endDate")}
               for w in back["work"]]
        want = [{"name": "BigCorp", "position": "Lead", "startDate": "2021-03",
                 "endDate": "2023-08"},
                {"name": "SmallCo", "position": "Dev", "startDate": "2019-01",
                 "endDate": None}]
        self.assertEqual(got, want)

    def test_profile_summary_round_trip(self):
        # FlowCV profile -> basics.summary -> FlowCV profile is stable.
        r = flowcv_resume()
        jr = to_jsonresume(r)
        res = from_jsonresume(jr, base_resume())
        orig_html = r["content"]["profile"]["entries"][0]["text"]
        self.assertEqual(res["content"]["profile"]["entries"][0]["text"], orig_html)

    def test_publication_releasedate_round_trip(self):
        r = flowcv_resume()
        jr = to_jsonresume(r)
        res = from_jsonresume(jr, base_resume())
        self.assertEqual(res["content"]["publication"]["entries"][0]["date"],
                         {"year": "2021", "month": "3", "day": "",
                          "hideMonth": False, "hideDay": True})


if __name__ == "__main__":
    unittest.main()

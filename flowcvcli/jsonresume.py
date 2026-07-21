"""JSON Resume (jsonresume.org schema v1.0.0) <-> FlowCV resume-object interop.

Pure functions, no I/O and no client dependency. `to_jsonresume` turns a full
FlowCV resume object into a JSON Resume dict; `from_jsonresume` does the inverse,
overlaying a JSON Resume dict onto a DEEP-COPIED existing FlowCV resume (`base`)
so every NOT-NULL column FlowCV needs is inherited (see resume._create_from).

Section / field map (FlowCV <-> JSON Resume):

    personalDetails.fullName        <-> basics.name
    personalDetails.jobTitle        <-> basics.label
    personalDetails.email / phone   <-> basics.email / basics.phone
    address / city / country        <-> basics.location.address/city/countryCode
    social {k:{display,link}}        <-> basics.profiles [{network,url,username}]
    profile.entries[0].text          -> basics.summary  (basics.summary -> profile)
    work {employer,jobTitle,          <-> work {name,position,url,
      employerLink,startDateNew,             startDate,endDate,summary}
      endDateNew,description}
    education {school,schoolLink,     <-> education {institution,url,studyType,
      degree,startDateNew,endDateNew}        startDate,endDate}
    skill {skill,skillLevel}         <-> skills {name,level,keywords:[]}
    publication {title,publisher,     <-> publications {name,publisher,releaseDate,
      titleLink,date{},description}          url,summary}
    organisation {organisationName,   <-> volunteer {organization,position,url,
      position,organisationLink,...}         startDate,endDate,summary}
    custom* {title,titleLink,         <-> projects {name,description,url}
      description}

Dates: FlowCV "MM/YYYY" <-> "YYYY-MM"; year-only "YYYY" <-> "YYYY"; a FlowCV
"Present" (or empty) endDate is omitted from JSON Resume, and an absent
JSON Resume endDate becomes "Present" on import for work/volunteer (else empty).
Publications use FlowCV's structured `date` {year,month,day,hideMonth,hideDay}.

Lossiness (does NOT round-trip both ways):
  - FlowCV customization/design, template, layout, colors, fonts: not represented.
  - Photo/avatar (personalDetails.photo): dropped on export, untouched on import.
  - Hidden entries (isHidden): excluded from export.
  - JSON Resume sections FlowCV has no home for — awards, certificates,
    languages, interests, references — are ignored on import (and never emitted
    on export since FlowCV stores no such data here).
  - education/skill descriptions and per-entry extras JSON Resume lacks (e.g.
    skill.infoHtml, education free text, publication description on some layouts)
    are not carried; JSON Resume extras FlowCV lacks (basics.url, work.location,
    project highlights, skill.keywords) are dropped.
"""
import copy
import re
import uuid

from .content import SECTION_META
from .markup import html_to_md, md_to_html

SCHEMA_URL = "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json"


# --------------------------------------------------------------- date helpers
def _fc_date_to_jr(s):
    """FlowCV "MM/YYYY"/"YYYY"/"Present"/"" -> JSON Resume "YYYY-MM"/"YYYY"/None."""
    s = (s or "").strip()
    if not s or s.lower() == "present":
        return None
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m:
        return "%s-%02d" % (m.group(2), int(m.group(1)))
    return s  # year-only "YYYY" (or anything unrecognised) passes through


def _jr_date_to_fc(s):
    """JSON Resume "YYYY-MM[-DD]"/"YYYY"/"" -> FlowCV "MM/YYYY"/"YYYY"/""."""
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})-(\d{1,2})", s)
    if m:
        return "%02d/%s" % (int(m.group(2)), m.group(1))
    return s


def _fc_pubdate_to_jr(date):
    """FlowCV structured pub date -> JSON Resume releaseDate string (or None).

    Emits as much precision as is unhidden: day > month > year-only."""
    date = date or {}
    year = str(date.get("year") or "").strip()
    if not year:
        return None
    month = str(date.get("month") or "").strip()
    day = str(date.get("day") or "").strip()
    if not date.get("hideMonth", True) and month:
        if not date.get("hideDay", True) and day:
            return "%s-%02d-%02d" % (year, int(month), int(day))
        return "%s-%02d" % (year, int(month))
    return year


def _jr_pubdate_to_fc(s):
    """JSON Resume releaseDate -> FlowCV structured date (matching set_date's shape)."""
    date = {"year": "", "month": "", "day": "", "hideMonth": True, "hideDay": True}
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", (s or "").strip())
    if not m:
        return date
    date["year"] = m.group(1)
    if m.group(2):
        date["month"] = str(int(m.group(2)))
        date["hideMonth"] = False
    if m.group(3):
        date["day"] = str(int(m.group(3)))
        date["hideDay"] = False
    return date


# ----------------------------------------------------------------- utilities
def _compact(d):
    """Drop keys whose value is None or an empty string (keeps 0/False/[])."""
    return {k: v for k, v in d.items() if v is not None and v != ""}


def _visible(section):
    """Entries of a FlowCV section that aren't hidden (isHidden falsey)."""
    return [e for e in (section or {}).get("entries") or [] if not e.get("isHidden")]


def _rich_to_md(entry, field):
    """html_to_md of an entry's rich-text field (empty string if absent)."""
    return html_to_md(entry.get(field) or "")


# ------------------------------------------------------------- FlowCV -> JR
def _basics(pd):
    b = _compact({
        "name": pd.get("fullName"),
        "label": pd.get("jobTitle"),
        "email": pd.get("email"),
        "phone": pd.get("phone"),
    })
    loc = _compact({
        "address": pd.get("address"),
        "city": pd.get("city"),
        "countryCode": pd.get("country"),
    })
    if loc:
        b["location"] = loc
    profiles = []
    for key, v in (pd.get("social") or {}).items():
        v = v or {}
        profiles.append({"network": v.get("display") or key,
                         "url": v.get("link") or "", "username": ""})
    if profiles:
        b["profiles"] = profiles
    return b


def to_jsonresume(resume):
    """FlowCV resume object -> JSON Resume dict (empty sections omitted)."""
    content = resume.get("content") or {}
    basics = _basics(resume.get("personalDetails") or {})

    prof = _visible(content.get("profile"))
    if prof:
        summary = _rich_to_md(prof[0], "text")
        if summary:
            basics["summary"] = summary

    out = {"$schema": SCHEMA_URL, "basics": basics}

    work = []
    for e in _visible(content.get("work")):
        work.append(_compact({
            "name": e.get("employer"), "position": e.get("jobTitle"),
            "url": e.get("employerLink"),
            "startDate": _fc_date_to_jr(e.get("startDateNew")),
            "endDate": _fc_date_to_jr(e.get("endDateNew")),
            "summary": _rich_to_md(e, "description"),
        }))
    if work:
        out["work"] = work

    education = []
    for e in _visible(content.get("education")):
        education.append(_compact({
            "institution": e.get("school"), "url": e.get("schoolLink"),
            "studyType": e.get("degree"),
            "startDate": _fc_date_to_jr(e.get("startDateNew")),
            "endDate": _fc_date_to_jr(e.get("endDateNew")),
        }))
    if education:
        out["education"] = education

    skills = []
    for e in _visible(content.get("skill")):
        s = _compact({"name": e.get("skill"), "level": e.get("skillLevel")})
        s["keywords"] = []
        skills.append(s)
    if skills:
        out["skills"] = skills

    publications = []
    for e in _visible(content.get("publication")):
        publications.append(_compact({
            "name": e.get("title"), "publisher": e.get("publisher"),
            "releaseDate": _fc_pubdate_to_jr(e.get("date")),
            "url": e.get("titleLink"), "summary": _rich_to_md(e, "description"),
        }))
    if publications:
        out["publications"] = publications

    volunteer = []
    for e in _visible(content.get("organisation")):
        volunteer.append(_compact({
            "organization": e.get("organisationName"), "position": e.get("position"),
            "url": e.get("organisationLink"),
            "startDate": _fc_date_to_jr(e.get("startDateNew")),
            "endDate": _fc_date_to_jr(e.get("endDateNew")),
            "summary": _rich_to_md(e, "description"),
        }))
    if volunteer:
        out["volunteer"] = volunteer

    projects = []
    for sid, sec in content.items():
        if (sec or {}).get("sectionType") != "custom" \
                and not re.fullmatch(r"custom\d+", sid):
            continue
        default_name = (sec or {}).get("displayName")
        for e in _visible(sec):
            projects.append(_compact({
                "name": e.get("title") or default_name,
                "description": _rich_to_md(e, "description"),
                "url": e.get("titleLink"),
            }))
    if projects:
        out["projects"] = projects

    return out


# ------------------------------------------------------------- JR -> FlowCV
def _section(sid, entries):
    """A FlowCV content section dict with meta from SECTION_META."""
    stype, name, icon = SECTION_META[sid]
    return {"entries": entries, "sectionType": stype, "displayName": name,
            "iconKey": icon}


def _new_entry(**fields):
    """A fresh FlowCV entry: uuid id, visible, plus non-empty `fields`."""
    entry = {"id": str(uuid.uuid4()), "isHidden": False}
    entry.update(_compact(fields))
    return entry


def _apply_basics(pd, basics):
    """Overwrite personalDetails fields from a JSON Resume `basics` (in place)."""
    for jr_key, pd_key in (("name", "fullName"), ("label", "jobTitle"),
                           ("email", "email"), ("phone", "phone")):
        if basics.get(jr_key):
            pd[pd_key] = basics[jr_key]
    loc = basics.get("location") or {}
    for jr_key, pd_key in (("address", "address"), ("city", "city"),
                           ("countryCode", "country")):
        if loc.get(jr_key):
            pd[pd_key] = loc[jr_key]
    profiles = basics.get("profiles") or []
    if profiles:
        social = {}
        order = list(pd.get("detailsOrder") or [])
        for p in profiles:
            net = (p or {}).get("network") or ""
            key = re.sub(r"[^a-z0-9]", "", net.lower()) or "link"
            social[key] = {"display": net, "link": (p or {}).get("url") or ""}
            if key not in order:
                order.append(key)
        pd["social"] = social
        pd["detailsOrder"] = order


def from_jsonresume(jr, base):
    """JSON Resume dict + a full FlowCV resume `base` -> a deep-copied FlowCV
    resume with personalDetails overlaid from basics and content rebuilt from the
    JSON Resume sections. `base` supplies identity/design and is never mutated."""
    resume = copy.deepcopy(base)
    basics = jr.get("basics") or {}
    _apply_basics(resume.setdefault("personalDetails", {}), basics)

    content = {}

    if basics.get("summary"):
        content["profile"] = _section("profile", [
            _new_entry(text=md_to_html(basics["summary"]))])

    work = []
    for w in jr.get("work") or []:
        end = _jr_date_to_fc(w.get("endDate"))
        work.append(_new_entry(
            employer=w.get("name"), jobTitle=w.get("position"),
            employerLink=w.get("url"),
            startDateNew=_jr_date_to_fc(w.get("startDate")),
            endDateNew=end or "Present",
            description=md_to_html(w.get("summary") or "")))
    if work:
        content["work"] = _section("work", work)

    education = []
    for e in jr.get("education") or []:
        education.append(_new_entry(
            school=e.get("institution"), schoolLink=e.get("url"),
            degree=e.get("studyType"),
            startDateNew=_jr_date_to_fc(e.get("startDate")),
            endDateNew=_jr_date_to_fc(e.get("endDate"))))
    if education:
        content["education"] = _section("education", education)

    skills = []
    for s in jr.get("skills") or []:
        skills.append(_new_entry(skill=s.get("name"), skillLevel=s.get("level")))
    if skills:
        content["skill"] = _section("skill", skills)

    publications = []
    for p in jr.get("publications") or []:
        publications.append(_new_entry(
            title=p.get("name"), publisher=p.get("publisher"),
            titleLink=p.get("url"),
            date=_jr_pubdate_to_fc(p.get("releaseDate")),
            description=md_to_html(p.get("summary") or "")))
    if publications:
        content["publication"] = _section("publication", publications)

    volunteer = []
    for v in jr.get("volunteer") or []:
        end = _jr_date_to_fc(v.get("endDate"))
        volunteer.append(_new_entry(
            organisationName=v.get("organization"), position=v.get("position"),
            organisationLink=v.get("url"),
            startDateNew=_jr_date_to_fc(v.get("startDate")),
            endDateNew=end or "Present",
            description=md_to_html(v.get("summary") or "")))
    if volunteer:
        content["organisation"] = _section("organisation", volunteer)

    projects = []
    for p in jr.get("projects") or []:
        projects.append(_new_entry(
            title=p.get("name"), titleLink=p.get("url"),
            description=md_to_html(p.get("description") or "")))
    if projects:
        content["custom1"] = _section("custom1", projects)

    resume["content"] = content
    return resume

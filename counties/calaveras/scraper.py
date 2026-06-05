"""Calaveras County tentative-rulings scraper.

Calaveras keeps long static lists for case-management and civil law-and-motion
PDFs. Filenames vary by year and by upload location, so discovery keys off the
link text and the fact that the link target is a court-hosted PDF.

Parsing supports the two observed current layouts:

* Case-management calendars: date and time headers, followed by bare case
  number rows with wrapped party titles and disposition text.
* Law-and-motion calendars: title line, case number line, motion title, then a
  ruling body. These PDFs often rely on the source filename for the hearing
  date.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import pypdf

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://www.calaveras.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-case-management",
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-civil-law-and-motion-calendar",
]


def _division_from_page(page_url: str, text: str) -> str | None:
    haystack = f"{page_url} {text}".lower()
    if "case-management" in haystack or "cmc" in haystack:
        return "Case Management"
    if "civil-law" in haystack or "civil tentative" in haystack:
        return "Civil Law and Motion"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if not link.url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        text = link.text
        if "tentative" not in text.lower() and "cmc" not in text.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.calaveras.courts.ca.gov", "calaveras.courts.ca.gov"}:
            continue
        if not parsed.path.lower().startswith("/system/files/"):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_page(source_page, text),
                link_text=text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)


# ============================================================ PARSE


CASE_NUMBER_LINE_RE = re.compile(
    r"^\s*(?P<num>\d{2}[A-Z]{2,4}\d{4,6})\b(?:[ \t]+(?P<rest>.*?))?\s*$",
    re.MULTILINE,
)
LONG_DATE_RE = re.compile(
    r"\b(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
URL_DASH_DATE_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})[-_](?P<d>\d{1,2})[-_](?P<y>\d{2,4})(?!\d)")
URL_COMPACT_DATE_RE = re.compile(r"(?<!\d)(?P<m>\d{2})(?P<d>\d{2})(?P<y>20\d{2})(?!\d)")
SECTION_RE = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}\s*[AP]\.?\s*M\.?\s*)?"
    r"(?P<section>(?:Civil|Family\s+Law)\s+Case\s+Management|Civil\s+Law\s+and\s+Motion)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
CONTINUED_TO_RE = re.compile(
    r"(?:continued|set|scheduled)\s+(?:for|to|on)\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE | re.DOTALL,
)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}

_BODY_START_RE = re.compile(
    r"\b(?:There\s+is|The\s+case|The\s+matter|All\s+Defendants|Plaintiff\s+|Defendant\s+|"
    r"Petitioner\s+|Respondent\s+|Appearances?\s+|Judgment\s+|This\s+is|Now\s+before)\b",
    re.IGNORECASE,
)


def _parse_long_date(text: str) -> date | None:
    m = LONG_DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month").upper())
    if not month:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def _parse_url_date(source_url: str) -> date | None:
    for pattern in (URL_DASH_DATE_RE, URL_COMPACT_DATE_RE):
        m = pattern.search(source_url)
        if not m:
            continue
        year = int(m.group("y"))
        if year < 100:
            year += 2000
        try:
            return date(year, int(m.group("m")), int(m.group("d")))
        except ValueError:
            continue
    return None


def _section_name(raw: str) -> str:
    upper = raw.upper()
    if "FAMILY" in upper:
        return "Family Law Case Management"
    if "CASE MANAGEMENT" in upper:
        return "Civil Case Management"
    return "Civil Law and Motion"


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bCONTINUED\s+OSC\b|\bIS\s+CONTINUED\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bDROPPED\s+FROM\b|\bVACATED\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:REQUIRED|NECESSARY)\b", upper))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_off_calendar:
        outcome = "off_calendar"
    elif has_appearance:
        outcome = "appearance_required"
    else:
        outcome = "other"

    continued_to = None
    if has_continued:
        m = CONTINUED_TO_RE.search(text)
        if m:
            month = _MONTHS.get(m.group("month").upper())
            if month:
                try:
                    continued_to = date(int(m.group("year")), month, int(m.group("day")))
                except ValueError:
                    pass
    return outcome, conditional, continued_to


def _strip_pages(page_texts: list[str]) -> list[str]:
    out: list[str] = []
    for text in page_texts:
        lines = [line for line in text.splitlines() if not PAGE_NUMBER_RE.match(line)]
        out.append("\n".join(lines))
    return out


def _join_pages(page_texts: list[str]) -> tuple[str, list[int]]:
    offsets: list[int] = []
    parts: list[str] = []
    cursor = 0
    sep = "\n\n"
    for page in page_texts:
        offsets.append(cursor)
        parts.append(page)
        cursor += len(page) + len(sep)
    return sep.join(parts), offsets


def _page_for_offset(offsets: list[int], offset: int) -> int:
    page = 1
    for i, start in enumerate(offsets):
        if start <= offset:
            page = i + 1
        else:
            break
    return page


def _is_title_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    if upper / len(letters) >= 0.70:
        return True
    if _BODY_START_RE.search(s):
        return False
    return bool(re.search(r"\bv(?:\.|s\.?)?\b", s, re.IGNORECASE))


def _split_inline_title(rest: str) -> tuple[str, str]:
    if not rest:
        return "", ""
    m = _BODY_START_RE.search(rest)
    if not m:
        return rest.strip(), ""
    return rest[: m.start()].strip(), rest[m.start():].strip()


def _title_above(plain: str, anchor_start: int) -> str:
    lines: list[str] = []
    for line in reversed(plain[:anchor_start].splitlines()):
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        if CASE_NUMBER_LINE_RE.match(s) or SECTION_RE.match(s):
            break
        if _is_title_line(s):
            lines.append(s)
            continue
        if lines:
            break
    lines.reverse()
    return " ".join(" ".join(lines).split())


def _split_block(anchor: re.Match[str], block: str, plain: str) -> tuple[str, str, str, str]:
    rest = (anchor.group("rest") or "").strip()
    case_title = ""
    motion_type = ""
    body_lines: list[str] = []

    if not rest:
        case_title = _title_above(plain, anchor.start())
        lines = [line.strip() for line in block.splitlines()]
        idx = 0
        motion_lines: list[str] = []
        while idx < len(lines):
            s = lines[idx]
            if not s:
                idx += 1
                continue
            if not _is_title_line(s):
                break
            motion_lines.append(s)
            idx += 1
        motion_type = " ".join(motion_lines)
        body_lines = [line for line in lines[idx:] if line]
        return case_title, motion_type, "\n".join(body_lines).strip(), "calaveras-lawmotion"

    title_start, body_start = _split_inline_title(rest)
    title_lines = [title_start] if title_start else []
    if body_start:
        body_lines.append(body_start)
    for line in block.splitlines():
        s = line.strip()
        if not s:
            continue
        if not body_lines and _is_title_line(s):
            title_lines.append(s)
            continue
        body_lines.append(s)
    case_title = " ".join(" ".join(title_lines).split())
    return case_title, "Case Management Conference", "\n".join(body_lines).strip(), "calaveras-cmc"


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return []
    raw_pages = [page.extract_text() or "" for page in reader.pages]
    if not raw_pages:
        return []

    pages = _strip_pages(raw_pages)
    plain, offsets = _join_pages(pages)
    hearing_date = _parse_long_date(plain[:1000]) or _parse_url_date(source_url)
    if hearing_date is None:
        return []

    anchors = list(CASE_NUMBER_LINE_RE.finditer(plain))
    if not anchors:
        return []

    rulings: list[Ruling] = []
    current_division = division_hint or "Civil Law and Motion"
    for i, anchor in enumerate(anchors):
        region_start = anchors[i - 1].end() if i > 0 else 0
        region = plain[region_start:anchor.start()]
        for sm in SECTION_RE.finditer(region):
            current_division = _section_name(sm.group("section"))

        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        case_title, motion_type, body, style = _split_block(anchor, plain[anchor.end():block_end], plain)
        if not body and not motion_type:
            continue
        outcome, conditional, continued_to = _classify(body or motion_type)
        page_start = _page_for_offset(offsets, anchor.start())
        page_end = max(page_start, _page_for_offset(offsets, max(anchor.start(), block_end - 1)))
        case_number = anchor.group("num").upper()

        rulings.append(
            Ruling(
                ruling_id=_ruling_id(source_sha256, len(rulings) + 1, case_number),
                county=COUNTY_SLUG,
                division=current_division,
                dept=dept_hint,
                hearing_date=hearing_date,
                ruling_index=len(rulings) + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=plain[anchor.start():block_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=style,
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.now(UTC),
            )
        )

    return rulings


def parse_file(
    path: str,
    source_url: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    with open(path, "rb") as f:
        data = f.read()
    if source_url is None:
        source_url = f"file://{path}"
    return parse(data, source_url=source_url, dept_hint=dept_hint, division_hint=division_hint)

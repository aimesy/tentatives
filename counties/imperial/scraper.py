"""Imperial County public tentative-ruling source discovery."""

from __future__ import annotations

from datetime import date
import re

from counties.static_pdf import discover_static_pdfs
from counties.simple_parser import clean_lines, extract_pdf_pages, find_date, inline, join_pages, make_ruling, page_for_offset, source_sha
from schema import Ruling

BASE = "https://www.imperial.courts.ca.gov/general-information/tentative-rulings"
LANDING_PAGES = [
    BASE,
    "https://www.imperial.courts.ca.gov/news/tentative-rulings",
]
WAYBACK_PDF_PATTERNS = [
    "https://www.imperial.courts.ca.gov/system/files/tentative-rulings/*.pdf",
]


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.imperial.courts.ca.gov", "imperial.courts.ca.gov"},
        path_test=lambda parsed, text: (
            "/system/files/tentative-rulings/" in parsed.path.lower()
            or "tentative" in f"{parsed.path} {text}".lower()
        ),
        default_division="Civil Law and Motion",
    )


# The current Imperial PDF does not carry its hearing date in the PDF text or
# filename. The court page lists this event as "Hearing date: 11/07/2024".
KNOWN_HEARING_DATES = {
    ("ECUO03561", "imperial-demurrer-mtn-strike-mtn-dismiss-ecu003561.pdf"): date(2024, 11, 7),
}
SECTION_HEADER_RE = re.compile(
    r"(?im)^\s*Tentative\s+Ruling(?:\s+(?P<num>[A-Z]{3,5}\d{5,}))?\s*$"
)


def _normalize_text(text: str) -> str:
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = re.sub(r"\bT\s+entative\b", "Tentative", text)
    text = re.sub(r"\bECUO(?=\d)", "ECUO", text)
    return clean_lines(text)


def _known_hearing_date(case_number: str, source_url: str) -> date | None:
    lower_url = source_url.lower()
    for (known_case, marker), hearing_date in KNOWN_HEARING_DATES.items():
        if case_number == known_case and marker in lower_url:
            return hearing_date
    return None


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages = [_normalize_text(page) for page in extract_pdf_pages(pdf_bytes)]
    if not pages:
        return []
    plain, offsets = join_pages(pages)
    if not plain:
        return []

    sections = list(SECTION_HEADER_RE.finditer(plain))
    if not sections:
        return []

    first_num = next((inline(section.group("num")).upper() for section in sections if section.group("num")), "")
    if not first_num:
        return []
    hearing_date = find_date(plain[:1200]) or _known_hearing_date(first_num, source_url)
    if hearing_date is None:
        return []

    case_number = first_num
    case_title = ""
    rulings: list[Ruling] = []
    for index, section in enumerate(sections):
        start = section.start()
        end = sections[index + 1].start() if index + 1 < len(sections) else len(plain)
        lines = [inline(line) for line in plain[section.end():end].splitlines() if inline(line)]
        if not lines:
            continue
        section_num = inline(section.group("num") or "").upper()
        if section_num:
            case_number = section_num
            if len(lines) < 3:
                continue
            case_title = lines[0]
            motion = lines[1]
            body = "\n".join(lines[2:]).strip()
        else:
            if not case_title or len(lines) < 2:
                continue
            motion = lines[0]
            body = "\n".join(lines[1:]).strip()
        if not body:
            continue
        page_start = page_for_offset(offsets, start)
        page_end = max(page_start, page_for_offset(offsets, max(start, end - 1)))
        rulings.append(make_ruling(
            county="imperial",
            source_sha256=sha,
            source_url=source_url,
            parser_version="imperial-v1",
            style="imperial-section-ruling",
            index=len(rulings) + 1,
            case_number=case_number,
            case_title=case_title,
            hearing_date=hearing_date,
            full_text=plain[start:end],
            body_text=body,
            outcome_text=body.splitlines()[0] if body.splitlines() else body,
            motion_type=motion,
            division=division_hint or "Civil Law and Motion",
            dept=dept_hint,
            page_start=page_start,
            page_end=page_end,
        ))
    return rulings

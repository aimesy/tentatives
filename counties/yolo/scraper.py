"""Yolo County public calendar-page tentative-ruling discovery."""

from __future__ import annotations

import io
import re
from urllib.parse import urlparse

import pypdf

from counties.common import PageRef, PdfRef, absolute_url, clean_text, extract_links, filename_from_url
from counties.simple_parser import (
    clean_lines,
    find_date,
    inline,
    join_pages,
    make_ruling,
    page_for_offset,
    source_sha,
)

BASE = "https://www.yolo.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings-calendar",
    f"{BASE}/online-services/probate-note-calendar",
]
PAGE_CAPTURE_URLS = [
    PageRef(
        url=f"{BASE}/online-services/tentative-rulings-calendar",
        title="Yolo Tentative Rulings Calendar",
        page_kind="tentative_rulings_calendar",
    ),
    PageRef(
        url=f"{BASE}/online-services/probate-note-calendar",
        title="Yolo Probate Note Calendar",
        page_kind="probate_note_calendar",
    ),
]


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def _calendar_document_paths(html: str) -> list[str]:
    text = html
    for _ in range(3):
        text = (
            text.replace("\\\\/", "/")
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u0022", '"')
        )
    paths = re.findall(r"/document/[A-Za-z0-9_.-]+", text)
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _document_page_refs(html: str, page_url: str) -> list[PageRef]:
    refs: list[PageRef] = []
    for path in _calendar_document_paths(html):
        title = "Yolo probate notes" if "probate" in path else "Yolo tentative ruling"
        refs.append(
            PageRef(
                url=absolute_url(path, page_url),
                title=title,
                page_kind="document_page",
            )
        )
    return refs


def _division_for_url(*values: str) -> str:
    low = " ".join(values).lower()
    if "probate" in low:
        return "Probate Notes"
    if "ato-prb" in low or "prb-" in low:
        return "Probate Notes"
    return "Tentative Rulings"


def _pdf_refs_from_document(html: str, page_url: str) -> list[PdfRef]:
    refs: list[PdfRef] = []
    for link in extract_links(html):
        url = absolute_url(link.url, page_url)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.yolo.courts.ca.gov", "yolo.courts.ca.gov"}:
            continue
        if not parsed.path.lower().endswith(".pdf"):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_for_url(page_url, url, clean_text(link.text)),
                link_text=clean_text(link.text) or filename_from_url(url),
                source_page_url=page_url,
            )
        )
    return refs


def discover_live_pages(html: str, page_url: str | None = None):
    return _document_page_refs(html, page_url or LANDING_PAGES[0])


def discover_live_page_extra(session, errors=None):
    refs: list[PageRef] = []
    for url in LANDING_PAGES:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        refs.extend(_document_page_refs(response.text, url))
    return refs


def discover_live_extra(session, errors=None):
    refs: list[PdfRef] = []
    for url in LANDING_PAGES:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        for page_ref in _document_page_refs(response.text, url):
            doc = session.get(page_ref.url, timeout=60)
            doc.raise_for_status()
            refs.extend(_pdf_refs_from_document(doc.text, page_ref.url))
    return refs


DEPT_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
}


def _dept_value(value: str | None) -> str | None:
    if not value:
        return None
    text = inline(value).strip(" .")
    return DEPT_WORDS.get(text.lower(), text)


def _extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted and not reader.decrypt(""):
            return []
        return [clean_lines(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return []


def _page_span(offsets: list[int], start: int, end: int) -> tuple[int, int]:
    return page_for_offset(offsets, start), page_for_offset(offsets, max(start, end - 1))


def _case_number_pattern() -> str:
    return r"(?:CV|PR|JV|PT|SP|UD)[- ]?\d{4,}[- ]?\d*"


def _parse_law_motion(plain: str, offsets: list[int], *, sha: str, source_url: str) -> list:
    anchors = list(re.finditer(r"(?m)^TENTATIVE RULING\s*$", plain))
    rows = []
    for anchor_index, anchor in enumerate(anchors):
        end = anchors[anchor_index + 1].start() if anchor_index + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        if not block:
            continue
        case_match = re.search(r"(?ims)^Case:\s*(?P<title>.*?)(?=\n\s*Case No\.?\s*:?)", block)
        number_match = re.search(rf"(?im)^Case No\.?\s*:?\s*(?P<num>{_case_number_pattern()})\b", block)
        hearing_match = re.search(r"(?im)^Hearing Date:\s*(?P<line>.+)$", block)
        if not case_match or not number_match or not hearing_match:
            continue
        hearing_date = find_date(hearing_match.group("line")) or find_date(block[:800])
        if not hearing_date:
            continue
        dept_match = re.search(r"Department\s+(?P<dept>[A-Za-z0-9]+)", hearing_match.group("line"), re.IGNORECASE)
        lines = block.splitlines()
        hearing_line_index = next((i for i, line in enumerate(lines) if line.startswith("Hearing Date:")), -1)
        after_lines = [line for line in lines[hearing_line_index + 1 :] if inline(line)] if hearing_line_index != -1 else []
        motion = ""
        body_lines = after_lines
        if after_lines:
            first = inline(after_lines[0])
            if re.match(
                r"^(?:Demurrer|Motion|Petition|Application|Request|Order|OSC|Case Management|Trial Setting|Claim of Exemption)\b",
                first,
                re.IGNORECASE,
            ):
                motion = first
                body_lines = after_lines[1:]
        body = clean_lines("\n".join(body_lines))
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rows.append(
            make_ruling(
                county="yolo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="yolo-v1",
                style="yolo-law-motion",
                index=len(rows) + 1,
                case_number=number_match.group("num"),
                case_title=case_match.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division="Law and Motion",
                dept=_dept_value(dept_match.group("dept") if dept_match else None),
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rows


def _parse_probate_notes(plain: str, offsets: list[int], *, sha: str, source_url: str) -> list:
    hearing_date = find_date(plain[:500])
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?im)^Case:\s*(?P<title>.+)$", plain))
    rows = []
    for anchor_index, anchor in enumerate(anchors):
        end = anchors[anchor_index + 1].start() if anchor_index + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        number_match = re.search(rf"(?im)^Case No\.?\s*:?\s*(?P<num>{_case_number_pattern()})\b", block)
        if not number_match:
            continue
        prior = plain[max(0, anchor.start() - 500) : anchor.start()]
        dept_matches = list(re.finditer(r"Department\s+(?P<dept>[A-Za-z0-9]+)", prior, re.IGNORECASE))
        dept = _dept_value(dept_matches[-1].group("dept") if dept_matches else None)
        body = clean_lines(block[number_match.end() :])
        if not body:
            continue
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rows.append(
            make_ruling(
                county="yolo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="yolo-v1",
                style="yolo-probate-notes",
                index=len(rows) + 1,
                case_number=number_match.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type="Probate Notes",
                division="Probate Notes",
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rows


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
):
    sha = source_sha(pdf_bytes, source_sha256)
    pages = _extract_pdf_pages(pdf_bytes)
    if not pages or not any(page.strip() for page in pages):
        return []
    plain, offsets = join_pages(pages)
    if re.search(r"\bProbate Notes for\b", plain, re.IGNORECASE):
        return _parse_probate_notes(plain, offsets, sha=sha, source_url=source_url)
    return _parse_law_motion(plain, offsets, sha=sha, source_url=source_url)

"""Small parsing helpers for plain-text tentative ruling sources."""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, date, datetime
from html import unescape
from html.parser import HTMLParser

import pypdf

from schema import Ruling

MONTHS = (
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
)
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
MONTH_RE = "|".join(MONTHS)
WEEKDAY_RE = "|".join(WEEKDAYS)


class _TextParser(HTMLParser):
    BLOCK_TAGS = {
        "br",
        "div",
        "p",
        "li",
        "tr",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def clean_lines(text: str) -> str:
    text = unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def inline(text: str) -> str:
    return " ".join(clean_lines(text).split())


def html_to_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return clean_lines("".join(parser.parts))


def extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return []
    return [clean_lines(page.extract_text() or "") for page in reader.pages]


def join_pages(pages: list[str]) -> tuple[str, list[int]]:
    parts: list[str] = []
    offsets: list[int] = []
    total = 0
    for page in pages:
        offsets.append(total)
        parts.append(page)
        total += len(page) + 2
    return "\n\n".join(parts), offsets


def page_for_offset(offsets: list[int], pos: int) -> int:
    if not offsets:
        return 1
    page = 1
    for i, start in enumerate(offsets, start=1):
        if start <= pos:
            page = i
        else:
            break
    return page


def _normalize_year(value: str) -> int:
    year = int(value)
    if year < 100:
        return 2000 + year if year < 70 else 1900 + year
    return year


def parse_date_value(value: str) -> date | None:
    text = inline(value)
    text = re.sub(rf"^(?:{WEEKDAY_RE})\s*,?\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d{1,2})\s*,\s*(\d{4})", r"\1, \2", text)
    text = re.sub(r"(\d{1,2})\s+(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)

    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    numeric = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if numeric:
        return date(
            _normalize_year(numeric.group(3)),
            int(numeric.group(1)),
            int(numeric.group(2)),
        )

    long_date = re.search(
        rf"\b({MONTH_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
        text,
        re.IGNORECASE,
    )
    if long_date:
        month_name = long_date.group(1).lower()
        month = {m.lower(): i for i, m in enumerate(MONTHS, start=1)}[month_name]
        return date(int(long_date.group(3)), month, int(long_date.group(2)))
    return None


def find_date(text: str) -> date | None:
    for pattern in (
        rf"\b(?:{WEEKDAY_RE})\s*,?\s+(?:{MONTH_RE})\s+\d{{1,2}},?\s+\d{{4}}\b",
        rf"\b(?:{MONTH_RE})\s+\d{{1,2}},?\s+\d{{4}}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        r"\b20\d{2}-\d{1,2}-\d{1,2}\b",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = parse_date_value(match.group(0))
            if parsed:
                return parsed
    return None


def classify(text: str) -> tuple[str, bool, date | None]:
    low = text.lower()
    conditional = bool(re.search(r"\b(absent|unless|if)\b.{0,80}\bobjection", low))
    continued_to = None
    continued_match = re.search(
        r"continued\s+(?:to|until)\s+([A-Za-z]+ \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if continued_match:
        continued_to = parse_date_value(continued_match.group(1))
    if "off calendar" in low or "off-calendar" in low:
        return "off_calendar", conditional, continued_to
    if "continued" in low:
        return "continued", conditional, continued_to
    if (
        "appearance required" in low
        or "appearance is required" in low
        or "appearance ordered" in low
        or "parties shall appear" in low
        or "parties are ordered to appear" in low
    ):
        return "appearance_required", conditional, continued_to
    has_granted = bool(re.search(r"\bgranted\b|\bgrant\b", low))
    has_denied = bool(re.search(r"\bdenied\b|\bdeny\b", low))
    if has_granted and not has_denied:
        return "granted", conditional, continued_to
    if has_denied and not has_granted:
        return "denied", conditional, continued_to
    return "other", conditional, continued_to


def ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def make_ruling(
    *,
    county: str,
    source_sha256: str,
    source_url: str,
    parser_version: str,
    style: str,
    index: int,
    case_number: str,
    case_title: str,
    hearing_date: date,
    full_text: str,
    body_text: str = "",
    motion_type: str = "",
    division: str | None = None,
    dept: str | None = None,
    page_start: int = 1,
    page_end: int = 1,
    outcome_text: str | None = None,
) -> Ruling:
    outcome_source = outcome_text if outcome_text is not None else body_text or full_text
    outcome, conditional, continued_to = classify(outcome_source)
    return Ruling(
        ruling_id=ruling_id(source_sha256, index, case_number),
        county=county,
        division=division,
        dept=dept,
        hearing_date=hearing_date,
        ruling_index=index,
        case_number=inline(case_number),
        case_title=inline(case_title),
        motion_type=inline(motion_type),
        outcome=outcome,
        outcome_text=clean_lines(outcome_source),
        conditional=conditional,
        continued_to=continued_to,
        body_text=clean_lines(body_text),
        full_text=clean_lines(full_text),
        page_start=page_start,
        page_end=page_end,
        source_sha256=source_sha256,
        source_url=source_url,
        parser_version=parser_version,
        style=style,
        ingest_ts=datetime.now(UTC),
    )


def source_sha(pdf_bytes: bytes, source_sha256: str | None) -> str:
    return source_sha256 or hashlib.sha256(pdf_bytes).hexdigest()

"""El Dorado County tentative-rulings scraper.

Four stages, all separable for testing and replay:

  discover_live(html)   list of PDF refs from a dept landing page
  fetch(ref)            download PDF bytes
  parse(pdf_bytes, ...) extract Ruling records

The unit of input is a *file*, not a date — court purges old URLs from the live
server (~2 months of retention), and one PDF can cover a date range. Metadata
(hearing_date, dept, division) is taken from the page header inside the PDF,
not the filename, which has multiple inconsistent formats.

Reference fixture: counties/el_dorado/fixtures/tr-d-09-2026-05-18.pdf
  - 20 pages, 15 rulings, Dept. 9, Probate, hearing date 2026-05-18.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator
from urllib.parse import urljoin

import pypdf

from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION


# ---------------------------------------------------------------- DISCOVERY


PDF_HREF_RE = re.compile(
    r'href="(/system/files/tentative-rulings/[^"]+\.pdf)"',
    re.IGNORECASE,
)
DEPT_PAGE_RE = re.compile(
    r'href="(/online-services/tentative-rulings/tentative-rulings-dept-\d+)"',
    re.IGNORECASE,
)
BASE = "https://www.eldorado.courts.ca.gov"


@dataclass(frozen=True)
class PdfRef:
    """A PDF we know exists. Not yet fetched."""

    url: str
    filename: str
    wayback_ts: str | None = None


def discover_live(html: str, base_url: str = BASE) -> list[PdfRef]:
    """Extract PDF links from a dept landing page's HTML."""
    seen: set[str] = set()
    refs: list[PdfRef] = []
    for m in PDF_HREF_RE.finditer(html):
        path = m.group(1)
        url = urljoin(base_url + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen.add(url)
        refs.append(PdfRef(url=url, filename=path.rsplit("/", 1)[-1]))
    return refs


def discover_dept_pages(html: str, base_url: str = BASE) -> list[str]:
    """From any EDC tentative-rulings page, list URLs of all dept landing pages."""
    seen: set[str] = set()
    urls: list[str] = []
    for m in DEPT_PAGE_RE.finditer(html):
        path = m.group(1)
        url = urljoin(base_url + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return sorted(urls)


# ---------------------------------------------------------------- FETCH


def fetch(ref: PdfRef, session=None) -> tuple[bytes, str]:
    """Download the PDF. Returns (content, sha256). For Wayback refs uses id_ form."""
    import requests  # local import; not needed for parser tests

    sess = session or requests.Session()
    if ref.wayback_ts:
        url = f"https://web.archive.org/web/{ref.wayback_ts}id_/{ref.url}"
    else:
        url = ref.url
    r = sess.get(url, timeout=60)
    r.raise_for_status()
    content = r.content
    return content, hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------- PARSE


# Per-page header. Each PDF page begins with these four lines:
#   <MONTH DD, YYYY>
#   Dept. <N>
#   <Division Name> Tentative Rulings
#   <page-number>
HEADER_DATE_RE = re.compile(
    r"^([A-Z][A-Za-z]+ \d{1,2}, \d{4})\s*$",
    re.MULTILINE,
)
HEADER_DEPT_RE = re.compile(r"^Dept\.\s+(\d+)\s*$", re.MULTILINE)
HEADER_DIVISION_RE = re.compile(r"^(.+?)\s+Tentative Rulings\s*$", re.MULTILINE)

# Ruling header: "<N>. <CASE_NUMBER> <CASE_TITLE>" on one line, motion-type on the next.
# Case-number formats observed:
#   25PR0206       new style: <YY><type><####>
#   26PR0099
#   PP20200121     legacy style (pre-2021): <prefix><YYYY><####>
# Pattern covers both: optional leading digits, then letters, then digits.
RULING_HEADER_RE = re.compile(
    r"""^
    (?P<idx>\d{1,2})\.\s+
    (?P<case_number>\d*[A-Z]{2,}\d{3,})\s+
    (?P<case_title>[^\n]+?)\s*\n
    (?P<motion_type>[^\n]+?)\s*$
    """,
    re.MULTILINE | re.VERBOSE,
)

# Disposition section.
DISPOSITION_RE = re.compile(
    r"^TENTATIVE RULING #(?P<idx>\d{1,2}):\s*\n(?P<text>.*?)(?=\n\s*\n|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Common boilerplate to trim from disposition text.
REMOTE_BOILERPLATE_RE = re.compile(
    r"\s*IF A PARTY OR PARTIES WISH TO APPEAR REMOTELY,?\s+INSTRUCTIONS FOR REMOTE\s+"
    r"APPEARANCES CAN BE FOUND ON THE COURT[’']S WEBSITE\.?\s*",
    re.IGNORECASE | re.DOTALL,
)

# Continued-to date extractor. "CONTINUED TO MONDAY, JULY 6, 2026," or
# "CONTINUED TO MONDAY, JUNE 29, 2026, AT 8:30 AM ..."
CONTINUED_RE = re.compile(
    r"CONTINUED TO\s+(?:[A-Z]+,?\s+)?"
    r"(?P<month>[A-Z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}


def _parse_long_date(s: str) -> date:
    m = re.match(r"^([A-Z][A-Za-z]+) (\d{1,2}), (\d{4})$", s.strip())
    if not m:
        raise ValueError(f"unrecognised date: {s!r}")
    return date(int(m.group(3)), _MONTHS[m.group(1).upper()], int(m.group(2)))


@dataclass(frozen=True)
class PdfMeta:
    hearing_date: date
    dept: str
    division: str


def extract_meta(reader: pypdf.PdfReader) -> PdfMeta:
    """Read date/dept/division from the page-1 header."""
    text = reader.pages[0].extract_text() or ""
    date_m = HEADER_DATE_RE.search(text)
    dept_m = HEADER_DEPT_RE.search(text)
    div_m = HEADER_DIVISION_RE.search(text)
    if not (date_m and dept_m and div_m):
        raise ValueError(f"could not parse page-1 header; got: {text[:300]!r}")
    return PdfMeta(
        hearing_date=_parse_long_date(date_m.group(1)),
        dept=dept_m.group(1),
        division=div_m.group(1).strip(),
    )


def _strip_page_header(page_text: str, meta: PdfMeta) -> str:
    """Remove the 4-line header that repeats on every page."""
    lines = page_text.splitlines()
    # First 4 non-empty lines are: date / Dept. N / Division Tentative Rulings / page#
    out: list[str] = []
    skip = 4
    for line in lines:
        if skip > 0 and line.strip():
            skip -= 1
            continue
        out.append(line)
    return "\n".join(out)


def _classify(disposition_text: str) -> tuple[str, bool, date | None]:
    """Return (primary_outcome, conditional, continued_to)."""
    text = disposition_text.upper()
    text = REMOTE_BOILERPLATE_RE.sub("", text).strip()
    conditional = "ABSENT OBJECTION" in text

    # Priority order: substantive dispositions first.
    has_denied = bool(re.search(r"\bDENIED\b", text))
    has_granted = bool(re.search(r"\bGRANTED\b", text))
    has_continued = bool(re.search(r"\bCONTINUED TO\b|\bHEARING CONTINUED\b", text))
    has_appearance = bool(re.search(r"\bAPPEARANCES ARE REQUIRED\b", text))
    has_off_cal = bool(re.search(r"\bOFF CALENDAR\b|\bDROPPED FROM CALENDAR\b", text))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_appearance:
        outcome = "appearance_required"
    elif has_off_cal:
        outcome = "off_calendar"
    else:
        outcome = "other"

    continued_to: date | None = None
    if has_continued:
        m = CONTINUED_RE.search(disposition_text)
        if m:
            month = m.group("month").upper()
            if month in _MONTHS:
                continued_to = date(int(m.group("year")), _MONTHS[month], int(m.group("day")))

    return outcome, conditional, continued_to


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
) -> list[Ruling]:
    """Extract all rulings from one EDC tentative-rulings PDF."""
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    meta = extract_meta(reader)

    # Build a per-page text array, stripping the repeating header.
    page_texts: list[str] = []
    for page in reader.pages:
        raw = page.extract_text() or ""
        page_texts.append(_strip_page_header(raw, meta))
    full_doc_text = "\n\n".join(
        f"\x1ePAGE {i+1}\x1e\n{t}" for i, t in enumerate(page_texts)
    )

    # Find ruling header positions in the joined text (with page markers).
    # Strip page markers when searching headers but preserve them for page lookup.
    plain = re.sub(r"\x1ePAGE \d+\x1e\n", "", full_doc_text)
    page_offsets: list[tuple[int, int]] = []  # (offset_in_plain, page_number)
    cursor = 0
    for i, t in enumerate(page_texts):
        page_offsets.append((cursor, i + 1))
        cursor += len(t) + 2  # the "\n\n" between pages

    def page_for_offset(off: int) -> int:
        page = 1
        for o, p in page_offsets:
            if o <= off:
                page = p
            else:
                break
        return page

    header_matches = list(RULING_HEADER_RE.finditer(plain))
    if not header_matches:
        return []

    # Map ruling_idx → disposition text.
    dispositions: dict[int, tuple[str, int]] = {}  # idx -> (text, start_offset)
    for dm in DISPOSITION_RE.finditer(plain):
        idx = int(dm.group("idx"))
        dispositions[idx] = (dm.group("text").strip(), dm.start())

    rulings: list[Ruling] = []
    for i, hm in enumerate(header_matches):
        idx = int(hm.group("idx"))
        case_number = hm.group("case_number").strip()
        case_title = hm.group("case_title").strip()
        motion_type = hm.group("motion_type").strip()

        start = hm.start()
        end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(plain)
        # The slice [start:end] reaches into the whitespace before the next ruling
        # header. Trim trailing whitespace so page_end reflects where content really
        # ends, not where the next ruling begins.
        content_end = start + len(plain[start:end].rstrip())
        ruling_text = plain[start:end].strip()

        # Body = between the header line and TENTATIVE RULING #N marker.
        body = ruling_text
        body_end = ruling_text.find("TENTATIVE RULING #")
        if body_end >= 0:
            body = ruling_text[:body_end].strip()
            # Drop the two header lines themselves.
            body_lines = body.splitlines()[2:]
            body = "\n".join(body_lines).strip()

        disposition_text = dispositions.get(idx, ("", 0))[0]
        disposition_clean = REMOTE_BOILERPLATE_RE.sub("", disposition_text).strip()
        outcome, conditional, continued_to = _classify(disposition_text)

        page_start = page_for_offset(start)
        page_end = page_for_offset(max(start, content_end - 1))

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{idx}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=meta.dept,
                hearing_date=meta.hearing_date,
                ruling_index=idx,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=disposition_clean,
                conditional=conditional,
                continued_to=continued_to,
                body_text=body,
                full_text=ruling_text,
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.utcnow(),
            )
        )

    return rulings


def parse_file(path: str, source_url: str | None = None) -> list[Ruling]:
    """Convenience wrapper for tests and CLI use."""
    with open(path, "rb") as f:
        data = f.read()
    if source_url is None:
        source_url = f"file://{path}"
    return parse(data, source_url=source_url)

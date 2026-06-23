"""Parser implementations for newly captured county sources."""

from __future__ import annotations

import re
from datetime import date

from schema import Ruling

from .simple_parser import (
    clean_lines,
    extract_pdf_pages,
    find_date,
    html_to_text,
    inline,
    join_pages,
    make_ruling,
    page_for_offset,
    parse_date_value,
    source_sha,
)


def _pdf_text(pdf_bytes: bytes):
    pages = extract_pdf_pages(pdf_bytes)
    plain, offsets = join_pages(pages)
    return pages, plain, offsets


def _page_span(offsets: list[int], start: int, end: int) -> tuple[int, int]:
    page_start = page_for_offset(offsets, start)
    page_end = max(page_start, page_for_offset(offsets, max(start, end - 1)))
    return page_start, page_end


def _case_division(case_number: str, default: str | None = None) -> str | None:
    upper = case_number.upper()
    if "PR" in upper:
        return "Probate"
    if upper.startswith("FL") or "FL" in upper:
        return "Family Law"
    if "CV" in upper or "CU" in upper or "CLJ" in upper or "CIV" in upper:
        return "Civil Law and Motion"
    return default


def _first_body_line(lines: list[str]) -> int:
    body_re = re.compile(
        r"^(?:The Court|At the request|Pursuant|This matter|The petition|The Petition|"
        r"The First|Parties|Plaintiff|Defendant|Petitioner|Respondent|Based upon|"
        r"Good cause|No appearance|Appearance|Documents|All in order|Previous issues)",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if body_re.search(line):
            return i
    return min(2, len(lines))


def _line_window(lines: list[str], start: int, end: int | None = None) -> str:
    return clean_lines("\n".join(lines[start:end]))


def parse_ventura(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, _offsets = _pdf_text(pdf_bytes)
    if not plain:
        return []
    header = re.search(r"(?m)^(?P<num>[A-Z0-9]{5,30}):\s*(?P<title>.+?)\s*$", plain)
    date_dept = re.search(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+in\s+Department\s+(?P<dept>[A-Z0-9]+)", plain)
    if not header or not date_dept:
        return []
    hearing_date = parse_date_value(date_dept.group("date"))
    if not hearing_date:
        return []
    after_date = plain[date_dept.end() :].splitlines()
    motion = ""
    for line in after_date:
        line = inline(line)
        if line and not line.isdigit():
            motion = line
            break
    body_match = re.search(r"Tentative Ruling:\s*(?P<body>.*)", plain, re.IGNORECASE | re.DOTALL)
    if body_match:
        body = body_match.group("body")
    elif motion:
        body = plain[plain.find(motion) + len(motion) :]
    else:
        body = plain[date_dept.end() :]
    division = "Probate Notes" if "Probate Notes" in plain[:300] or "PR" in header.group("num") else "Civil Law and Motion"
    return [
        make_ruling(
            county="ventura",
            source_sha256=sha,
            source_url=source_url,
            parser_version="ventura-v1",
            style="ventura-one-ruling",
            index=1,
            case_number=header.group("num"),
            case_title=header.group("title"),
            hearing_date=hearing_date,
            full_text=plain,
            body_text=body,
            motion_type=motion,
            division=division_hint or division,
            dept=dept_hint or date_dept.group("dept"),
            page_start=1,
            page_end=max(1, len(pages)),
        )
    ]


def parse_monterey(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, _offsets = _pdf_text(pdf_bytes)
    case = re.search(r"\b\d{2}CV\d{6}\b", plain)
    date_match = re.search(r"Hearing Date:\s*([A-Za-z]+ \d{1,2},? \d{4})", plain, re.IGNORECASE)
    if not case or not date_match:
        return []
    hearing_date = parse_date_value(date_match.group(1))
    if not hearing_date:
        return []
    title_start = re.search(r"TENTATIVE RULING", plain, re.IGNORECASE)
    title_region = plain[(title_start.end() if title_start else 0) : case.start()]
    title_lines = [line for line in title_region.splitlines() if inline(line) and not inline(line).isdigit()]
    motion_region = plain[case.end() : date_match.start()]
    motion_lines = [
        line
        for line in motion_region.splitlines()
        if inline(line) and not re.search(r"consolidated|related cross", line, re.IGNORECASE)
    ]
    body = plain[date_match.end() :]
    return [
        make_ruling(
            county="monterey",
            source_sha256=sha,
            source_url=source_url,
            parser_version="monterey-v1",
            style="monterey-one-ruling",
            index=1,
            case_number=case.group(0),
            case_title=" ".join(title_lines) or case.group(0),
            hearing_date=hearing_date,
            full_text=plain,
            body_text=body,
            motion_type=" ".join(motion_lines),
            division=division_hint or "Tentative Rulings",
            dept=dept_hint,
            page_start=1,
            page_end=max(1, len(pages)),
        )
    ]


def parse_tulare_pdf(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:1200])
    dept = dept_hint
    dept_match = re.search(r"DEPARTMENT\s+([A-Z0-9]+)", plain[:800], re.IGNORECASE)
    if dept_match:
        dept = dept_match.group(1)
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?m)^\s*(?P<num>[VP]PR\d{6})\s+", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        lines = [inline(line) for line in block.splitlines() if inline(line)]
        if not lines:
            continue
        first = re.sub(rf"^{re.escape(anchor.group('num'))}\s*", "", lines[0]).strip()
        tail_lines = ([first] if first else []) + lines[1:]
        body_idx = _first_body_line(tail_lines)
        case_title = " ".join(tail_lines[:body_idx]) or anchor.group("num")
        body = _line_window(tail_lines, body_idx)
        motion = ""
        status_match = re.search(r"(Appearance Required|Recommended for Approval|Approval Conditional[^.\n]*)", block, re.IGNORECASE)
        if status_match:
            motion = inline(block[: status_match.start()].replace(anchor.group("num"), ""))
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="tulare",
                source_sha256=sha,
                source_url=source_url,
                parser_version="tulare-probate-v1",
                style="tulare-probate-table",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=case_title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=division_hint or "Probate",
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_tulare_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    start = text.find("Current Tentative Rulings")
    end = text.find("Probate Examiner Recommendations", start if start != -1 else 0)
    section = text[start : end if end != -1 else len(text)] if start != -1 else text
    hearing_date = find_date(section[:500])
    if not hearing_date:
        return []
    blocks = re.split(r"(?m)^\s*Re:\s*", section)
    rulings: list[Ruling] = []
    for block in blocks[1:]:
        next_case = re.search(
            r"(?is)(?P<title>.*?)\n\s*Case No\.:\s*(?P<num>[A-Za-z0-9-]+).*?"
            r"\n\s*Dept\.?\s*(?P<dept>[^\n]+).*?"
            r"\n\s*Motion:\s*(?P<motion>.*?)\n\s*Tentative Ruling:\s*(?P<body>.*)",
            block,
        )
        if not next_case:
            continue
        dept = inline(next_case.group("dept")).split("The Honorable", 1)[0].strip(" -")
        full = "Re: " + block
        rulings.append(
            make_ruling(
                county="tulare",
                source_sha256=sha,
                source_url=source_url,
                parser_version="tulare-civil-html-v1",
                style="tulare-civil-html",
                index=len(rulings) + 1,
                case_number=next_case.group("num"),
                case_title=next_case.group("title"),
                hearing_date=hearing_date,
                full_text=full,
                body_text=next_case.group("body"),
                motion_type=next_case.group("motion"),
                division="Civil Law and Motion",
                dept=dept or None,
            )
        )
    return rulings


def parse_santa_cruz(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:1000])
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?m)^\s*Nos?\.\s+(?P<num>[0-9A-Z,\s]+)\s*$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        lines = [inline(line) for line in block.splitlines() if inline(line)]
        if len(lines) < 3:
            continue
        case_title = lines[1]
        body_start = 2
        for j in range(2, min(len(lines), 8)):
            if lines[j].upper() != lines[j] or re.search(r"\b(is|are|shall|the|parties)\b", lines[j], re.IGNORECASE):
                body_start = j
                break
        motion = " ".join(lines[2:body_start])
        body = "\n".join(lines[body_start:])
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        case_number = inline(anchor.group("num")).replace(" ", "")
        rulings.append(
            make_ruling(
                county="santa-cruz",
                source_sha256=sha,
                source_url=source_url,
                parser_version="santa-cruz-v1",
                style="santa-cruz-law-motion",
                index=len(rulings) + 1,
                case_number=case_number,
                case_title=case_title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=division_hint or "Civil Law and Motion",
                dept=dept_hint,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_san_benito(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:1200])
    if not hearing_date:
        return []
    dept = dept_hint
    dept_match = re.search(r"Courtroom\s+#?(\d+)", plain, re.IGNORECASE)
    if dept_match:
        dept = dept_match.group(1)
    anchors = list(re.finditer(r"(?m)^(?P<num>(?:FL|CU|PR)-\d{2}-\d{5})\s+(?P<title>.+)$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        body = block[block.find(anchor.group("title")) + len(anchor.group("title")) :]
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="san-benito",
                source_sha256=sha,
                source_url=source_url,
                parser_version="san-benito-v1",
                style="san-benito-list",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                division=division_hint or _case_division(anchor.group("num")),
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_butte(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:800])
    if not hearing_date:
        return []
    if "Current Probate Tentative Rulings" in plain:
        normalized = re.sub(r"(\d{2}PR)\s+(\d{5})", r"\1\2", plain)
        normalized = re.sub(r"(?m)^9:\s*\n\s*00\s+", "9:00 ", normalized)
        anchors = list(re.finditer(r"(?m)^\s*\d{1,2}:\d{2}\s+(?P<num>\d{2}PR\d{5})\s+", normalized))
        rulings: list[Ruling] = []
        for i, anchor in enumerate(anchors):
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(normalized)
            block = clean_lines(normalized[anchor.start() : end])
            lines = [inline(line) for line in block.splitlines() if inline(line)]
            tail = re.sub(r"^\d{1,2}:\d{2}\s+\d{2}PR\d{5}\s*", "", lines[0]).strip() if lines else ""
            tail_lines = ([tail] if tail else []) + lines[1:]
            body_idx = _first_body_line(tail_lines)
            rulings.append(
                make_ruling(
                    county="butte",
                    source_sha256=sha,
                    source_url=source_url,
                    parser_version="butte-v1",
                    style="butte-probate-table",
                    index=len(rulings) + 1,
                    case_number=anchor.group("num"),
                    case_title=" ".join(tail_lines[:body_idx]) or anchor.group("num"),
                    hearing_date=hearing_date,
                    full_text=block,
                    body_text=_line_window(tail_lines, body_idx),
                    division=division_hint or "Probate",
                    dept=dept_hint,
                    page_start=1,
                    page_end=max(1, len(pages)),
                )
            )
        return rulings

    anchors = list(re.finditer(r"(?m)^\s*\d+(?:-\d+)?\.\s+(?P<num>\d{2}CV\d{5})\s+(?P<title>.+)$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        motion_match = re.search(r"EVENTS?:\s*(?P<motion>.*?)(?=\n[A-Z][a-z]|\nThe Court|\nAs an initial|\Z)", block, re.DOTALL)
        if motion_match:
            motion = motion_match.group("motion")
            body = block[motion_match.end() :]
        else:
            motion = ""
            body = block
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="butte",
                source_sha256=sha,
                source_url=source_url,
                parser_version="butte-v1",
                style="butte-civil-law-motion",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=division_hint or "Civil Law and Motion",
                dept=dept_hint,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_napa(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    date_match = re.search(r"FOR:\s*([A-Za-z]+ \d{1,2},? \d{4})", plain, re.IGNORECASE)
    hearing_date = parse_date_value(date_match.group(1)) if date_match else find_date(plain[:1000])
    if not hearing_date:
        return []
    case_re = re.compile(r"(?m)^(?P<title>.{3,160}?)\s+(?P<num>(?:\d{2}(?:PR|CV|FL)\d{6}|PR\d{5}))\s*$")
    anchors = list(case_re.finditer(plain))
    rulings: list[Ruling] = []
    current_division = division_hint or "Civil Law and Motion"
    current_dept = dept_hint
    for i, anchor in enumerate(anchors):
        prefix = plain[: anchor.start()]
        section_match = list(re.finditer(r"(?m)^([A-Z][A-Z &/]+CALENDAR).*?Dept\.\s*([A-Z0-9]+)", prefix))
        if section_match:
            section = section_match[-1]
            current_dept = section.group(2)
            current_division = "Probate" if "PROBATE" in section.group(1) else "Civil Law and Motion"
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        ruling_match = re.search(r"TENTATIVE RULING:\s*(?P<body>.*)", block, re.IGNORECASE | re.DOTALL)
        if not ruling_match:
            continue
        before = block[: ruling_match.start()]
        motion_lines = [line for line in before.splitlines()[1:] if inline(line)]
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="napa",
                source_sha256=sha,
                source_url=source_url,
                parser_version="napa-v1",
                style="napa-section-calendar",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=ruling_match.group("body"),
                motion_type=" ".join(motion_lines),
                division=current_division,
                dept=current_dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_san_luis_obispo(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    if not plain or "no tentative rulings" in plain.lower():
        return []
    civil = re.search(r"(?m)^(?P<title>.+?),\s*(?P<num>\d{2}(?:CV|LC)-\d{4})\s*$", plain[:1000])
    if civil:
        date_match = re.search(r"Date:\s*([A-Za-z]+ \d{1,2},? \d{4})", plain, re.IGNORECASE)
        hearing_date = parse_date_value(date_match.group(1)) if date_match else find_date(plain[:1000])
        if not hearing_date:
            return []
        motion_match = re.search(r"Hearing:\s*(?P<motion>.*?)(?:\n\s*\n|Date:)", plain, re.IGNORECASE | re.DOTALL)
        return [
            make_ruling(
                county="san-luis-obispo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="slo-v1",
                style="slo-civil-one-ruling",
                index=1,
                case_number=civil.group("num"),
                case_title=civil.group("title"),
                hearing_date=hearing_date,
                full_text=plain,
                body_text=plain[(date_match.end() if date_match else civil.end()) :],
                motion_type=motion_match.group("motion") if motion_match else "",
                division=division_hint or "Civil Law and Motion",
                dept=dept_hint,
                page_start=1,
                page_end=max(1, len(pages)),
            )
        ]

    hearing_date = find_date(plain[:1200])
    if not hearing_date:
        return []
    dept = dept_hint
    dept_match = re.search(r"in\s+Department\s+([A-Za-z0-9 ]+),", plain[:800], re.IGNORECASE)
    if dept_match:
        dept = inline(dept_match.group(1))
    anchors = list(re.finditer(r"(?m)^\s*(?:\d+\s+)?(?P<num>\d{2}PR-\d{4})\s+", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        lines = [inline(line) for line in block.splitlines() if inline(line)]
        tail = re.sub(r"^(?:\d+\s+)?\d{2}PR-\d{4}\s*", "", lines[0]).strip() if lines else ""
        tail_lines = ([tail] if tail else []) + lines[1:]
        body_idx = _first_body_line(tail_lines)
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="san-luis-obispo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="slo-v1",
                style="slo-probate-table",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=" ".join(tail_lines[:body_idx]) or anchor.group("num"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=_line_window(tail_lines, body_idx),
                division="Probate",
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_sierra(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, _offsets = _pdf_text(pdf_bytes)
    if not plain or "do not have any tentative rulings" in plain.lower():
        return []
    match = re.search(
        r"Tentative rulings for (?P<date>[A-Za-z]+ \d{1,2},? \d{4}) in (?P<title>.*?)\s+(?P<num>\d{2}CU\d{4})",
        plain,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    hearing_date = parse_date_value(match.group("date"))
    if not hearing_date:
        return []
    rest = plain[match.end() :]
    lines = [line for line in rest.splitlines() if inline(line)]
    motion = inline(lines[0]) if lines else ""
    body = "\n".join(lines[1:]) if len(lines) > 1 else rest
    return [
        make_ruling(
            county="sierra",
            source_sha256=sha,
            source_url=source_url,
            parser_version="sierra-v1",
            style="sierra-law-motion",
            index=1,
            case_number=match.group("num"),
            case_title=match.group("title"),
            hearing_date=hearing_date,
            full_text=plain,
            body_text=body,
            motion_type=motion,
            division=division_hint or "Law and Motion",
            dept=dept_hint,
            page_start=1,
            page_end=max(1, len(pages)),
        )
    ]


def parse_san_mateo(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = None
    date_match = re.search(r"Hearing Date:\s*([0-9/]+)", plain, re.IGNORECASE)
    if date_match:
        hearing_date = parse_date_value(date_match.group(1))
    if not hearing_date:
        hearing_date = find_date(plain[:1500])
    if not hearing_date:
        return []
    dept = dept_hint
    dept_match = re.search(r"Department\s+(\d+)", plain[:1500], re.IGNORECASE)
    if dept_match:
        dept = dept_match.group(1)
    anchors = list(re.finditer(r"(?m)^\s*(?P<num>\d{2}-(?:CIV|CLJ|PRO)-\d{5})\s*$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        ruling_match = re.search(r"TENTATIVE RULING:\s*(?P<body>.*)", block, re.IGNORECASE | re.DOTALL)
        if not ruling_match:
            continue
        before = [inline(line) for line in block[: ruling_match.start()].splitlines() if inline(line)]
        title = ""
        for line in before[1:]:
            if re.match(r"^(LINE \d+|\d{1,2}:\d{2}\s*[AP]M?)$", line, re.IGNORECASE):
                continue
            title = line
            break
        motion = " ".join(before[-3:]) if len(before) > 3 else ""
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="san-mateo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="san-mateo-v1",
                style="san-mateo-calendar",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=title or anchor.group("num"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=ruling_match.group("body"),
                motion_type=motion,
                division=division_hint or _case_division(anchor.group("num"), "Civil Law and Motion"),
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_los_angeles_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    parts = re.split(r"Case Number:\s*", text)
    rulings: list[Ruling] = []
    for part in parts[1:]:
        header = re.match(
            r"(?P<num>[A-Z0-9]+)\s+Hearing Date:\s*(?P<date>[A-Za-z]+ \d{1,2},? \d{4})\s+Dept:\s*(?P<dept>[A-Z0-9]+)",
            inline(part[:250]),
            re.IGNORECASE,
        )
        if not header:
            continue
        hearing_date = parse_date_value(header.group("date"))
        if not hearing_date:
            continue
        block = "Case Number: " + part
        title = header.group("num")
        caption = re.search(
            r"(?is)\n\s*(?P<p>[^.\n]{2,120}?)\s*,?\s+Plaintiff\(s\).*?vs\.\s*(?P<d>[^.\n]{2,120}?)\s*,?\s+Defendant",
            block,
        )
        if caption:
            title = f"{inline(caption.group('p'))} v. {inline(caption.group('d'))}"
        motion = ""
        motion_match = re.search(r"ORDER RE:\s*(?P<motion>.*?)(?:\n\s*Dept\.|\n\s*Dept\s)", block, re.IGNORECASE | re.DOTALL)
        if motion_match:
            motion = motion_match.group("motion")
        body = block
        intro = re.search(r"\n\s*(?:I\.|INTRODUCTION|Introduction|Background|Discussion)\b", block, re.IGNORECASE)
        if intro:
            body = block[intro.start() :]
        rulings.append(
            make_ruling(
                county="los-angeles",
                source_sha256=sha,
                source_url=source_url,
                parser_version="los-angeles-html-v1",
                style="la-webforms-result",
                index=len(rulings) + 1,
                case_number=header.group("num"),
                case_title=title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division="Civil Law and Motion",
                dept=header.group("dept"),
            )
        )
    return rulings


def parse_stanislaus_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    hearing_date = find_date(text)
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?m)^(?P<num>(?:CV|FL|PR|UD)-\d{2}-\d{6})\s+[-–]\s+(?P<title>.+)$", text))
    rulings: list[Ruling] = []
    current_dept = None
    for i, anchor in enumerate(anchors):
        prefix = text[: anchor.start()]
        dept_matches = list(re.finditer(r"Department\s+#?\s*(\d+)|Department\s+(\d+)", prefix, re.IGNORECASE))
        if dept_matches:
            current_dept = next(g for g in dept_matches[-1].groups() if g)
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = clean_lines(text[anchor.start() : end])
        after_title = block[block.find(anchor.group("title")) + len(anchor.group("title")) :]
        motion, _, body = after_title.partition(" - ")
        if not body:
            body = after_title
        rulings.append(
            make_ruling(
                county="stanislaus",
                source_sha256=sha,
                source_url=source_url,
                parser_version="stanislaus-html-v1",
                style="stanislaus-html",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=_case_division(anchor.group("num")),
                dept=current_dept,
            )
        )
    return rulings

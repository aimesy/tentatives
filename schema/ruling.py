"""Shared schema for cross-county tentative-ruling records.

Two record types:
  - Capture: one row per (PDF content, fetch event). Lives in archive/<county>/manifest.parquet.
  - Ruling:  one row per (case × motion) extracted from a PDF. Lives in data/<county>/rulings.parquet.

A Ruling references its source PDF by sha256, not by URL: the same content captured
from the live site and from N Wayback timestamps is one PDF in storage, N rows in
manifest, and the rulings parse once.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any


OUTCOME_CHOICES = (
    "granted",
    "denied",
    "continued",
    "appearance_required",
    "off_calendar",
    "other",
)


@dataclass(frozen=True)
class Capture:
    """One capture of a PDF. Multiple captures can share a source_sha256."""

    source_sha256: str
    source_url: str
    discovered_filename: str
    fetched_at: datetime
    wayback_ts: str | None = None
    content_length: int | None = None

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["fetched_at"] = self.fetched_at.isoformat()
        return d


@dataclass(frozen=True)
class Ruling:
    """One ruling extracted from a PDF. Stable across re-parses via ruling_id.

    `dept` and `division` are Optional because some PDF styles don't carry the
    dept in the header (callers can supply via dept_hint from the discovery URL).
    """

    ruling_id: str          # sha256(source_sha256 + ruling_index)
    county: str             # e.g. "el-dorado"
    division: str | None    # "Probate", "Law and Motion", "Civil", "Family Law", ...
    dept: str | None        # e.g. "9", "12"
    hearing_date: date
    ruling_index: int       # 1-based position within the PDF
    case_number: str        # e.g. "25PR0206", "SFL20210053"
    case_title: str         # e.g. "MATTER OF ANDRESEN TRUST"
    motion_type: str        # e.g. "Discovery Motions & Motion for Relief". May be empty.
    outcome: str            # one of OUTCOME_CHOICES (primary disposition)
    outcome_text: str       # raw disposition text (verbatim, may be multi-line)
    conditional: bool       # True for "ABSENT OBJECTION ... GRANTED"
    continued_to: date | None  # if outcome == "continued"
    body_text: str          # narrative between header and TENTATIVE RULING line
    full_text: str          # entire per-ruling text, page headers stripped
    page_start: int         # 1-based page in source PDF
    page_end: int
    source_sha256: str      # FK → Capture.source_sha256
    source_url: str         # canonical court URL of the source PDF
    style: str = ""         # e.g. "probate-dept-header", "lawandmotion-calendar"
    parser_version: str = "el-dorado-v2"
    ingest_ts: datetime = field(default_factory=datetime.utcnow)

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["hearing_date"] = self.hearing_date.isoformat()
        d["continued_to"] = self.continued_to.isoformat() if self.continued_to else None
        d["ingest_ts"] = self.ingest_ts.isoformat()
        return d

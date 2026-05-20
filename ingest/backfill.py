"""Fetch live or Wayback tentative-ruling PDFs into archive/.

This is the local companion to the browser extension. The extension is best
for forward capture from a browser tab. This module is for historical backfill:
discover PDF URLs from configured county pages, query Wayback CDX, fetch raw
captures, store content-addressed PDFs, and append capture provenance rows.

Examples:

    python -m ingest.backfill --county amador --live --dry-run
    python -m ingest.backfill --county amador --wayback --from-year 2020 --to-year 2022
    python -m ingest.backfill --county orange --live --wayback --limit 25
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
import requests

from counties.common import PdfRef, filename_from_url, unique_refs
from schema import Capture

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"
CDX_ENDPOINT = "https://web.archive.org/cdx"
AVAILABILITY_ENDPOINT = "https://archive.org/wayback/available"

COUNTY_MODULES = {
    "amador": "counties.amador.scraper",
    "calaveras": "counties.calaveras.scraper",
    "fresno": "counties.fresno.scraper",
    "merced": "counties.merced.scraper",
    "nevada": "counties.nevada.scraper",
    "orange": "counties.orange.scraper",
    "plumas": "counties.plumas.scraper",
    "riverside": "counties.riverside.scraper",
    "san-bernardino": "counties.san_bernardino.scraper",
    "san-francisco": "counties.san_francisco.scraper",
    "santa-clara": "counties.santa_clara.scraper",
    "shasta": "counties.shasta.scraper",
    "solano": "counties.solano.scraper",
    "tuolumne": "counties.tuolumne.scraper",
}


def _county_module(county: str):
    try:
        return importlib.import_module(COUNTY_MODULES[county])
    except KeyError:
        supported = ", ".join(sorted(COUNTY_MODULES))
        raise SystemExit(f"no discovery module for county={county!r}; supported: {supported}")


def _capture_path(county: str) -> Path:
    return ARCHIVE / county / "captures.ndjson"


def _existing_capture_keys(county: str) -> set[tuple[str, str, str | None]]:
    path = _capture_path(county)
    if not path.exists():
        return set()
    keys: set[tuple[str, str, str | None]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        sha = row.get("source_sha256")
        url = row.get("source_url")
        if sha and url:
            keys.add((sha, url, row.get("wayback_ts")))
    return keys


def _append_capture(county: str, ref: PdfRef, sha: str, content_length: int, dry_run: bool) -> None:
    row = Capture(
        source_sha256=sha,
        source_url=ref.url,
        discovered_filename=ref.filename,
        fetched_at=datetime.utcnow(),
        wayback_ts=ref.wayback_ts,
        content_length=content_length,
        dept_hint=ref.dept_hint,
        division_hint=ref.division_hint,
        source_page_url=ref.source_page_url,
    ).to_row()
    if dry_run:
        print(f"  would log capture {ref.filename} sha={sha[:12]} wayback={ref.wayback_ts or '-'}")
        return
    path = _capture_path(county)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _replay_url(ref: PdfRef) -> str:
    if not ref.wayback_ts:
        return ref.url
    return f"https://web.archive.org/web/{ref.wayback_ts}id_/{ref.url}"


def _wayback_timestamp(from_year: int | None, to_year: int | None) -> str | None:
    if to_year:
        return f"{to_year}1231235959"
    if from_year:
        return f"{from_year}0101000000"
    return None


def _ref_from_available(
    ref: PdfRef,
    *,
    session: requests.Session,
    timestamp: str | None = None,
) -> PdfRef | None:
    params = {"url": ref.url}
    if timestamp:
        params["timestamp"] = timestamp
    r = session.get(AVAILABILITY_ENDPOINT, params=params, timeout=60)
    if r.status_code == 429:
        print(f"  Wayback availability rate-limited for {ref.url}", file=sys.stderr)
        return None
    r.raise_for_status()
    closest = r.json().get("archived_snapshots", {}).get("closest")
    if not closest or not closest.get("available") or closest.get("status") != "200":
        return None
    return PdfRef(
        url=ref.url,
        filename=ref.filename,
        wayback_ts=closest.get("timestamp") or None,
        dept_hint=ref.dept_hint,
        division_hint=ref.division_hint,
        link_text=ref.link_text,
        source_page_url=ref.source_page_url,
    )


def fetch_ref(ref: PdfRef, session: requests.Session) -> tuple[bytes, str]:
    r = session.get(_replay_url(ref), timeout=90)
    r.raise_for_status()
    content = r.content
    return content, hashlib.sha256(content).hexdigest()


def archive_ref(county: str, ref: PdfRef, session: requests.Session, dry_run: bool = False) -> str:
    content, sha = fetch_ref(ref, session)
    archive_path = ARCHIVE / county / sha[:2] / f"{sha}.pdf"
    if dry_run:
        print(f"  would store {ref.filename} -> {archive_path.relative_to(REPO)}")
    else:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not archive_path.exists():
            archive_path.write_bytes(content)
    return sha


def discover_live_refs(county: str, session: requests.Session) -> list[PdfRef]:
    module = _county_module(county)
    refs: list[PdfRef] = []
    for url in getattr(module, "LANDING_PAGES", []):
        r = session.get(url, timeout=60)
        r.raise_for_status()
        refs.extend(module.discover_live(r.text, page_url=url))
    return unique_refs(refs)


def _cdx_rows(
    url_pattern: str,
    *,
    from_year: int | None,
    to_year: int | None,
    match_type: str | None,
    session: requests.Session,
) -> list[dict[str, str]]:
    params: dict[str, str | list[str]] = {
        "url": url_pattern,
        "output": "json",
        "fl": "timestamp,original,mimetype,statuscode,digest,length",
        "filter": ["statuscode:200"],
        "collapse": "digest",
    }
    if from_year:
        params["from"] = str(from_year)
    if to_year:
        params["to"] = str(to_year)
    if match_type:
        params["matchType"] = match_type
    r = session.get(CDX_ENDPOINT, params=params, timeout=90)
    r.raise_for_status()
    data = r.json()
    if not data:
        return []
    header = data[0]
    return [dict(zip(header, row)) for row in data[1:]]


def _source_url_year(ref: PdfRef) -> int | None:
    path = urlparse(ref.url).path
    for part in path.split("/"):
        if re.fullmatch(r"(?:19|20)\d{2}", part):
            return int(part)
    return None


def _filter_source_url_years(
    refs: list[PdfRef],
    *,
    from_year: int | None,
    to_year: int | None,
) -> list[PdfRef]:
    if from_year is None and to_year is None:
        return refs
    out: list[PdfRef] = []
    for ref in refs:
        year = _source_url_year(ref)
        if year is None:
            out.append(ref)
            continue
        if from_year is not None and year < from_year:
            continue
        if to_year is not None and year > to_year:
            continue
        out.append(ref)
    return out


def discover_wayback_refs(
    county: str,
    session: requests.Session,
    *,
    from_year: int | None = None,
    to_year: int | None = None,
    live_refs: Iterable[PdfRef] = (),
) -> list[PdfRef]:
    module = _county_module(county)
    refs: list[PdfRef] = []

    for pattern in getattr(module, "WAYBACK_PDF_PATTERNS", []):
        # CDX treats '*' in the url parameter as a wildcard. Passing
        # matchType=prefix here looks tempting but misses captures on some
        # hosts, including Amador's tentativeRulings tree.
        for row in _cdx_rows(
            pattern,
            from_year=from_year,
            to_year=to_year,
            match_type=None,
            session=session,
        ):
            original = row.get("original", "")
            if not original.lower().split("?", 1)[0].endswith(".pdf"):
                continue
            ref_from_wayback_url = getattr(module, "ref_from_wayback_url", None)
            if ref_from_wayback_url:
                refs.append(
                    ref_from_wayback_url(
                        original,
                        wayback_ts=row.get("timestamp") or None,
                    )
                )
            else:
                refs.append(
                    PdfRef(
                        url=original,
                        filename=filename_from_url(original),
                        wayback_ts=row.get("timestamp") or None,
                    )
                )

    # Counties with stable "current" PDF URLs, especially Orange, need exact
    # CDX queries for each live URL to recover prior contents.
    for live_ref in live_refs:
        rows = _cdx_rows(
            live_ref.url,
            from_year=from_year,
            to_year=to_year,
            match_type=None,
            session=session,
        )
        if not rows:
            available = _ref_from_available(
                live_ref,
                session=session,
                timestamp=_wayback_timestamp(from_year, to_year),
            )
            if available:
                refs.append(available)
            continue
        for row in rows:
            original = row.get("original") or live_ref.url
            refs.append(
                PdfRef(
                    url=original,
                    filename=live_ref.filename,
                    wayback_ts=row.get("timestamp") or None,
                    dept_hint=live_ref.dept_hint,
                    division_hint=live_ref.division_hint,
                    link_text=live_ref.link_text,
                    source_page_url=live_ref.source_page_url,
                )
            )
    return unique_refs(refs)


def _limit(refs: list[PdfRef], limit: int | None) -> list[PdfRef]:
    return refs[:limit] if limit is not None else refs


def _wayback_needs_live_refs(county: str) -> bool:
    module = _county_module(county)
    return not bool(getattr(module, "WAYBACK_PDF_PATTERNS", []))


def run(args: argparse.Namespace) -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "aimesy-tentatives/1.0"})

    do_live = args.live or not args.wayback
    needs_live_for_wayback = args.wayback and _wayback_needs_live_refs(args.county)
    live_refs: list[PdfRef] = (
        discover_live_refs(args.county, session) if do_live or needs_live_for_wayback else []
    )
    refs: list[PdfRef] = []
    if args.live:
        refs.extend(live_refs)
    if args.wayback:
        wayback_live_refs = live_refs
        if needs_live_for_wayback and args.limit is not None:
            wayback_live_refs = _limit(live_refs, args.limit)
        refs.extend(
            discover_wayback_refs(
                args.county,
                session,
                from_year=args.from_year,
                to_year=args.to_year,
                live_refs=wayback_live_refs,
            )
        )
    if not args.live and not args.wayback:
        refs = live_refs

    refs = _filter_source_url_years(
        unique_refs(refs),
        from_year=args.url_from_year,
        to_year=args.url_to_year,
    )
    refs = _limit(refs, args.limit)
    print(f"{args.county}: {len(refs)} refs")
    existing = _existing_capture_keys(args.county)
    wrote = 0
    for ref in refs:
        try:
            content, sha = fetch_ref(ref, session)
        except Exception as e:
            print(f"  ERROR fetch {ref.url} wayback={ref.wayback_ts or '-'}: {e}", file=sys.stderr)
            continue
        archive_path = ARCHIVE / args.county / sha[:2] / f"{sha}.pdf"
        key = (sha, ref.url, ref.wayback_ts)
        if args.dry_run:
            print(f"  would store {ref.filename} sha={sha[:12]} from {ref.url}")
            continue
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not archive_path.exists():
            archive_path.write_bytes(content)
        if key not in existing:
            _append_capture(args.county, ref, sha, len(content), dry_run=False)
            existing.add(key)
        wrote += 1
    print(f"{args.county}: archived/logged {wrote} refs")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--county", required=True, choices=sorted(COUNTY_MODULES))
    parser.add_argument("--live", action="store_true", help="Fetch PDFs from configured live landing pages")
    parser.add_argument("--wayback", action="store_true", help="Fetch matching Wayback PDF captures")
    parser.add_argument("--from-year", type=int, help="First Wayback capture year, e.g. 2020")
    parser.add_argument("--to-year", type=int, help="Last Wayback capture year, e.g. 2022")
    parser.add_argument("--url-from-year", type=int, help="First year embedded in the source PDF URL")
    parser.add_argument("--url-to-year", type=int, help="Last year embedded in the source PDF URL")
    parser.add_argument("--limit", type=int, help="Maximum refs to fetch after discovery")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

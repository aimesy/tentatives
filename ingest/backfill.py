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
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
import requests

from counties.common import PdfRef, filename_from_url, unique_refs
from counties.registry import discovery_modules
from schema import Capture

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"
CDX_ENDPOINT = "https://web.archive.org/cdx"
AVAILABILITY_ENDPOINT = "https://archive.org/wayback/available"
MAX_PDF_BYTES = 50 * 1024 * 1024
PDF_MAGIC = b"%PDF-"
REDIRECT_LIMIT = 5

COUNTY_MODULES = discovery_modules()


def _county_module(county: str):
    try:
        return COUNTY_MODULES[county]
    except KeyError:
        supported = ", ".join(sorted(COUNTY_MODULES))
        raise ValueError(f"no discovery module for county={county!r}; supported: {supported}") from None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _record_failure(errors: list[str] | None, message: str) -> None:
    print(message, file=sys.stderr)
    if errors is not None:
        errors.append(message)


def _host_matches(host: str, allowed_host: str) -> bool:
    host = host.lower().rstrip(".")
    allowed_host = allowed_host.lower().rstrip(".")
    return host == allowed_host or host.endswith(f".{allowed_host}")


def _allowed_hosts_for_county(county: str) -> set[str]:
    module = _county_module(county)
    hosts: set[str] = set()
    for attr in ("LANDING_PAGES", "WAYBACK_PDF_PATTERNS"):
        for raw in getattr(module, attr, []):
            candidate = str(raw).replace("*", "")
            parsed = urlparse(candidate)
            if not parsed.hostname and "://" not in candidate:
                parsed = urlparse(f"https://{candidate.lstrip('/')}")
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    return hosts


def _validate_source_host(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"unsupported source URL: {url}")
    if parsed.username or parsed.password:
        raise ValueError(f"credentials are not allowed in source URL: {url}")
    if allowed_hosts and not any(_host_matches(parsed.hostname, h) for h in allowed_hosts):
        allowed = ", ".join(sorted(allowed_hosts))
        raise ValueError(f"source host {parsed.hostname!r} is not in county allowlist ({allowed})")


def _validate_fetch_host(
    fetch_url: str,
    source_url: str,
    allowed_hosts: set[str],
    *,
    wayback: bool = False,
) -> None:
    parsed = urlparse(fetch_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"unsupported fetch URL: {fetch_url}")
    if parsed.username or parsed.password:
        raise ValueError(f"credentials are not allowed in fetch URL: {fetch_url}")
    fetch_host = parsed.hostname.lower().rstrip(".")
    if wayback:
        if fetch_host != "web.archive.org":
            raise ValueError(f"Wayback replay host is not allowlisted: {parsed.hostname}")
        return
    _validate_source_host(fetch_url, allowed_hosts)
    _validate_source_host(source_url, allowed_hosts)


def _content_type_is_pdfish(value: str) -> bool:
    ctype = value.split(";", 1)[0].strip().lower()
    return ctype in {
        "",
        "application/pdf",
        "application/x-pdf",
        "application/force-download",
        "application/octet-stream",
        "binary/octet-stream",
    }


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
        fetched_at=utc_now(),
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
    errors: list[str] | None = None,
) -> PdfRef | None:
    params = {"url": ref.url}
    if timestamp:
        params["timestamp"] = timestamp
    try:
        r = session.get(AVAILABILITY_ENDPOINT, params=params, timeout=60)
    except requests.RequestException as e:
        _record_failure(errors, f"  ERROR Wayback availability fetch for {ref.url}: {e}")
        return None
    if r.status_code == 429:
        _record_failure(errors, f"  Wayback availability rate-limited for {ref.url}")
        return None
    try:
        r.raise_for_status()
    except requests.RequestException as e:
        _record_failure(errors, f"  ERROR Wayback availability status for {ref.url}: {e}")
        return None
    try:
        payload = r.json()
    except ValueError as e:
        _record_failure(errors, f"  Wayback availability returned non-JSON for {ref.url}: {e}")
        return None
    if not isinstance(payload, dict):
        _record_failure(errors, f"  Wayback availability returned unexpected JSON for {ref.url}")
        return None
    snapshots = payload.get("archived_snapshots")
    if not isinstance(snapshots, dict):
        return None
    closest = snapshots.get("closest")
    if not isinstance(closest, dict):
        return None
    available = closest.get("available")
    if available is not True and str(available).lower() != "true":
        return None
    if str(closest.get("status")) != "200":
        return None
    closest_url = closest.get("url")
    if closest_url:
        closest_host = urlparse(str(closest_url)).hostname
        if closest_host and closest_host.lower() != "web.archive.org":
            _record_failure(
                errors,
                f"  Wayback availability returned non-allowlisted host for {ref.url}: {closest_host}",
            )
            return None
    wayback_ts = closest.get("timestamp") or None
    if wayback_ts and not re.fullmatch(r"\d{14}", str(wayback_ts)):
        _record_failure(errors, f"  Wayback availability returned invalid timestamp for {ref.url}: {wayback_ts}")
        return None
    return PdfRef(
        url=ref.url,
        filename=ref.filename,
        wayback_ts=str(wayback_ts) if wayback_ts else None,
        dept_hint=ref.dept_hint,
        division_hint=ref.division_hint,
        link_text=ref.link_text,
        source_page_url=ref.source_page_url,
    )


def fetch_ref(
    ref: PdfRef,
    session: requests.Session,
    *,
    allowed_hosts: set[str] | None = None,
    max_bytes: int = MAX_PDF_BYTES,
) -> tuple[bytes, str]:
    allowed = allowed_hosts or set()
    _validate_source_host(ref.url, allowed)
    fetch_url = _replay_url(ref)
    for _ in range(REDIRECT_LIMIT + 1):
        _validate_fetch_host(fetch_url, ref.url, allowed, wayback=bool(ref.wayback_ts))
        r = session.get(fetch_url, timeout=90, stream=True, allow_redirects=False)
        if 300 <= r.status_code < 400 and r.headers.get("Location"):
            fetch_url = urljoin(fetch_url, r.headers["Location"])
            continue
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if not _content_type_is_pdfish(ctype):
            raise ValueError(f"unexpected content type for {ref.url}: {ctype}")
        content = _read_limited_pdf(r, max_bytes=max_bytes, source_url=ref.url)
        break
    else:
        raise ValueError(f"too many redirects for {ref.url}")
    return content, hashlib.sha256(content).hexdigest()


def _read_limited_pdf(
    response: requests.Response,
    *,
    max_bytes: int,
    source_url: str,
) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError(f"PDF too large for {source_url}: {content_length} bytes")
        except ValueError:
            if content_length.isdigit():
                raise
    chunks: list[bytes] = []
    total = 0
    first = b""
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        if not first:
            first = chunk[:1024]
            if len(first) >= len(PDF_MAGIC) and not _looks_like_pdf(first):
                raise ValueError(f"response is not a PDF for {source_url}")
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"PDF too large for {source_url}: >{max_bytes} bytes")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not _looks_like_pdf(content):
        raise ValueError(f"response is not a PDF for {source_url}")
    return content


def _looks_like_pdf(content: bytes) -> bool:
    sample = content[:1024]
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    return sample.lstrip().startswith(PDF_MAGIC)


def discover_live_refs(
    county: str,
    session: requests.Session,
    *,
    continue_on_error: bool = False,
    errors: list[str] | None = None,
) -> list[PdfRef]:
    module = _county_module(county)
    refs: list[PdfRef] = []
    for url in getattr(module, "LANDING_PAGES", []):
        try:
            r = session.get(url, timeout=60)
            r.raise_for_status()
            refs.extend(module.discover_live(r.text, page_url=url))
        except Exception as e:
            _record_failure(errors, f"  ERROR discover landing {url}: {e}")
            if not continue_on_error:
                raise
    return unique_refs(refs)


def _cdx_rows(
    url_pattern: str,
    *,
    from_year: int | None,
    to_year: int | None,
    match_type: str | None,
    session: requests.Session,
    errors: list[str] | None = None,
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
    try:
        r = session.get(CDX_ENDPOINT, params=params, timeout=90)
    except requests.RequestException as e:
        _record_failure(errors, f"  ERROR Wayback CDX fetch for {url_pattern}: {e}")
        return []
    if r.status_code == 429:
        _record_failure(errors, f"  Wayback CDX rate-limited for {url_pattern}")
        return []
    try:
        r.raise_for_status()
    except requests.RequestException as e:
        _record_failure(errors, f"  ERROR Wayback CDX status for {url_pattern}: {e}")
        return []
    try:
        data = r.json()
    except ValueError as e:
        _record_failure(errors, f"  Wayback CDX returned non-JSON for {url_pattern}: {e}")
        return []
    if not data:
        return []
    if not isinstance(data, list) or not isinstance(data[0], list):
        _record_failure(errors, f"  Wayback CDX returned unexpected JSON for {url_pattern}")
        return []
    header = data[0]
    rows: list[dict[str, str]] = []
    for row in data[1:]:
        if not isinstance(row, list):
            continue
        rows.append(
            {
                str(key): "" if value is None else str(value)
                for key, value in zip(header, row, strict=False)
            }
        )
    return rows


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
    errors: list[str] | None = None,
) -> list[PdfRef]:
    module = _county_module(county)
    allowed_hosts = _allowed_hosts_for_county(county)
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
            errors=errors,
        ):
            original = row.get("original", "")
            try:
                _validate_source_host(original, allowed_hosts)
            except ValueError as e:
                print(f"  WARN skipping CDX row outside allowlist: {e}", file=sys.stderr)
                continue
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
            errors=errors,
        )
        if not rows:
            available = _ref_from_available(
                live_ref,
                session=session,
                timestamp=_wayback_timestamp(from_year, to_year),
                errors=errors,
            )
            if available:
                refs.append(available)
            continue
        for row in rows:
            original = row.get("original") or live_ref.url
            try:
                _validate_source_host(original, allowed_hosts)
            except ValueError as e:
                print(f"  WARN skipping CDX row outside allowlist: {e}", file=sys.stderr)
                continue
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


def _run_county(args: argparse.Namespace, county: str, session: requests.Session) -> int:
    failures: list[str] = []
    allowed_hosts = _allowed_hosts_for_county(county)
    do_live = args.live or not args.wayback
    needs_live_for_wayback = args.wayback and _wayback_needs_live_refs(county)
    try:
        live_refs: list[PdfRef] = (
            discover_live_refs(
                county,
                session,
                continue_on_error=args.continue_on_error,
                errors=failures,
            ) if do_live or needs_live_for_wayback else []
        )
    except Exception as e:
        _record_failure(failures, f"  ERROR live discovery for {county}: {e}")
        if not args.continue_on_error:
            raise
        live_refs = []
    refs: list[PdfRef] = []
    if args.live:
        refs.extend(live_refs)
    if args.wayback:
        wayback_live_refs = live_refs
        if needs_live_for_wayback and args.limit is not None:
            wayback_live_refs = _limit(live_refs, args.limit)
        try:
            refs.extend(
                discover_wayback_refs(
                    county,
                    session,
                    from_year=args.from_year,
                    to_year=args.to_year,
                    live_refs=wayback_live_refs,
                    errors=failures,
                )
            )
        except Exception as e:
            _record_failure(failures, f"  ERROR Wayback discovery for {county}: {e}")
            if not args.continue_on_error:
                raise
    if not args.live and not args.wayback:
        refs = live_refs

    refs = _filter_source_url_years(
        unique_refs(refs),
        from_year=args.url_from_year,
        to_year=args.url_to_year,
    )
    refs = _limit(refs, args.limit)
    print(f"{county}: {len(refs)} refs")
    existing = _existing_capture_keys(county)
    wrote = 0
    for ref in refs:
        try:
            content, sha = fetch_ref(ref, session, allowed_hosts=allowed_hosts)
        except Exception as e:
            _record_failure(
                failures,
                f"  ERROR fetch {ref.url} wayback={ref.wayback_ts or '-'}: {e}",
            )
            continue
        archive_path = ARCHIVE / county / sha[:2] / f"{sha}.pdf"
        key = (sha, ref.url, ref.wayback_ts)
        if args.dry_run:
            print(f"  would store {ref.filename} sha={sha[:12]} from {ref.url}")
            continue
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not archive_path.exists():
            archive_path.write_bytes(content)
        if key not in existing:
            _append_capture(county, ref, sha, len(content), dry_run=False)
            existing.add(key)
        wrote += 1
    print(f"{county}: archived/logged {wrote} refs")
    if failures:
        print(f"{county}: {len(failures)} failures", file=sys.stderr)
    return 1 if failures else 0


def run(args: argparse.Namespace) -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "aimesy-tentatives/1.0"})

    counties = sorted(COUNTY_MODULES) if args.county == "all" else [args.county]
    status = 0
    for county in counties:
        try:
            status |= _run_county(args, county, session)
        except Exception as e:
            print(f"{county}: ERROR {e}", file=sys.stderr)
            status = 1
            if not args.continue_on_error:
                break
    if args.continue_on_error:
        # With continue-on-error, per-county failures are logged but the
        # process exits clean; the calling workflow grep-checks the log to
        # decide whether enough refs landed to call the run a success.
        # Without this swallow, a single 503 from one of 16 county sites
        # fails the whole daily job (and trips set -o pipefail in the
        # workflow shell) — even when 15 other counties produced data.
        return 0
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--county", required=True, choices=["all", *sorted(COUNTY_MODULES)])
    parser.add_argument("--live", action="store_true", help="Fetch PDFs from configured live landing pages")
    parser.add_argument("--wayback", action="store_true", help="Fetch matching Wayback PDF captures")
    parser.add_argument("--from-year", type=int, help="First Wayback capture year, e.g. 2020")
    parser.add_argument("--to-year", type=int, help="Last Wayback capture year, e.g. 2022")
    parser.add_argument("--url-from-year", type=int, help="First year embedded in the source PDF URL")
    parser.add_argument("--url-to-year", type=int, help="Last year embedded in the source PDF URL")
    parser.add_argument("--limit", type=int, help="Maximum refs to fetch after discovery")
    parser.add_argument("--continue-on-error", action="store_true", help="Keep processing remaining counties after a county-level failure")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

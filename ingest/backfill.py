"""Fetch live or Wayback tentative-ruling source files into archive/.

This is the local companion to the browser extension. The extension is best
for forward capture from a browser tab. This module is for historical backfill:
discover source-file URLs from configured county pages, query Wayback CDX,
fetch raw captures, store content-addressed files, and append capture
provenance rows.

Examples:

    python -m ingest.backfill --county amador --live --dry-run
    python -m ingest.backfill --county amador --wayback --from-year 2020 --to-year 2022
    python -m ingest.backfill --county orange --live --wayback --limit 25
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse
import requests
import urllib3

from counties.common import PageRef, PdfRef, filename_from_url, unique_refs
from counties.registry import discovery_modules
from schema import Capture

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"
CDX_ENDPOINT = "https://web.archive.org/cdx"
AVAILABILITY_ENDPOINT = "https://archive.org/wayback/available"
READER_ENDPOINT_PREFIX = "https://r.jina.ai/"
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_SOURCE_BYTES = MAX_PDF_BYTES
MAX_PAGE_BYTES = 10 * 1024 * 1024
PDF_MAGIC = b"%PDF-"
DOCX_MAGIC_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
REDIRECT_LIMIT = 5
SUPPORTED_SOURCE_EXTENSIONS = {".pdf", ".docx"}

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


def _reader_landing_url(url: str) -> str:
    return f"{READER_ENDPOINT_PREFIX}{url}"


def _host_matches(host: str, allowed_host: str) -> bool:
    host = host.lower().rstrip(".")
    allowed_host = allowed_host.lower().rstrip(".")
    return host == allowed_host or host.endswith(f".{allowed_host}")


def _allowed_hosts_for_county(county: str) -> set[str]:
    module = _county_module(county)
    hosts: set[str] = set()
    hosts.update(str(host).lower() for host in getattr(module, "ALLOWED_SOURCE_HOSTS", set()))
    for attr in ("LANDING_PAGES", "WAYBACK_PDF_PATTERNS"):
        for raw in getattr(module, attr, []):
            candidate = str(raw).replace("*", "")
            parsed = urlparse(candidate)
            if not parsed.hostname and "://" not in candidate:
                parsed = urlparse(f"https://{candidate.lstrip('/')}")
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    return hosts


def _verify_tls_for_county(county: str) -> bool:
    module = _county_module(county)
    return bool(getattr(module, "VERIFY_TLS", True))


def _routine_live_enabled(county: str) -> bool:
    module = _county_module(county)
    return bool(getattr(module, "ROUTINE_LIVE", True))


def _routine_live_disabled_reason(county: str) -> str:
    module = _county_module(county)
    return str(getattr(module, "ROUTINE_LIVE_DISABLED_REASON", "routine live discovery disabled"))


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


def _content_type_is_docxish(value: str) -> bool:
    ctype = value.split(";", 1)[0].strip().lower()
    return ctype in {
        "",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
        "application/zip",
        "binary/octet-stream",
    }


def _content_type_is_htmlish(value: str) -> bool:
    ctype = value.split(";", 1)[0].strip().lower()
    return ctype in {
        "",
        "text/html",
        "application/xhtml+xml",
    }


def _content_type_is_jsonish(value: str) -> bool:
    ctype = value.split(";", 1)[0].strip().lower()
    return ctype == "application/json"


def _source_extension(ref: PdfRef) -> str:
    for candidate in (ref.filename, unquote(urlparse(ref.url).path)):
        suffix = Path(candidate).suffix.lower()
        if suffix:
            if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
                raise ValueError(f"unsupported source file extension for {ref.url}: {suffix}")
            return suffix
    raise ValueError(f"source URL has no supported file extension: {ref.url}")


def _url_has_supported_source_extension(url: str) -> bool:
    return Path(unquote(urlparse(url).path)).suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS


def _source_format(ref: PdfRef) -> str:
    return _source_extension(ref).lstrip(".")


def _content_type_matches_source(value: str, extension: str) -> bool:
    if extension == ".pdf":
        return _content_type_is_pdfish(value)
    if extension == ".docx":
        return _content_type_is_docxish(value)
    return False


def _capture_path(county: str) -> Path:
    return ARCHIVE / county / "captures.ndjson"


def _page_capture_path(county: str) -> Path:
    return ARCHIVE / county / "page-captures.ndjson"


def _materialize_capture_path_from_head(county: str) -> None:
    """Sparse checkouts can omit capture logs; restore them before appending."""
    path = _capture_path(county)
    if path.exists():
        return
    try:
        rel = path.relative_to(REPO).as_posix()
    except ValueError:
        return
    try:
        content = subprocess.check_output(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _existing_capture_keys(county: str) -> set[tuple[str, str, str | None]]:
    _materialize_capture_path_from_head(county)
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


def _existing_page_capture_keys(county: str) -> set[tuple[str, str]]:
    path = _page_capture_path(county)
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
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
            keys.add((url, sha))
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
        source_format=_source_format(ref),
        archive_extension=_source_extension(ref).lstrip("."),
    ).to_row()
    if dry_run:
        print(f"  would log capture {ref.filename} sha={sha[:12]} wayback={ref.wayback_ts or '-'}")
        return
    _materialize_capture_path_from_head(county)
    path = _capture_path(county)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _append_page_capture(
    county: str,
    ref: PageRef,
    sha: str,
    content_length: int,
    archive_path: Path,
    dry_run: bool,
) -> None:
    source_url = ref.source_url or ref.url
    row = {
        "archive_path": archive_path.relative_to(REPO).as_posix(),
        "captured_at": utc_now().isoformat(),
        "content_length": content_length,
        "county": county,
        "page_kind": ref.page_kind,
        "source_sha256": sha,
        "source_url": source_url,
        "title": ref.title,
    }
    if dry_run:
        print(f"  would log page {ref.title} sha={sha[:12]} url={source_url}")
        return
    path = _page_capture_path(county)
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
    verify_tls: bool = True,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> tuple[bytes, str]:
    allowed = allowed_hosts or set()
    extension = _source_extension(ref)
    _validate_source_host(ref.url, allowed)
    fetch_url = _replay_url(ref)
    for _ in range(REDIRECT_LIMIT + 1):
        _validate_fetch_host(fetch_url, ref.url, allowed, wayback=bool(ref.wayback_ts))
        r = session.get(fetch_url, timeout=90, stream=True, allow_redirects=False, verify=verify_tls)
        if 300 <= r.status_code < 400 and r.headers.get("Location"):
            fetch_url = urljoin(fetch_url, r.headers["Location"])
            continue
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if extension == ".pdf" and _content_type_is_jsonish(ctype):
            raw_json = _read_limited_response_bytes(r, max_bytes=max_bytes, source_url=ref.url)
            content = _pdf_from_json_response(raw_json, ref.url)
        elif not _content_type_matches_source(ctype, extension):
            raise ValueError(f"unexpected content type for {extension} source {ref.url}: {ctype}")
        else:
            content = _read_limited_source(
                r,
                max_bytes=max_bytes,
                source_url=ref.url,
                extension=extension,
            )
        break
    else:
        raise ValueError(f"too many redirects for {ref.url}")
    return content, hashlib.sha256(content).hexdigest()


def fetch_page_ref(
    ref: PageRef,
    session: requests.Session,
    *,
    allowed_hosts: set[str] | None = None,
    verify_tls: bool = True,
    max_bytes: int = MAX_PAGE_BYTES,
) -> tuple[str, str]:
    allowed = allowed_hosts or set()
    source_url = ref.source_url or ref.url
    _validate_source_host(ref.url, allowed)
    _validate_source_host(source_url, allowed)
    method = ref.method.upper()
    if method == "POST":
        response = session.post(ref.url, data=ref.data, timeout=90, verify=verify_tls)
    elif method == "GET":
        response = session.get(ref.url, timeout=90, verify=verify_tls)
    else:
        raise ValueError(f"unsupported page fetch method for {source_url}: {ref.method}")
    _validate_fetch_host(response.url or ref.url, source_url, allowed)
    response.raise_for_status()
    ctype = response.headers.get("Content-Type", "")
    if not _content_type_is_htmlish(ctype):
        raise ValueError(f"unexpected content type for page {source_url}: {ctype}")
    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise ValueError(f"page too large for {source_url}: {content_length} bytes")
    body = response.content
    if len(body) > max_bytes:
        raise ValueError(f"page too large for {source_url}: >{max_bytes} bytes")
    text = body.decode(response.encoding or "utf-8", errors="replace")
    if "<html" not in text[:2048].lower() and "<!doctype html" not in text[:2048].lower():
        raise ValueError(f"response does not look like HTML for {source_url}")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_limited_pdf(
    response: requests.Response,
    *,
    max_bytes: int,
    source_url: str,
) -> bytes:
    return _read_limited_source(
        response,
        max_bytes=max_bytes,
        source_url=source_url,
        extension=".pdf",
    )


def _read_limited_source(
    response: requests.Response,
    *,
    max_bytes: int,
    source_url: str,
    extension: str,
) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError(f"source file too large for {source_url}: {content_length} bytes")
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
            if len(first) >= 4 and not _looks_like_source_start(first, extension):
                raise ValueError(f"response is not a {_source_label(extension)} for {source_url}")
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"source file too large for {source_url}: >{max_bytes} bytes")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not _looks_like_source(content, extension):
        raise ValueError(f"response is not a {_source_label(extension)} for {source_url}")
    return content


def _read_limited_response_bytes(
    response: requests.Response,
    *,
    max_bytes: int,
    source_url: str,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"source response too large for {source_url}: >{max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _pdf_from_json_response(raw_json: bytes, source_url: str) -> bytes:
    try:
        payload = json.loads(raw_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"JSON source did not decode for {source_url}: {e}") from e
    data = payload.get("data") if isinstance(payload, dict) else None
    contents = data.get("contents") if isinstance(data, dict) else None
    if not isinstance(contents, str) or not contents:
        raise ValueError(f"JSON source did not contain base64 PDF contents for {source_url}")
    try:
        pdf = base64.b64decode(contents, validate=True)
    except ValueError as e:
        raise ValueError(f"JSON source contained invalid base64 PDF for {source_url}: {e}") from e
    if not _looks_like_pdf(pdf):
        raise ValueError(f"JSON source contents are not a PDF for {source_url}")
    return pdf


def _looks_like_pdf(content: bytes) -> bool:
    sample = content[:1024]
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    return sample.lstrip().startswith(PDF_MAGIC)


def _looks_like_docx(content: bytes) -> bool:
    if not content.startswith(DOCX_MAGIC_PREFIXES):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def _looks_like_source_start(content: bytes, extension: str) -> bool:
    if extension == ".pdf":
        return _looks_like_pdf(content)
    if extension == ".docx":
        return content.startswith(DOCX_MAGIC_PREFIXES)
    return False


def _looks_like_source(content: bytes, extension: str) -> bool:
    if extension == ".pdf":
        return _looks_like_pdf(content)
    if extension == ".docx":
        return _looks_like_docx(content)
    return False


def _source_label(extension: str) -> str:
    return extension.lstrip(".").upper() or "source file"


def discover_live_refs(
    county: str,
    session: requests.Session,
    *,
    continue_on_error: bool = False,
    errors: list[str] | None = None,
) -> list[PdfRef]:
    module = _county_module(county)
    verify_tls = _verify_tls_for_county(county)
    refs: list[PdfRef] = []
    for url in getattr(module, "LANDING_PAGES", []):
        try:
            r = session.get(url, timeout=60, verify=verify_tls)
            r.raise_for_status()
            landing_text = r.text
        except Exception as landing_error:
            if not getattr(module, "READER_FALLBACK_LANDING_PAGES", False):
                _record_failure(errors, f"  ERROR discover landing {url}: {landing_error}")
                if not continue_on_error:
                    raise
                continue
            reader_url = _reader_landing_url(url)
            print(
                f"  WARN discover landing {url} failed; trying reader fallback: {landing_error}",
                file=sys.stderr,
            )
            try:
                r = session.get(reader_url, timeout=90)
                r.raise_for_status()
                landing_text = r.text
                if "Warning: Target URL returned error" in landing_text and ".pdf" not in landing_text.lower():
                    raise RuntimeError("reader fallback did not expose source links")
            except Exception as reader_error:
                _record_failure(errors, f"  ERROR discover landing {url}: {landing_error}")
                _record_failure(errors, f"  ERROR reader fallback {reader_url}: {reader_error}")
                if not continue_on_error:
                    raise
                continue
        try:
            refs.extend(module.discover_live(landing_text, page_url=url))
        except Exception as e:
            _record_failure(errors, f"  ERROR parse landing {url}: {e}")
            if not continue_on_error:
                raise
    return unique_refs(refs)


def _normalize_page_ref(raw: PageRef | str, *, page_kind: str = "tentative_rulings_page") -> PageRef:
    if isinstance(raw, PageRef):
        return raw
    title = filename_from_url(str(raw)) or str(raw).rstrip("/").rsplit("/", 1)[-1] or "page"
    return PageRef(url=str(raw), title=title, page_kind=page_kind)


def discover_live_page_refs(
    county: str,
    session: requests.Session,
    *,
    continue_on_error: bool = False,
    errors: list[str] | None = None,
) -> list[PageRef]:
    module = _county_module(county)
    verify_tls = _verify_tls_for_county(county)
    refs: list[PageRef] = []
    default_page_kind = str(getattr(module, "DEFAULT_PAGE_KIND", "tentative_rulings_page"))

    for raw in getattr(module, "PAGE_CAPTURE_URLS", []):
        refs.append(_normalize_page_ref(raw, page_kind=default_page_kind))

    discover_pages = getattr(module, "discover_live_pages", None)
    if callable(discover_pages):
        for url in getattr(module, "LANDING_PAGES", []):
            try:
                r = session.get(url, timeout=60, verify=verify_tls)
                r.raise_for_status()
                refs.extend(discover_pages(r.text, page_url=url))
            except Exception as e:
                _record_failure(errors, f"  ERROR discover page refs {url}: {e}")
                if not continue_on_error:
                    raise

    extra_pages = getattr(module, "discover_live_page_extra", None)
    if callable(extra_pages):
        try:
            refs.extend(extra_pages(session=session, errors=errors))
        except Exception as e:
            _record_failure(errors, f"  ERROR extra page discovery for {county}: {e}")
            if not continue_on_error:
                raise

    seen: set[tuple[str, str, str]] = set()
    out: list[PageRef] = []
    for ref in refs:
        source_url = ref.source_url or ref.url
        key = (source_url, ref.method.upper(), json.dumps(ref.data, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def discover_extra_live_refs(
    county: str,
    session: requests.Session,
    *,
    continue_on_error: bool = False,
    errors: list[str] | None = None,
) -> list[PdfRef]:
    module = _county_module(county)
    hook = getattr(module, "discover_live_extra", None)
    if not callable(hook):
        return []
    try:
        return unique_refs(list(hook(session=session, errors=errors)))
    except Exception as e:
        _record_failure(errors, f"  ERROR extra live discovery for {county}: {e}")
        if not continue_on_error:
            raise
        return []


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
            ref_from_wayback_url = getattr(module, "ref_from_wayback_url", None)
            if not _url_has_supported_source_extension(original) and not (
                ref_from_wayback_url and getattr(module, "WAYBACK_ALLOW_NON_EXTENSION", False)
            ):
                continue
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

    # Counties with stable "current" source URLs, especially Orange, need exact
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
    explicit = getattr(module, "WAYBACK_NEEDS_LIVE_REFS", None)
    if explicit is not None:
        return bool(explicit)
    return not bool(getattr(module, "WAYBACK_PDF_PATTERNS", ()))


def _run_county(args: argparse.Namespace, county: str, session: requests.Session) -> int:
    failures: list[str] = []
    allowed_hosts = _allowed_hosts_for_county(county)
    verify_tls = _verify_tls_for_county(county)
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
    if do_live:
        try:
            live_refs.extend(
                discover_extra_live_refs(
                    county,
                    session,
                    continue_on_error=args.continue_on_error,
                    errors=failures,
                )
            )
            live_refs = unique_refs(live_refs)
        except Exception as e:
            _record_failure(failures, f"  ERROR extra live discovery for {county}: {e}")
            if not args.continue_on_error:
                raise
    page_refs: list[PageRef] = []
    if do_live:
        try:
            page_refs = discover_live_page_refs(
                county,
                session,
                continue_on_error=args.continue_on_error,
                errors=failures,
            )
        except Exception as e:
            _record_failure(failures, f"  ERROR live page discovery for {county}: {e}")
            if not args.continue_on_error:
                raise
            page_refs = []
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
    if args.limit is not None:
        page_refs = page_refs[: args.limit]
    print(f"{county}: {len(refs)} refs, {len(page_refs)} pages")
    existing = _existing_capture_keys(county)
    existing_pages = _existing_page_capture_keys(county)
    wrote = 0
    for ref in refs:
        try:
            content, sha = fetch_ref(ref, session, allowed_hosts=allowed_hosts, verify_tls=verify_tls)
        except Exception as e:
            _record_failure(
                failures,
                f"  ERROR fetch {ref.url} wayback={ref.wayback_ts or '-'}: {e}",
            )
            continue
        archive_path = ARCHIVE / county / sha[:2] / f"{sha}{_source_extension(ref)}"
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
    wrote_pages = 0
    for ref in page_refs:
        source_url = ref.source_url or ref.url
        try:
            html, sha = fetch_page_ref(ref, session, allowed_hosts=allowed_hosts, verify_tls=verify_tls)
        except Exception as e:
            _record_failure(
                failures,
                f"  ERROR fetch page {source_url}: {e}",
            )
            continue
        archive_path = ARCHIVE / county / "pages" / sha[:2] / f"{sha}.html"
        key = (source_url, sha)
        if args.dry_run:
            print(f"  would store page {ref.title} sha={sha[:12]} from {source_url}")
            continue
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not archive_path.exists():
            archive_path.write_text(html, encoding="utf-8")
        if key not in existing_pages:
            _append_page_capture(county, ref, sha, len(html.encode("utf-8")), archive_path, dry_run=False)
            existing_pages.add(key)
        wrote_pages += 1
    print(f"{county}: archived/logged {wrote} refs")
    if page_refs:
        print(f"{county}: archived/logged {wrote_pages} pages")
    if failures:
        print(f"{county}: {len(failures)} failures", file=sys.stderr)
    return 1 if failures else 0


def run(args: argparse.Namespace) -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "aimesy-tentatives/1.0"})
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    counties = sorted(COUNTY_MODULES) if args.county == "all" else [args.county]
    if args.county == "all" and args.live and not args.wayback:
        live_counties = []
        for county in counties:
            if _routine_live_enabled(county):
                live_counties.append(county)
            else:
                print(f"{county}: skipped routine live check ({_routine_live_disabled_reason(county)})")
        counties = live_counties
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
    parser.add_argument("--live", action="store_true", help="Fetch source files from configured live landing pages")
    parser.add_argument("--wayback", action="store_true", help="Fetch matching Wayback source-file captures")
    parser.add_argument("--from-year", type=int, help="First Wayback capture year, e.g. 2020")
    parser.add_argument("--to-year", type=int, help="Last Wayback capture year, e.g. 2022")
    parser.add_argument("--url-from-year", type=int, help="First year embedded in the source file URL")
    parser.add_argument("--url-to-year", type=int, help="Last year embedded in the source file URL")
    parser.add_argument("--limit", type=int, help="Maximum refs to fetch after discovery")
    parser.add_argument("--continue-on-error", action="store_true", help="Keep processing remaining counties after a county-level failure")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

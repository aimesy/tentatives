import argparse
import hashlib
import io
import json
import zipfile

import pytest

from counties.common import PdfRef, extract_links
from ingest import backfill
from ingest.backfill import (
    MAX_PDF_BYTES,
    _allowed_hosts_for_county,
    _cdx_rows,
    _filter_source_url_years,
    _ref_from_available,
    _read_limited_pdf,
    _replay_url,
    _run_county,
    _source_url_year,
    _validate_source_host,
    _wayback_needs_live_refs,
    _wayback_timestamp,
    fetch_ref,
)


def test_replay_url_uses_wayback_id_form_for_raw_pdf():
    ref = PdfRef(
        url="https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2022/062722.pdf",
        filename="062722.pdf",
        wayback_ts="20220625162710",
    )
    assert _replay_url(ref) == (
        "https://web.archive.org/web/20220625162710id_/"
        "https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2022/062722.pdf"
    )


def test_replay_url_leaves_live_refs_alone():
    ref = PdfRef(url="https://example.test/ruling.pdf", filename="ruling.pdf")
    assert _replay_url(ref) == "https://example.test/ruling.pdf"


def test_amador_wayback_uses_prefix_without_live_discovery():
    assert not _wayback_needs_live_refs("amador")


def test_orange_wayback_uses_live_refs_for_stable_pdf_urls():
    assert _wayback_needs_live_refs("orange")


def test_source_url_year_uses_path_segment():
    ref = PdfRef(
        url="https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2022/041122.pdf",
        filename="041122.pdf",
        wayback_ts="20230324203624",
    )
    assert _source_url_year(ref) == 2022


def test_filter_source_url_years_keeps_requested_url_year_not_capture_year():
    refs = [
        PdfRef(
            url="https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2015/082115.pdf",
            filename="082115.pdf",
            wayback_ts="20150824014923",
        ),
        PdfRef(
            url="https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2022/041122.pdf",
            filename="041122.pdf",
            wayback_ts="20230324203624",
        ),
    ]
    filtered = _filter_source_url_years(refs, from_year=2020, to_year=2022)
    assert [ref.filename for ref in filtered] == ["041122.pdf"]


def test_wayback_timestamp_prefers_end_of_to_year():
    assert _wayback_timestamp(2020, 2022) == "20221231235959"
    assert _wayback_timestamp(2020, None) == "20200101000000"


class _FakeResponse:
    def __init__(
        self,
        chunks=None,
        headers=None,
        *,
        status_code=200,
        payload=None,
        raise_json=False,
        text="",
    ):
        self._chunks = chunks or []
        self.headers = headers or {}
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json
        self.text = text

    def iter_content(self, chunk_size=65536):
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.responses.pop(0)


def _minimal_docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("word/document.xml", "<w:document></w:document>")
    return buf.getvalue()


def test_read_limited_pdf_requires_pdf_magic():
    resp = _FakeResponse([b"<html>not a pdf</html>"])
    try:
        _read_limited_pdf(resp, max_bytes=1024, source_url="https://example.test/a.pdf")
    except ValueError as e:
        assert "not a PDF" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_read_limited_pdf_enforces_size_cap():
    resp = _FakeResponse([b"%PDF-" + b"x" * 10])
    try:
        _read_limited_pdf(resp, max_bytes=8, source_url="https://example.test/a.pdf")
    except ValueError as e:
        assert "too large" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_validate_source_host_allows_subdomains_only():
    _validate_source_host("https://www.example.test/r.pdf", {"example.test"})
    try:
        _validate_source_host("https://example.test.evil/r.pdf", {"example.test"})
    except ValueError as e:
        assert "not in county allowlist" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_allowed_hosts_include_schemeless_wayback_patterns():
    hosts = _allowed_hosts_for_county("amador")
    assert "amadorcourt.org" in hosts
    assert "www.amadorcourt.org" in hosts


def test_run_county_returns_failure_when_ref_fetch_fails(monkeypatch):
    args = argparse.Namespace(
        live=True,
        wayback=False,
        from_year=None,
        to_year=None,
        url_from_year=None,
        url_to_year=None,
        limit=None,
        dry_run=False,
        continue_on_error=True,
    )
    ref = PdfRef(url="https://www.amadorcourt.org/x.pdf", filename="x.pdf")
    monkeypatch.setattr(backfill, "discover_live_refs", lambda *_args, **_kwargs: [ref])
    monkeypatch.setattr(backfill, "fetch_ref", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(backfill, "_existing_capture_keys", lambda _county: set())

    assert _run_county(args, "amador", object()) == 1


def test_extract_links_accepts_reader_markdown_source_links():
    links = extract_links(
        "[Department 10](https://www.riverside.courts.ca.gov/system/files/2023-10/Riv10ruling102323.pdf)"
    )

    assert links[0].tag == "markdown-a"
    assert links[0].text == "Department 10"
    assert links[0].url.endswith("/Riv10ruling102323.pdf")


def test_discover_live_refs_uses_reader_fallback(monkeypatch):
    class _Module:
        LANDING_PAGES = ["https://www.riverside.courts.ca.gov/online-services/tentative-rulings"]
        READER_FALLBACK_LANDING_PAGES = True

        @staticmethod
        def discover_live(text, page_url=None):
            links = extract_links(text)
            return [
                PdfRef(
                    url=links[0].url,
                    filename="Riv10ruling102323.pdf",
                    source_page_url=page_url,
                    link_text=links[0].text,
                )
            ]

    monkeypatch.setattr(backfill, "COUNTY_MODULES", {"riverside": _Module})
    session = _FakeSession([
        _FakeResponse(status_code=403),
        _FakeResponse(
            text=(
                "[Department 10]"
                "(https://www.riverside.courts.ca.gov/system/files/2023-10/Riv10ruling102323.pdf)"
            )
        ),
    ])

    refs = backfill.discover_live_refs("riverside", session)

    assert [ref.filename for ref in refs] == ["Riv10ruling102323.pdf"]
    assert session.urls[1] == backfill._reader_landing_url(_Module.LANDING_PAGES[0])


def test_cdx_rows_returns_empty_for_unexpected_json():
    errors = []
    rows = _cdx_rows(
        "https://example.test/*.pdf",
        from_year=None,
        to_year=None,
        match_type=None,
        session=_FakeSession([_FakeResponse(payload={"error": "bad"})]),
        errors=errors,
    )
    assert rows == []
    assert errors


def test_ref_from_available_accepts_int_status_and_valid_wayback_url():
    ref = PdfRef(url="https://example.test/ruling.pdf", filename="ruling.pdf")
    payload = {
        "archived_snapshots": {
            "closest": {
                "available": True,
                "status": 200,
                "timestamp": "20200102030405",
                "url": "https://web.archive.org/web/20200102030405/https://example.test/ruling.pdf",
            }
        }
    }

    out = _ref_from_available(ref, session=_FakeSession([_FakeResponse(payload=payload)]))

    assert out is not None
    assert out.wayback_ts == "20200102030405"


def test_ref_from_available_rejects_non_wayback_closest_host():
    ref = PdfRef(url="https://example.test/ruling.pdf", filename="ruling.pdf")
    payload = {
        "archived_snapshots": {
            "closest": {
                "available": True,
                "status": "200",
                "timestamp": "20200102030405",
                "url": "https://evil.test/web/20200102030405/https://example.test/ruling.pdf",
            }
        }
    }
    errors = []

    assert _ref_from_available(
        ref,
        session=_FakeSession([_FakeResponse(payload=payload)]),
        errors=errors,
    ) is None
    assert errors


def test_fetch_ref_rejects_html_content_type():
    ref = PdfRef(url="https://example.test/ruling.pdf", filename="ruling.pdf")
    session = _FakeSession([
        _FakeResponse(
            [b"<html>not a pdf</html>"],
            headers={"Content-Type": "text/html"},
        )
    ])

    with pytest.raises(ValueError, match="unexpected content type"):
        fetch_ref(ref, session, allowed_hosts={"example.test"})


def test_fetch_ref_rejects_bad_pdf_magic():
    ref = PdfRef(url="https://example.test/ruling.pdf", filename="ruling.pdf")
    session = _FakeSession([
        _FakeResponse(
            [b"<html>not a pdf</html>"],
            headers={"Content-Type": "application/pdf"},
        )
    ])

    with pytest.raises(ValueError, match="not a PDF"):
        fetch_ref(ref, session, allowed_hosts={"example.test"})


def test_fetch_ref_rejects_oversized_pdf_from_content_length():
    ref = PdfRef(url="https://example.test/ruling.pdf", filename="ruling.pdf")
    session = _FakeSession([
        _FakeResponse(
            [b"%PDF-"],
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(MAX_PDF_BYTES + 1),
            },
        )
    ])

    with pytest.raises(ValueError, match="too large"):
        fetch_ref(ref, session, allowed_hosts={"example.test"})


def test_fetch_ref_accepts_docx_source():
    content = _minimal_docx_bytes()
    ref = PdfRef(url="https://example.test/ruling.docx", filename="ruling.docx")
    session = _FakeSession([
        _FakeResponse(
            [content],
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "Content-Length": str(len(content)),
            },
        )
    ])

    fetched, sha = fetch_ref(ref, session, allowed_hosts={"example.test"})

    assert fetched == content
    assert sha == hashlib.sha256(content).hexdigest()


def test_fetch_ref_rejects_invalid_docx_source():
    ref = PdfRef(url="https://example.test/ruling.docx", filename="ruling.docx")
    session = _FakeSession([
        _FakeResponse(
            [b"PK\x03\x04not really a docx"],
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )
    ])

    with pytest.raises(ValueError, match="not a DOCX"):
        fetch_ref(ref, session, allowed_hosts={"example.test"})


def test_fetch_ref_rejects_wayback_redirect_to_non_allowlisted_host():
    ref = PdfRef(
        url="https://www.amadorcourt.org/ruling.pdf",
        filename="ruling.pdf",
        wayback_ts="20200102030405",
    )
    session = _FakeSession([
        _FakeResponse(
            status_code=302,
            headers={"Location": "https://evil.test/ruling.pdf"},
        )
    ])

    with pytest.raises(ValueError, match="Wayback replay host"):
        fetch_ref(ref, session, allowed_hosts={"amadorcourt.org"})


def test_run_county_continues_after_ref_failure_and_logs_success(tmp_path, monkeypatch):
    args = argparse.Namespace(
        live=True,
        wayback=False,
        from_year=None,
        to_year=None,
        url_from_year=None,
        url_to_year=None,
        limit=None,
        dry_run=False,
        continue_on_error=True,
    )
    bad = PdfRef(url="https://example.test/bad.pdf", filename="bad.pdf")
    good = PdfRef(url="https://example.test/good.pdf", filename="good.pdf")
    content = b"%PDF-1.4\nok\n"
    sha = hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(backfill, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(backfill, "_allowed_hosts_for_county", lambda _county: {"example.test"})
    monkeypatch.setattr(backfill, "discover_live_refs", lambda *_args, **_kwargs: [bad, good])
    monkeypatch.setattr(backfill, "_existing_capture_keys", lambda _county: set())

    def fake_fetch(ref, *args, **kwargs):
        if ref is bad:
            raise RuntimeError("boom")
        return content, sha

    monkeypatch.setattr(backfill, "fetch_ref", fake_fetch)

    assert _run_county(args, "fake", object()) == 1
    assert (tmp_path / "archive" / "fake" / sha[:2] / f"{sha}.pdf").exists()
    rows = [
        json.loads(line)
        for line in (tmp_path / "archive" / "fake" / "captures.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["source_url"] for row in rows] == [good.url]


def test_run_swallows_per_county_failures_with_continue_on_error(monkeypatch):
    """With --continue-on-error, run() exits 0 even if a county errored, so the
    workflow's grep-the-log policy is what decides success (not a stray 503)."""
    args = argparse.Namespace(
        county="all",
        live=True,
        wayback=False,
        from_year=None,
        to_year=None,
        url_from_year=None,
        url_to_year=None,
        limit=None,
        dry_run=False,
        continue_on_error=True,
    )
    # Pretend there are two counties; both report failures via _run_county.
    monkeypatch.setattr(backfill, "COUNTY_MODULES", {"a": object(), "b": object()})
    monkeypatch.setattr(backfill, "_run_county", lambda *_args, **_kwargs: 1)
    assert backfill.run(args) == 0


def test_run_propagates_failures_without_continue_on_error(monkeypatch):
    """Without --continue-on-error, run() still surfaces non-zero so manual
    runs without the flag still fail loudly."""
    args = argparse.Namespace(
        county="all",
        live=True,
        wayback=False,
        from_year=None,
        to_year=None,
        url_from_year=None,
        url_to_year=None,
        limit=None,
        dry_run=False,
        continue_on_error=False,
    )
    monkeypatch.setattr(backfill, "COUNTY_MODULES", {"a": object()})
    monkeypatch.setattr(backfill, "_run_county", lambda *_args, **_kwargs: 1)
    assert backfill.run(args) == 1

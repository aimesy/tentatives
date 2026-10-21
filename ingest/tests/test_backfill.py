import argparse
import base64
import hashlib
import io
import json
import zipfile

import pytest

from counties.common import PageRef, PdfRef, extract_links
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
    _verify_tls_for_county,
    _wayback_needs_live_refs,
    _wayback_timestamp,
    fetch_ref,
    fetch_page_ref,
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
        self.content = b"".join(self._chunks)
        self.encoding = "utf-8"
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
        self.posts = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected GET {url}")
        response = self.responses.pop(0)
        response.url = url
        return response

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected POST {url}")
        response = self.responses.pop(0)
        response.url = url
        return response


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


def test_allowed_hosts_include_explicit_orange_source_host():
    hosts = _allowed_hosts_for_county("orange")
    assert "live-jcc-oc.pantheonsite.io" in hosts


def test_placer_tls_verification_is_county_scoped():
    assert _verify_tls_for_county("placer") is False
    assert _verify_tls_for_county("orange") is True


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


def test_fetch_ref_accepts_base64_pdf_json_source():
    content = b"%PDF-1.4\nok\n"
    payload = json.dumps({"data": {"contents": base64.b64encode(content).decode("ascii")}}).encode("utf-8")
    ref = PdfRef(url="https://api.example.test/doc/123", filename="ruling.pdf")
    session = _FakeSession([
        _FakeResponse(
            [payload],
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    ])

    fetched, sha = fetch_ref(ref, session, allowed_hosts={"api.example.test"})

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


def test_fetch_page_ref_accepts_html_page():
    content = b"<!DOCTYPE html><html><body>Tentative ruling</body></html>"
    ref = PageRef(url="https://example.test/rulings", title="Rulings")
    session = _FakeSession([
        _FakeResponse(
            [content],
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
    ])

    fetched, sha = fetch_page_ref(ref, session, allowed_hosts={"example.test"})

    assert "Tentative ruling" in fetched
    assert sha == hashlib.sha256(fetched.encode("utf-8")).hexdigest()


def test_fetch_page_ref_posts_logical_source_url():
    content = b"<!DOCTYPE html><html><body>Result</body></html>"
    ref = PageRef(
        url="https://example.test/form",
        source_url="https://example.test/form?selection=dept",
        title="Dept result",
        method="POST",
        data={"dept": "1"},
    )
    session = _FakeSession([
        _FakeResponse(
            [content],
            headers={"Content-Type": "text/html"},
            text=content.decode("utf-8"),
        )
    ])

    fetched, _sha = fetch_page_ref(ref, session, allowed_hosts={"example.test"})

    assert fetched.endswith("</html>")


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
    monkeypatch.setattr(backfill, "_verify_tls_for_county", lambda _county: True)
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


def test_existing_capture_keys_materializes_sparse_capture_log(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    path = archive / "fake" / "captures.ndjson"
    sha = "a" * 64
    row = {
        "source_sha256": sha,
        "source_url": "https://example.test/ruling.pdf",
        "wayback_ts": None,
    }

    def fake_check_output(cmd, cwd=None, stderr=None):
        assert cmd == ["git", "show", "HEAD:archive/fake/captures.ndjson"]
        assert cwd == tmp_path
        assert stderr is backfill.subprocess.DEVNULL
        return (json.dumps(row) + "\n").encode("utf-8")

    monkeypatch.setattr(backfill, "REPO", tmp_path)
    monkeypatch.setattr(backfill, "ARCHIVE", archive)
    monkeypatch.setattr(backfill.subprocess, "check_output", fake_check_output)

    assert backfill._existing_capture_keys("fake") == {
        (sha, "https://example.test/ruling.pdf", None)
    }
    assert path.read_text(encoding="utf-8").strip() == json.dumps(row)


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


def test_run_skips_routine_disabled_counties_for_all_live(monkeypatch):
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
    calls = []

    class _RoutineDisabled:
        ROUTINE_LIVE = False
        ROUTINE_LIVE_DISABLED_REASON = "historical only"

    class _RoutineEnabled:
        pass

    monkeypatch.setattr(backfill, "COUNTY_MODULES", {"amador": _RoutineDisabled, "orange": _RoutineEnabled})
    monkeypatch.setattr(backfill, "_run_county", lambda _args, county, _session: calls.append(county) or 0)

    assert backfill.run(args) == 0
    assert calls == ["orange"]


def test_run_keeps_routine_disabled_county_for_wayback(monkeypatch):
    args = argparse.Namespace(
        county="all",
        live=False,
        wayback=True,
        from_year=None,
        to_year=None,
        url_from_year=None,
        url_to_year=None,
        limit=None,
        dry_run=False,
        continue_on_error=True,
    )
    calls = []

    class _RoutineDisabled:
        ROUTINE_LIVE = False

    monkeypatch.setattr(backfill, "COUNTY_MODULES", {"amador": _RoutineDisabled})
    monkeypatch.setattr(backfill, "_run_county", lambda _args, county, _session: calls.append(county) or 0)

    assert backfill.run(args) == 0
    assert calls == ["amador"]


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


def test_page_content_key_ignores_regenerated_markup():
    first = (
        '<html><body><button aria-controls="588536430">Menu</button>'
        '<div class="js-view-dom-id-c2ce83b2"><p>Case 123: motion GRANTED.</p>'
        '<a href="/files/ruling.pdf">Ruling</a></div>'
        '<script type="application/json">{"permissionsHash":"aaa"}</script></body></html>'
    )
    second = (
        '<html><body><button aria-controls="302659368">Menu</button>'
        '<div class="js-view-dom-id-7561ac22"><p>Case 123:   motion GRANTED.</p>'
        '<a href="/files/ruling.pdf">Ruling</a></div>'
        '<script type="application/json">{"permissionsHash":"bbb"}</script></body></html>'
    )
    assert backfill.page_content_key(first) == backfill.page_content_key(second)


def test_page_content_key_changes_with_text_or_links():
    base = '<html><body><p>Case 123: motion GRANTED.</p><a href="/a.pdf">Ruling</a></body></html>'
    new_text = '<html><body><p>Case 123: motion DENIED.</p><a href="/a.pdf">Ruling</a></body></html>'
    new_link = '<html><body><p>Case 123: motion GRANTED.</p><a href="/b.pdf">Ruling</a></body></html>'
    keys = {backfill.page_content_key(html) for html in (base, new_text, new_link)}
    assert len(keys) == 3


def _page_args():
    return argparse.Namespace(
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


def test_run_county_skips_page_whose_visible_content_is_unchanged(tmp_path, monkeypatch, capsys):
    ref = PageRef(url="https://example.test/tentatives", title="Tentatives")
    pages = iter([
        '<html><body><div id="111"><p>Case 1: GRANTED.</p></div></body></html>',
        '<html><body><div id="222"><p>Case 1: GRANTED.</p></div></body></html>',
        '<html><body><div id="333"><p>Case 1: DENIED.</p></div></body></html>',
    ])

    monkeypatch.setattr(backfill, "REPO", tmp_path)
    monkeypatch.setattr(backfill, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(backfill, "_allowed_hosts_for_county", lambda _county: {"example.test"})
    monkeypatch.setattr(backfill, "_verify_tls_for_county", lambda _county: True)
    monkeypatch.setattr(backfill, "discover_live_refs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(backfill, "discover_extra_live_refs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(backfill, "discover_live_page_refs", lambda *_args, **_kwargs: [ref])
    monkeypatch.setattr(backfill, "_existing_capture_keys", lambda _county: set())

    def fake_fetch_page(_ref, *_args, **_kwargs):
        html = next(pages)
        return html, hashlib.sha256(html.encode("utf-8")).hexdigest()

    monkeypatch.setattr(backfill, "fetch_page_ref", fake_fetch_page)

    for _ in range(3):
        assert _run_county(_page_args(), "fake", object()) == 0

    log = tmp_path / "archive" / "fake" / "page-captures.ndjson"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert all(row["content_key"] for row in rows)
    assert len(list((tmp_path / "archive" / "fake" / "pages").rglob("*.html"))) == 2
    assert "skipped 1 pages unchanged" in capsys.readouterr().out


def test_run_county_compares_against_older_rows_without_content_key(tmp_path, monkeypatch):
    html = '<html><body><div id="111"><p>Case 1: GRANTED.</p></div></body></html>'
    old_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    county_dir = tmp_path / "archive" / "fake"
    page_path = county_dir / "pages" / old_sha[:2] / f"{old_sha}.html"
    page_path.parent.mkdir(parents=True)
    page_path.write_text(html, encoding="utf-8")
    (county_dir / "page-captures.ndjson").write_text(
        json.dumps({
            "archive_path": page_path.relative_to(tmp_path).as_posix(),
            "captured_at": "2026-09-28T03:53:11+00:00",
            "source_sha256": old_sha,
            "source_url": "https://example.test/tentatives",
        }) + "\n",
        encoding="utf-8",
    )
    ref = PageRef(url="https://example.test/tentatives", title="Tentatives")
    regenerated = html.replace('id="111"', 'id="999"')

    monkeypatch.setattr(backfill, "REPO", tmp_path)
    monkeypatch.setattr(backfill, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(backfill, "_allowed_hosts_for_county", lambda _county: {"example.test"})
    monkeypatch.setattr(backfill, "_verify_tls_for_county", lambda _county: True)
    monkeypatch.setattr(backfill, "discover_live_refs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(backfill, "discover_extra_live_refs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(backfill, "discover_live_page_refs", lambda *_args, **_kwargs: [ref])
    monkeypatch.setattr(backfill, "_existing_capture_keys", lambda _county: set())
    monkeypatch.setattr(
        backfill,
        "fetch_page_ref",
        lambda *_args, **_kwargs: (regenerated, hashlib.sha256(regenerated.encode("utf-8")).hexdigest()),
    )

    assert _run_county(_page_args(), "fake", object()) == 0
    assert len((county_dir / "page-captures.ndjson").read_text(encoding="utf-8").splitlines()) == 1
    assert len(list((county_dir / "pages").rglob("*.html"))) == 1


# Repeat downloads: conditional requests, removed files, logged Wayback captures.


class _HTTPError(Exception):
    def __init__(self, status_code):
        super().__init__(f"{status_code} Client Error")
        self.response = type("R", (), {"status_code": status_code})()


class _Server:
    """Serves fixed files and honours If-None-Match / If-Modified-Since."""

    def __init__(self, files, etags=None, last_modified=None, gone=()):
        self.files = files
        self.etags = etags or {}
        self.last_modified = last_modified or {}
        self.gone = set(gone)
        self.requests = []

    def get(self, url, **kwargs):
        headers = kwargs.get("headers") or {}
        self.requests.append((url, dict(headers)))
        if url in self.gone:
            response = _FakeResponse(status_code=404)

            def raise_gone():
                raise _HTTPError(404)

            response.raise_for_status = raise_gone
            return response
        etag = self.etags.get(url)
        modified = self.last_modified.get(url)
        if (etag and headers.get("If-None-Match") == etag) or (
            not etag and modified and headers.get("If-Modified-Since") == modified
        ):
            response = _FakeResponse(status_code=304)
            response.url = url
            return response
        response_headers = {"Content-Type": self.files[url][1]}
        if etag:
            response_headers["ETag"] = etag
        if modified:
            response_headers["Last-Modified"] = modified
        body = self.files[url][0]
        response = _FakeResponse([body], response_headers, text=body.decode("utf-8", "replace"))
        response.url = url
        return response


def _live_args(**overrides):
    values = dict(
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
    values.update(overrides)
    return argparse.Namespace(**values)


def _patch_county(monkeypatch, tmp_path, refs=(), pages=()):
    monkeypatch.setattr(backfill, "REPO", tmp_path)
    monkeypatch.setattr(backfill, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(backfill, "_allowed_hosts_for_county", lambda _county: {"example.test"})
    monkeypatch.setattr(backfill, "_verify_tls_for_county", lambda _county: True)
    monkeypatch.setattr(backfill, "discover_live_refs", lambda *_args, **_kwargs: list(refs))
    monkeypatch.setattr(backfill, "discover_extra_live_refs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(backfill, "discover_live_page_refs", lambda *_args, **_kwargs: list(pages))
    monkeypatch.setattr(backfill, "_head_bytes", lambda _path: None)


def _state_rows(tmp_path):
    path = tmp_path / "archive" / "fake" / "fetch-state.ndjson"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fetch_ref_raises_not_modified_on_304_and_records_validators():
    ref = PdfRef(url="https://example.test/a.pdf", filename="a.pdf")
    server = _Server(
        {"https://example.test/a.pdf": (b"%PDF-1.4\nA\n", "application/pdf")},
        etags={"https://example.test/a.pdf": '"v1"'},
        last_modified={"https://example.test/a.pdf": "Tue, 20 Oct 2026 21:09:19 GMT"},
    )
    validators = {}
    content, _sha = fetch_ref(ref, server, allowed_hosts={"example.test"}, validators=validators)
    assert content.startswith(b"%PDF")
    assert validators == {"etag": '"v1"', "last_modified": "Tue, 20 Oct 2026 21:09:19 GMT"}
    assert server.requests[0][1] == {}

    with pytest.raises(backfill.NotModified):
        fetch_ref(ref, server, allowed_hosts={"example.test"}, conditional={"If-None-Match": '"v1"'})
    assert server.requests[1][1] == {"If-None-Match": '"v1"'}


def test_run_county_sends_conditional_request_and_skips_download_on_304(tmp_path, monkeypatch, capsys):
    url = "https://example.test/a.pdf"
    ref = PdfRef(url=url, filename="a.pdf")
    server = _Server(
        {url: (b"%PDF-1.4\nA\n", "application/pdf")},
        last_modified={url: "Tue, 20 Oct 2026 21:09:19 GMT"},
    )
    _patch_county(monkeypatch, tmp_path, refs=[ref])
    args = _live_args(summary={})

    assert _run_county(args, "fake", server) == 0
    assert server.requests[-1][1] == {}
    [row] = _state_rows(tmp_path)
    assert row["url"] == url and row["last_modified"] == "Tue, 20 Oct 2026 21:09:19 GMT" and row["sha256"]
    captures = (tmp_path / "archive" / "fake" / "captures.ndjson").read_text(encoding="utf-8")

    assert _run_county(args, "fake", server) == 0
    assert server.requests[-1][1] == {"If-Modified-Since": "Tue, 20 Oct 2026 21:09:19 GMT"}
    assert (tmp_path / "archive" / "fake" / "captures.ndjson").read_text(encoding="utf-8") == captures
    assert args.summary["fake"]["refs"] == 1
    assert args.summary["fake"]["refs_not_modified"] == 1
    out = capsys.readouterr().out
    assert "fake: archived/logged 1 refs" in out
    assert "1 refs and 0 pages not modified" in out


def test_run_county_downloads_again_when_the_file_changed(tmp_path, monkeypatch):
    url = "https://example.test/a.pdf"
    ref = PdfRef(url=url, filename="a.pdf")
    server = _Server({url: (b"%PDF-1.4\nA\n", "application/pdf")}, etags={url: '"v1"'})
    _patch_county(monkeypatch, tmp_path, refs=[ref])

    assert _run_county(_live_args(), "fake", server) == 0
    server.files[url] = (b"%PDF-1.4\nB\n", "application/pdf")
    server.etags[url] = '"v2"'
    assert _run_county(_live_args(), "fake", server) == 0

    assert server.requests[-1][1] == {"If-None-Match": '"v1"'}
    log = (tmp_path / "archive" / "fake" / "captures.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(log) == 2
    assert _state_rows(tmp_path)[0]["etag"] == '"v2"'


def test_run_county_stops_requesting_a_removed_file(tmp_path, monkeypatch, capsys):
    gone = PdfRef(url="https://example.test/gone.pdf", filename="gone.pdf")
    server = _Server({}, gone={gone.url})
    _patch_county(monkeypatch, tmp_path, refs=[gone])

    assert _run_county(_live_args(), "fake", server) == 1
    assert len(server.requests) == 1
    [row] = _state_rows(tmp_path)
    assert row["gone"] == 404 and row["url"] == gone.url

    args = _live_args(summary={})
    assert _run_county(args, "fake", server) == 0
    assert len(server.requests) == 1
    assert args.summary["fake"]["skipped_gone"] == 1
    assert args.summary["fake"]["failures"] == []
    assert "1 URLs the court removed" in capsys.readouterr().out


def test_run_county_skips_logged_wayback_captures_before_the_limit(tmp_path, monkeypatch):
    original = "https://example.test/a.pdf"
    old = PdfRef(url=original, filename="a.pdf", wayback_ts="20240101000000")
    new = PdfRef(url=original, filename="a.pdf", wayback_ts="20250101000000")
    monkeypatch.setattr(backfill, "discover_wayback_refs", lambda *_args, **_kwargs: [old, new])
    monkeypatch.setattr(backfill, "_wayback_needs_live_refs", lambda _county: False)
    monkeypatch.setattr(backfill, "_existing_capture_keys", lambda _county: {("sha-old", original, old.wayback_ts)})
    fetched = []

    def fake_fetch(ref, *_args, **kwargs):
        fetched.append(ref)
        assert not kwargs.get("conditional")
        content = b"%PDF-1.4\nnew\n"
        return content, hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(backfill, "fetch_ref", fake_fetch)
    _patch_county(monkeypatch, tmp_path)

    assert _run_county(_live_args(live=False, wayback=True, limit=1), "fake", object()) == 0
    assert fetched == [new]
    # Wayback captures never change, so they need no fetch state.
    assert not (tmp_path / "archive" / "fake" / "fetch-state.ndjson").exists()


def test_run_county_treats_page_304_as_unchanged(tmp_path, monkeypatch):
    url = "https://example.test/tentatives"
    ref = PageRef(url=url, title="Tentatives")
    html = b"<html><body><p>Case 1: GRANTED.</p></body></html>"
    server = _Server({url: (html, "text/html")}, etags={url: '"p1"'})
    _patch_county(monkeypatch, tmp_path, pages=[ref])

    assert _run_county(_live_args(), "fake", server) == 0
    args = _live_args(summary={})
    assert _run_county(args, "fake", server) == 0

    assert server.requests[-1][1] == {"If-None-Match": '"p1"'}
    assert args.summary["fake"]["pages_not_modified"] == 1
    assert args.summary["fake"]["pages_unchanged"] == 1
    assert len((tmp_path / "archive" / "fake" / "page-captures.ndjson").read_text(encoding="utf-8").splitlines()) == 1


def test_dry_run_writes_no_fetch_state(tmp_path, monkeypatch):
    url = "https://example.test/a.pdf"
    server = _Server({url: (b"%PDF-1.4\nA\n", "application/pdf")}, etags={url: '"v1"'})
    _patch_county(monkeypatch, tmp_path, refs=[PdfRef(url=url, filename="a.pdf")])

    assert _run_county(_live_args(dry_run=True), "fake", server) == 0
    assert not (tmp_path / "archive" / "fake" / "fetch-state.ndjson").exists()

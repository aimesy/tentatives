from counties.common import PdfRef
from ingest.backfill import (
    _filter_source_url_years,
    _replay_url,
    _source_url_year,
    _wayback_needs_live_refs,
    _wayback_timestamp,
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

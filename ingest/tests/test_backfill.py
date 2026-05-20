from counties.common import PdfRef
from ingest.backfill import _replay_url, _wayback_needs_live_refs


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

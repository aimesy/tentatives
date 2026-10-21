from pathlib import Path

from counties.santa_barbara.scraper import _detail_page_refs, _index_rows

FIXTURE = (Path(__file__).parent / "index_rows_fixture.html").read_text(encoding="utf-8")


def test_index_rows_key_each_ruling_by_its_row_text():
    rows = _index_rows(FIXTURE)
    row = rows["/tentative-ruling/1272565"]
    assert "October 21, 2026" in row and "1272565" in row and "Biennial Review" in row


def test_detail_refs_carry_their_index_row():
    refs = _detail_page_refs(FIXTURE, "https://www.santabarbara.courts.ca.gov/tentative-rulings")
    assert refs and all(ref.index_row for ref in refs)

from counties.nevada.scraper import discover_live


def test_discovers_nevada_pdf_and_docx_links():
    html = """
    <a href="/system/files/tentative-rulings/cmc-51526-dept-truckee.docx">
      May 15, 2026, Case Management Conference Tentative Rulings
    </a>
    <a href="/system/files/tentative-rulings/cmc-41726-dept-truckee.pdf">
      April 17, 2026, Case Management Conference Tentative Rulings
    </a>
    """
    refs = discover_live(html, page_url="https://www.nevada.courts.ca.gov/online-services/tentative-rulings")
    assert [ref.filename for ref in refs] == [
        "cmc-51526-dept-truckee.docx",
        "cmc-41726-dept-truckee.pdf",
    ]
    assert [ref.division_hint for ref in refs] == ["Case Management", "Case Management"]

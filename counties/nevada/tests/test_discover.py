from counties.nevada.scraper import discover_live


def test_discovers_nevada_pdf_links_but_not_docx():
    html = """
    <a href="/system/files/tentative-rulings/cmc-51526-dept-truckee.docx">
      May 15, 2026, Case Management Conference Tentative Rulings
    </a>
    <a href="/system/files/tentative-rulings/cmc-41726-dept-truckee.pdf">
      April 17, 2026, Case Management Conference Tentative Rulings
    </a>
    """
    refs = discover_live(html, page_url="https://www.nevada.courts.ca.gov/online-services/tentative-rulings")
    assert len(refs) == 1
    assert refs[0].filename == "cmc-41726-dept-truckee.pdf"
    assert refs[0].division_hint == "Case Management"

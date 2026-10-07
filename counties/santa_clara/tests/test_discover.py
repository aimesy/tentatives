from counties.santa_clara.scraper import LANDING_PAGES, discover_live


def test_landing_pages_use_current_dept_slug_for_complex_departments():
    assert "https://santaclara.courts.ca.gov/online-services/tentative-rulings/dept-16-tentative-rulings" in LANDING_PAGES
    assert "https://santaclara.courts.ca.gov/online-services/tentative-rulings/dept-19-tentative-rulings" in LANDING_PAGES
    assert "https://santaclara.courts.ca.gov/online-services/tentative-rulings/dept-22-tentative-rulings" in LANDING_PAGES


def test_discover_live_accepts_dept_slug_page_url():
    refs = discover_live(
        '<a href="/system/files/tentative-ruling/dept-19-tentative-rulings.pdf">Tentative ruling</a>',
        page_url="https://santaclara.courts.ca.gov/online-services/tentative-rulings/dept-19-tentative-rulings",
    )

    assert len(refs) == 1
    assert refs[0].dept_hint == "19"
    assert refs[0].division_hint == "Complex Civil"

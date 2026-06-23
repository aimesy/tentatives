from counties.butte import scraper as butte
from counties.los_angeles import scraper as los_angeles
from counties.san_mateo import scraper as san_mateo
from counties.santa_barbara import scraper as santa_barbara
from counties.ventura import scraper as ventura


def test_butte_discovers_system_tentative_pdf():
    refs = butte.discover_live(
        '<a href="/system/files/tentative-rulings/civil-tentative-rulings.pdf">Civil Tentative Rulings</a>'
    )

    assert refs[0].filename == "civil-tentative-rulings.pdf"
    assert refs[0].division_hint == "Civil Law and Motion"


def test_san_mateo_accepts_web_sanmateocourt_pdf():
    refs = san_mateo.discover_live(
        '<a href="https://web.sanmateocourt.org/tentative/tr-monday.pdf">Civil Tentative Monday</a>',
        page_url="https://sanmateo.courts.ca.gov/online-services/tentative-rulings/civil-law-motion-tentative-rulings",
    )

    assert refs[0].url.startswith("https://web.sanmateocourt.org/")
    assert refs[0].division_hint == "Civil Law and Motion"


def test_santa_barbara_discovers_detail_page_refs():
    pages = santa_barbara.discover_live_pages(
        '<a href="/tentative-ruling/24CV12345">Ruling detail</a>',
        page_url="https://www.santabarbara.courts.ca.gov/tentative-rulings",
    )

    assert pages[0].url.endswith("/tentative-ruling/24CV12345")
    assert pages[0].page_kind == "tentative_ruling_detail"


def test_los_angeles_builds_post_page_refs():
    html = """
    <input type="hidden" name="__VIEWSTATE" value="vs" />
    <input type="hidden" name="__VIEWSTATEGENERATOR" value="vg" />
    <input type="hidden" name="__EVENTVALIDATION" value="ev" />
    <option value="LAM,307,06/24/2026">(Stanley Mosk Courthouse: Dept. 307) June 24, 2026</option>
    """

    class _Session:
        def get(self, url, timeout=60):
            class _Response:
                text = html

                def raise_for_status(self):
                    pass

            return _Response()

    refs = los_angeles.discover_live_page_extra(session=_Session())

    assert refs[0].method == "POST"
    assert "dept_date=LAM%2C307%2C06%2F24%2F2026" in refs[0].source_url
    assert refs[0].data[los_angeles.SELECT_NAME] == "LAM,307,06/24/2026"


def test_ventura_extracts_token_and_viewfile_refs():
    assert ventura._token('<input name="__RequestVerificationToken" type="hidden" value="tok" />') == "tok"
    matches = list(ventura.VIEW_FILE_RE.finditer('<a href="/CaseInquiry/ViewFile/123">PDF</a>'))
    assert matches[0].group("id") == "123"

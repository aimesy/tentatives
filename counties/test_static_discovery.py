from counties.fresno import scraper as fresno
from counties.merced import scraper as merced
from counties.plumas import scraper as plumas
from counties.riverside import scraper as riverside
from counties.san_bernardino import scraper as san_bernardino
from counties.santa_clara import scraper as santa_clara
from counties.shasta import scraper as shasta
from counties.solano import scraper as solano
from counties.tuolumne import scraper as tuolumne


def test_fresno_discovers_dept_pdf():
    refs = fresno.discover_live(
        '<a href="/system/files/tentative-rulings/03-18-25-dept-503.pdf">March 18</a>'
    )
    assert refs[0].dept_hint == "503"
    assert refs[0].division_hint == "Civil Law and Motion"


def test_merced_discovers_weekday_pdf():
    refs = merced.discover_live(
        '<a href="/system/files/tentative-rulings/tr-monday.pdf">View Monday</a>'
    )
    assert refs[0].filename == "tr-monday.pdf"


def test_plumas_discovers_dept_two_pdf():
    refs = plumas.discover_live(
        '<a href="/system/files/tentative-ruling/tentative-ruling-may-11-2026-complete.pdf">Tentative Rulings</a>'
    )
    assert refs[0].dept_hint == "2"


def test_riverside_discovers_ruling_pdf():
    refs = riverside.discover_live(
        '<a href="/system/files/2026-05/PS4ruling051326.pdf">Department PS4</a>'
    )
    assert refs[0].dept_hint == "PS4"


def test_san_bernardino_discovers_legacy_table_pdf():
    refs = san_bernardino.discover_live(
        '<a href="/DesktopModules/TentativeRulings/TentativeRulings/CVS36052026.pdf">CVS36052026.pdf</a>'
    )
    assert refs[0].dept_hint == "S36"


def test_santa_clara_discovers_department_pdf():
    refs = santa_clara.discover_live(
        '<a href="/system/files/tentative-ruling/dept-1-tues.pdf">Tentative rulings for Tuesday</a>',
        page_url="https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-1-tentative-rulings",
    )
    assert refs[0].dept_hint == "1"
    assert refs[0].division_hint == "Civil Law and Motion"


def test_shasta_maps_old_department_names():
    refs = shasta.discover_live(
        '<a href="/system/files/tentative/tentatived10.pdf">Tentative Rulings</a>'
    )
    assert refs[0].dept_hint == "24"


def test_solano_discovers_department_pdfs_but_skips_forms():
    refs = solano.discover_live(
        """
        <a href="/system/files/general/dept_22.pdf">Department Twenty-Two</a>
        <a href="/system/files/forms/argument_form.pdf">Download Form</a>
        """
    )
    assert [ref.filename for ref in refs] == ["dept_22.pdf"]
    assert refs[0].dept_hint == "22"


def test_tuolumne_discovers_tentatives_but_skips_case_notes():
    refs = tuolumne.discover_live(
        """
        <a href="/system/files/tentative-rulings/tr_d5_01212026.pdf">Tentative Ruling - Department 5</a>
        <a href="/system/files/tentative-rulings/casenote_d5.pdf">Case Notes - Department 5</a>
        """
    )
    assert [ref.filename for ref in refs] == ["tr_d5_01212026.pdf"]
    assert refs[0].dept_hint == "5"

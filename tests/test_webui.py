"""The workbench page, driven in a real Chromium against the real local
host: the page draws what Python computed and nothing else.

Skipped where there is no browser driver; CI's ``test-gui`` job installs
one and sets ``FMCW_REQUIRE_BROWSER=1``, which turns a skip into a failure.
``FMCW_BROWSER`` names a Chromium binary to use instead of the driver's own."""

import os
import threading

import pytest

from fmcw_radar import guispec, guiutil, webhost

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                     # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None and os.environ.get("FMCW_REQUIRE_BROWSER") != "1",
                                reason="no browser driver (pip install playwright; playwright install chromium)")
FAST = {"chirp.n_chirps": 8, "lo.engine": "response"}


def _serve(backend):
    srv = webhost.make_server(0, backend=backend)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


@pytest.fixture(scope="module")
def browser():
    assert sync_playwright is not None, "FMCW_REQUIRE_BROWSER=1 but playwright is not installed"
    with sync_playwright() as pw:
        exe = os.environ.get("FMCW_BROWSER")
        b = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    srv, url = _serve("thread")
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    p = ctx.new_page()
    p.errors = []
    p.on("pageerror", lambda e: p.errors.append(str(e)))
    p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" else None)
    p.goto(url)
    p.wait_for_selector(".kpi")
    yield p
    assert p.errors == []
    ctx.close()
    srv.shutdown()
    srv.server_close()


def _set(p, path, value):
    sel = f'[data-path="{path}"]'
    if p.evaluate(f"document.querySelector('{sel}').tagName") == "SELECT":
        p.select_option(sel, value)
    else:
        p.fill(sel, str(value))
        p.press(sel, "Enter")


def _tile(p, n):
    return p.evaluate(f"document.querySelectorAll('.kpi .v')[{n}].textContent.trim()")


def _settled(p):
    p.wait_for_function("document.getElementById('busy').hidden === true && !document.querySelector('.empty.span2')")
    p.wait_for_timeout(350)                              # past the 250 ms debounce
    p.wait_for_function("document.getElementById('busy').hidden === true")


def test_the_page_shows_what_python_computed(page):
    """Every control from the spec, the default run's headline numbers as
    guiutil gives them, one id per control."""
    ref = guiutil.run_report({})
    assert page.evaluate("document.querySelectorAll('.fld').length") == len(guispec.controls()) == 88
    ids = page.evaluate("[...document.querySelectorAll('[id]')].map(e => e.id)")
    assert len(ids) == len(set(ids))
    assert _tile(page, 1) == f"{ref['metrics']['snr_cell_db']:.2f}dB" and _tile(page, 0) == "通过"
    assert _tile(page, 3) == f"{ref['metrics']['range_res_m'] * 100:.2f}cm"
    assert page.evaluate("document.querySelector('.kv').textContent").count(ref["repro"]["config_sha256"]) == 1
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    # the tag beside an untouched sourced field is the source table's, and its citation opens
    assert page.evaluate("document.querySelector('[data-fld=\"frontend.tx_power_dbm\"] .tag').textContent") == "spec"
    page.click('[data-fld="frontend.tx_power_dbm"] .tag')
    assert "60g_sensing.tx_power_dbm = 12" in page.evaluate("document.getElementById('pop').textContent")


def test_turning_a_knob_recomputes_and_an_edited_number_is_assumed(page):
    _set(page, "lo.engine", "response")                  # the fast engine for the rest
    _set(page, "target.range_m", 10)
    _settled(page)
    ref = guiutil.run_report({"lo.engine": "response", "target.range_m": 10.0})
    assert _tile(page, 1) == f"{ref['metrics']['snr_cell_db']:.2f}dB"
    # a sourced number edited on the page turns assumed; typed back, it is the citation again
    row = '[data-fld="frontend.tx_power_dbm"]'
    _set(page, "frontend.tx_power_dbm", 10)
    _settled(page)
    assert page.evaluate(f"document.querySelector('{row} .tag').textContent") == "assumed"
    assert page.evaluate(f"document.querySelector('{row} .tag').classList.contains('edited')")
    assert "EIRP 12.0 / 14 dBm" in page.evaluate("document.querySelector('.kpi .d').textContent")
    _set(page, "frontend.tx_power_dbm", 12)
    _settled(page)
    assert page.evaluate(f"document.querySelector('{row} .tag').textContent") == "spec"
    assert page.evaluate(f"document.querySelector('{row} input').classList.contains('chg')") is False
    # the display unit is the spec's: 100 us shows as 100, and goes back as 1e-4 s
    assert page.evaluate("document.querySelector('[data-path=\"chirp.duration_s\"]').value") == "100"


def test_a_refusal_is_the_schemas_sentence_beside_the_control(page):
    _set(page, "lo.engine", "response")
    _settled(page)
    before = _tile(page, 1)
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    _set(page, "mimo.n_rx", 2)
    page.wait_for_selector(".refusal")
    text = page.evaluate("document.querySelector('.refusal').textContent")
    assert "2 virtual elements" in text and "use angle_window 'rect' or 'hamming'" in text
    assert page.evaluate("document.querySelector('[data-fld=\"mimo.angle_window\"]').classList.contains('bad')")
    assert _tile(page, 1) == before                      # the last legal run stays on screen
    assert page.evaluate("document.querySelector('[data-act=frame]').disabled")
    _set(page, "mimo.angle_window", "rect")
    page.wait_for_selector(".refusal", state="detached")
    # an option the config would refuse is greyed out in its menu before the user can pick it
    assert page.evaluate("[...document.querySelectorAll('[data-path=\"lo.dp_cal\"] option')].filter(o => o.disabled).map(o => o.value)") == ["online"]
    _set(page, "lo.engine", "event")
    _settled(page)
    assert page.evaluate("[...document.querySelectorAll('[data-path=\"lo.dp_cal\"] option')].filter(o => o.disabled).length") == 0


def test_idle_controls_are_greyed_out_with_the_reason(page):
    row = '[data-fld="leakage.isolation_db"]'
    assert page.evaluate(f"document.querySelector('{row}').classList.contains('inert')")
    assert "建模收发泄漏 = true" in page.evaluate(f"document.querySelector('{row} .why').textContent")
    assert page.evaluate("document.querySelectorAll('.fld.inert').length") == len(guispec.inert({}))
    _set(page, "lo.engine", "response")
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    _set(page, "leakage.enabled", "true")
    _settled(page)
    assert not page.evaluate(f"document.querySelector('{row}').classList.contains('inert')")
    assert page.evaluate("document.querySelectorAll('.fld.inert').length") == len(guispec.inert({"lo.engine": "response", "leakage.enabled": True}))


def test_the_time_engine_is_a_job_and_its_frame_knows_its_settings(page):
    _set(page, "lo.engine", "response")
    _set(page, "chirp.n_chirps", 8)
    _settled(page)
    assert page.evaluate("!!document.querySelector('.empty')") and "还没跑" in page.evaluate("document.querySelector('.engrow').textContent")
    page.click("[data-act=frame]")
    page.wait_for_selector('[data-chart="rd"] svg', timeout=60000)
    assert page.evaluate("document.querySelectorAll('[data-chart=\"rd\"] .heat rect').length") > 100
    f = guiutil.run_frame(FAST)
    assert f"{f['time_engine']['snr_cell_db']:.2f}" in page.evaluate("document.querySelector('.engrow').textContent")
    assert page.evaluate("document.querySelector('.dlist tbody tr td:last-child').textContent") == str(f["cell_counts"]["target_lobe"])
    # another setting: the frame on screen is no longer this config's, and says so
    _set(page, "target.range_m", 7)
    _settled(page)
    assert "上一组参数" in page.evaluate("document.querySelector('.engrow').textContent")
    assert page.evaluate("document.querySelector('[data-chart=\"rd\"]').classList.contains('dim')")


def test_cancel_stops_the_frame(browser):
    """The desktop backend: the 64-chirp frame takes seconds; cancel ends it
    at once and the page says when."""
    srv, url = _serve("process")
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    p = ctx.new_page()
    try:
        p.goto(url)
        p.wait_for_selector(".kpi")
        _set(p, "lo.engine", "response")
        _settled(p)
        p.click("[data-act=frame]")
        p.wait_for_selector("[data-act=cancel]")
        assert p.evaluate("!!document.querySelector('.bar')")
        p.wait_for_timeout(600)
        p.click("[data-act=cancel]")
        p.wait_for_function("document.getElementById('jobslot').textContent.includes('取消;')", timeout=15000)
        assert p.evaluate("!!document.querySelector('[data-act=frame]')") and not p.evaluate("!!document.querySelector('[data-chart=\"rd\"] svg')")
    finally:
        ctx.close()
        srv.shutdown()
        srv.server_close()


def test_language_theme_and_phone_width(browser):
    srv, url = _serve("thread")
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    p = ctx.new_page()
    try:
        p.goto(url)
        p.wait_for_selector(".kpi")
        assert p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
        nav = p.evaluate("(() => { const n = document.querySelector('.bnav'); const s = getComputedStyle(n); return [s.display, s.position, n.querySelectorAll('button').length]; })()")
        assert nav == ["flex", "sticky", 4]
        assert p.evaluate("getComputedStyle(document.querySelector('.params')).display") == "none"
        p.click('.bnav [data-tab-to="params"]')
        assert p.evaluate("getComputedStyle(document.querySelector('.params')).display") != "none"
        assert p.evaluate("getComputedStyle(document.querySelector('.kpis')).display") == "none"
        assert p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
        p.click('.bnav [data-tab-to="budget"]')
        assert p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
        n = p.evaluate("document.querySelectorAll('.fld').length")
        p.click('[data-act=lang][data-v=en]')
        assert p.evaluate("document.querySelector('.params h2').textContent") == "Parameters" and p.evaluate("document.querySelectorAll('.fld').length") == n
        assert p.evaluate("document.documentElement.lang") == "en"
        light = p.evaluate("getComputedStyle(document.body).backgroundColor")
        p.click('[data-act=theme][data-v=dark]')
        assert p.evaluate("getComputedStyle(document.body).backgroundColor") != light
    finally:
        ctx.close()
        srv.shutdown()
        srv.server_close()

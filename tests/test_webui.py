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


# ---------------------------------------------------------------- P3: the system diagram, the band table, the sweep, the baseline

_OVERFLOW = """() => { const out = []; document.querySelectorAll('svg.sys .blk').forEach(g => { const r = g.querySelector('rect').getBBox();
  g.querySelectorAll('.bl,.bo,.bt').forEach(t => { const tb = t.getBBox();
    const chip = [...g.querySelectorAll('.stag')].find(s => Math.abs(s.getBBox().y + 10 - (tb.y + tb.height - 3)) < 6);
    const lim = chip ? chip.getBBox().x - 2 : r.x + r.width - 6;
    if (tb.x + tb.width > lim) out.push([g.dataset.id, t.textContent]); }); }); return out; }"""


def _go(p, name):
    p.click(f"a[data-page={name}]")
    p.wait_for_selector(f".pnav a.on[data-page={name}]")                    # the page has been drawn, not only the address changed


def test_the_system_diagram_draws_the_runs_stages(page):
    _set(page, "lo.engine", "response")
    _set(page, "frontend.tx_power_dbm", 10)
    _settled(page)
    ref = guiutil.run_report({"lo.engine": "response", "frontend.tx_power_dbm": 10.0})
    _go(page, "system")
    page.wait_for_selector("svg.sys")
    stages = {s["id"]: s for s in ref["system"]["stages"]}
    assert page.evaluate("[...document.querySelectorAll('svg.sys .blk')].map(g => g.dataset.id)") == list(stages) and len(stages) == 25
    # the optional stages not in play are drawn as options; the rest are not
    assert set(page.evaluate("[...document.querySelectorAll('svg.sys .blk.dashed')].map(g => g.dataset.id)")) == {i for i, s in stages.items() if not s["active"]} == {"leak", "hpf", "dbf"}
    # numbers are the run's: the conducted power after the transmitter, the EIRP after the antenna, the resolution
    text = lambda i: page.evaluate(f"document.querySelector('svg.sys .blk[data-id={i}]').textContent")      # noqa: E731
    assert f"{stages['pa']['out']['value']:.2f} dBm" in text("pa") and f"{stages['txant']['out']['value']:.2f} dBm" in text("txant")
    assert f"{ref['metrics']['range_res_m'] * 100:.2f} cm" in text("rfft") and "✓" in text("comp")
    # a number edited on the page is assumed in the diagram too, and its chip opens the same note
    assert page.evaluate("document.querySelector('svg.sys .blk[data-id=pa] .stag').getAttribute('class')") == "stag t-assumed"
    page.click("svg.sys .blk[data-id=pa] .stag")
    assert "assumed" in page.evaluate("document.getElementById('pop').textContent") and "frontend.tx_power_dbm" in page.evaluate("document.getElementById('pop').textContent")
    page.keyboard.press("Escape")
    # no line runs out of its box, in either language
    assert page.evaluate(_OVERFLOW) == []
    page.click("[data-act=lang][data-v=en]")
    assert page.evaluate(_OVERFLOW) == [] and "conducted" in text("pa")
    page.click("[data-act=lang][data-v=zh]")
    # a stage and its row in the table below
    assert page.evaluate("document.querySelectorAll('.stages tbody tr').length") == 25
    page.click("svg.sys .blk[data-id=mix] rect")
    assert page.evaluate("[...document.querySelectorAll('.stages tr.hl')].map(r => r.dataset.id)") == ["mix"]
    assert page.evaluate("document.querySelectorAll('[data-chart=levels] circle').length") == 10          # now and full power, five points each


def test_a_band_row_can_be_taken_into_the_form(page):
    _set(page, "lo.engine", "response")
    _settled(page)
    ref = {r["id"]: r for r in guiutil.band_tradeoff({"lo.engine": "response"})["rows"]}
    _go(page, "bands")
    page.wait_for_selector(".btable tbody tr", timeout=60000)
    assert page.evaluate("[...document.querySelectorAll('.btable tbody tr')].map(r => r.dataset.band)") == list(ref)
    row = lambda i: page.evaluate(f"document.querySelector('.btable tr[data-band=\"{i}\"]').textContent")   # noqa: E731
    for i, r in ref.items():
        assert f"{r['metrics']['snr_cell_db']:.2f} dB" in row(i) and f"{r['detection_range_m']:.1f} m" in row(i) and f"{r['limit_dbm']:.0f} dBm" in row(i)
    assert "当前" in row("current") and page.evaluate("document.querySelectorAll('[data-chart=bands] svg').length") == 1
    # take the indoor band: the form is on that row's config, and the workbench shows that row's SNR
    page.click('.btable tr[data-band="57_59p4_indoor"] [data-act=useband]')
    page.wait_for_selector(".pnav a.on[data-page=workbench]")
    _settled(page)
    assert _tile(page, 1) == f"{ref['57_59p4_indoor']['metrics']['snr_cell_db']:.2f}dB" and _tile(page, 0) == "通过"
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    assert page.evaluate("document.querySelector('[data-path=\"band.sweep_hz\"]').value") == "2.4"
    assert page.evaluate("document.querySelector('[data-path=\"regulatory.scenario\"]').value") == "indoor"
    assert page.evaluate("document.querySelector('[data-fld=\"frontend.tx_backoff_db\"] .tag').textContent") == "assumed"
    # back on the band page the table is this config's: its first row is where the form now is
    _go(page, "bands")
    page.wait_for_function("(document.querySelector('.btable tr[data-band=current]') || {textContent: ''}).textContent.includes('57–59.4 GHz')", timeout=60000)
    # where the rule does not apply the page says why instead of a table
    _go(page, "workbench")
    _set(page, "band.kind", "77g_automotive")
    _settled(page)
    _go(page, "bands")
    page.wait_for_selector(".bp .empty", timeout=60000)
    assert "57-71 GHz" in page.evaluate("document.querySelector('.bp .empty').textContent") and not page.evaluate("!!document.querySelector('.btable')")


def test_a_sweep_runs_as_a_job_and_a_point_can_be_taken(page):
    _set(page, "lo.engine", "response")
    _settled(page)
    _go(page, "sweep")
    # the form starts at half to twice the current value
    assert page.evaluate("[document.querySelector('[data-sw=lo]').value, document.querySelector('[data-sw=hi]').value]") == ["2.5", "10"]
    page.fill("[data-sw=points]", "4")
    page.press("[data-sw=points]", "Enter")
    page.click("[data-act=sweeprun]")
    page.wait_for_selector("[data-chart=sweep] svg", timeout=60000)
    ref = guiutil.run_sweep({"lo.engine": "response"}, "target.range_m", 2.5, 10.0, 4)
    assert page.evaluate("document.querySelectorAll('[data-chart=sweep] .swp').length") == 4
    cells = page.evaluate("[...document.querySelectorAll('.swtbl tbody tr')].map(r => [r.cells[0].textContent, r.cells[1].textContent])")
    assert cells == [[f"{p['x']:g}", f"{p['metrics']['snr_cell_db']:.2f}"] for p in ref["points"]]
    # a value the config refuses is a cross with the schema's sentence, not a number
    page.select_option("[data-sw=path]", "frontend.tx_backoff_db")
    for k, v in (("lo", "-2"), ("hi", "2"), ("points", "3")):
        page.fill(f"[data-sw={k}]", v)
        page.press(f"[data-sw={k}]", "Enter")
    page.click("[data-act=sweeprun]")
    page.wait_for_selector("[data-chart=sweep] .swx", timeout=60000)
    assert page.evaluate("[document.querySelectorAll('[data-chart=sweep] .swx').length, document.querySelectorAll('[data-chart=sweep] .swp').length]") == [1, 2]
    assert "frontend.tx_backoff_db" in page.evaluate("document.querySelector('.swtbl tr.dim').textContent")
    # take the last point: the form holds it
    page.click(".swtbl tbody tr:last-child [data-act=usepoint]")
    page.wait_for_selector(".pnav a.on[data-page=workbench]")
    _settled(page)
    assert page.evaluate("document.querySelector('[data-path=\"frontend.tx_backoff_db\"]').value") == "2"
    assert "EIRP 20.0 / 14 dBm" in page.evaluate("document.querySelector('.kpi .d').textContent") and _tile(page, 0) != "通过"
    # the sweep on screen was made from other settings now, and says so
    _go(page, "sweep")
    assert "上一组参数" in page.evaluate("document.querySelector('.sp-page h2').textContent")


def test_a_pinned_baseline_shows_which_way_the_numbers_moved(page):
    _set(page, "lo.engine", "response")
    _settled(page)
    base = guiutil.run_report({"lo.engine": "response"})
    page.click("[data-act=pin]")
    page.wait_for_selector(".basechg")
    assert not page.evaluate("!!document.querySelector('.basetbl')")                                    # nothing moved yet
    _set(page, "target.range_m", 10)
    page.wait_for_selector(".basetbl")
    _settled(page)
    cmp_ = guiutil.run_report({"lo.engine": "response", "target.range_m": 10.0}, {"values": {"lo.engine": "response"}, "metrics": base["metrics"]})["baseline"]
    moved = [k for k, r in cmp_["metrics"].items() if r["delta"]]
    assert page.evaluate("[...document.querySelectorAll('.basetbl tbody tr')].map(r => r.dataset.metric)") == moved
    snr = cmp_["metrics"]["snr_cell_db"]
    row = page.evaluate("document.querySelector('.basetbl tr[data-metric=snr_cell_db]').textContent")
    assert f"{snr['base']:.2f}" in row and f"{snr['now']:.2f}" in row and f"−{abs(snr['delta']):.2f} dB" in row
    assert page.evaluate("document.querySelector('.basetbl tr[data-metric=snr_cell_db] .pill').dataset.verdict") == "worse" == snr["verdict"]
    assert "5 m → 10 m" in page.evaluate("document.querySelector('.basechg').textContent")
    _set(page, "target.range_m", 3)
    _settled(page)
    assert page.evaluate("document.querySelector('.basetbl tr[data-metric=snr_cell_db] .pill').dataset.verdict") == "better"
    page.click("[data-act=unpin]")
    assert not page.evaluate("!!document.querySelector('.basetbl')") and page.evaluate("!!document.querySelector('[data-act=pin]')")


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
        # the other pages at this width: four links in the header, nothing wider than the screen
        assert p.evaluate("document.querySelectorAll('.pnav a').length") == 4
        for name, sel in (("system", "svg.sys"), ("bands", ".bcards .bcard"), ("sweep", ".swform")):
            p.click(f"a[data-page={name}]")
            p.wait_for_selector(sel, timeout=90000)
            assert p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0, name
            if name == "bands":
                assert p.evaluate("getComputedStyle(document.querySelector('.btable')).display") == "none"       # cards, not the wide table
        p.click("a[data-page=workbench]")
        p.wait_for_selector(".pnav a.on[data-page=workbench]")
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

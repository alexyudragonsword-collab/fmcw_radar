"""Invariant #5: every external number carries its source; ``grep source:`` lists them all."""

import math
import subprocess

import pytest

from fmcw_radar import sources
from fmcw_radar.config import RadarConfig
from fmcw_radar.link import link_budget


def test_every_entry_is_tagged_and_cited():
    table = sources.all_entries()
    assert len(table) >= 20
    for key, e in table.items():
        assert e.source in sources.SOURCES, key
        assert e.cite, key
        if e.source == "survey":
            assert "未核实" in e.note, f"{key}: a survey entry's note must say it is unverified"
        if e.source == "assumed":
            assert "占位" in e.note, f"{key}: a placeholder's note must say it is one"
        if e.source in ("spec", "derived"):
            assert e.upstream, f"{key}: a figure read in the original here comes through spec_sources"


def test_grep_lists_every_sourced_number():
    """The command the docs promise -- ``grep -c "source:"`` on the table --
    counts exactly the entries: no header comment may contain the tag."""
    out = subprocess.run(["grep", "-c", "source:", str(sources.SOURCES_FILE)], capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(sources.all_entries())


def test_every_front_end_placeholder_exists_for_every_band():
    for band in ("60g_sensing", "77g_automotive"):
        for name in ("tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "rx_gain_db", "nf_db", "p1db_oob_dbm", "p1db_inband_dbm",
                     "rx_rapp_p", "lo_mult", "dco_pn_dbchz", "dco_pn_floor_dbchz", "tdc_res_s", "tdc_jitter_s", "tx_rx_isolation_db",
                     "rx_coupling_c1_db"):
            e = sources.frontend_placeholder(band, name)
            sourced = band == "60g_sensing" and name in SOURCED_60G
            assert e.placeholder != sourced and (e.source == "spec") == sourced, (band, name)


#: the 60 GHz figures read from originals through spec_sources (the five front-end figures since 0.2.8, the TDC since
#: 0.2.12); the 77 GHz band has none
SOURCED_60G = ("tx_power_dbm", "nf_db", "p1db_oob_dbm", "p1db_inband_dbm", "tx_rx_isolation_db", "tdc_res_s")


def test_sourced_front_end_figures_are_the_sibling_tables():
    """The five 60 GHz figures name their entry in spec_sources (the vendored
    copy) and equal it; loading refuses a table that disagrees, so a re-pin
    that moves the shared number cannot pass unnoticed.  A reference only
    looks a number up: the isolation's subtraction is a derived entry there."""
    import yaml

    from fmcw_radar.vendor import spec_sources as ss

    radar = ss.value("rx60.radar_iwr6843")
    assert ss.survey("rx60.radar_iwr6843").source == "spec"
    got = {n: sources.frontend_placeholder("60g_sensing", n) for n in SOURCED_60G}
    assert all(e.upstream.startswith("spec_sources:") and e.quote and e.section for e in got.values())
    assert got["tx_power_dbm"].value == radar["tx_power_dbm"] == 12.0 and got["nf_db"].value == radar["nf_db"] == 12.0
    assert got["p1db_oob_dbm"].value == radar["p1db_in_oob_dbm"] == -12.0
    fig = ss.value("rx60.radar_iwr6843_fig7_2")
    assert got["p1db_inband_dbm"].value == dict(zip(fig["gain_db"], fig["p1db_inband_dbm"]))[40.0] == -34.0
    iso = ss.value("isolation.tx_rx_tue2018")
    assert ss.survey("isolation.tx_rx_tue2018_no_ebg_min_db").source == "derived"
    assert got["tx_rx_isolation_db"].value == ss.value("isolation.tx_rx_tue2018_no_ebg_min_db") == 20.0 \
        == iso["with_ebg_db"] - iso["improvement_max_db"]
    assert sources.upstream_value("spec_sources:rx60.radar_iwr6843_fig7_2#p1db_inband_dbm@gain_db=48") == -42.0
    for bad in ("polar_tx:x#y",
                "mmw60_trx:rx60.radar_iwr6843#nf_db",                                             # the old library's name
                "spec_sources:rx60.radar_iwr6843_fig7_2#p1db_inband_dbm@gain_db=41",               # no such point
                "spec_sources:isolation.tx_rx_tue2018#with_ebg_db-improvement_max_db"):            # a subtraction: refused
        with pytest.raises(ValueError):
            sources.upstream_value(bad)
    # a table whose number has drifted from its upstream does not load
    doc = yaml.safe_load(sources.SOURCES_FILE.read_text(encoding="utf-8"))
    doc["entries"]["60g_sensing.nf_db"]["value"] = 10.0
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, allow_unicode=True)
    with pytest.raises(ValueError, match="is not its upstream's"):
        sources.load_sources(fh.name)


def test_oxygen_and_human_rcs_are_read_from_the_originals():
    """0.2.11, fmcw_radar#15: the oxygen attenuation is ITU-R P.676-13's
    line-by-line sum for dry air at sea level, at each band's centre (a
    derived figure: the original prints the lines and the formula, not the
    number); the human RCS is the low end of a ray-traced pedestrian's
    co-polar range.  The old 15.0 and 0.4 were the 60.81 GHz peak and
    (near enough) the total gaseous attenuation at 77 GHz."""
    from fmcw_radar.vendor import spec_sources as ss

    o60, o77 = sources.number("oxygen.60g_db_per_km"), sources.number("oxygen.77g_db_per_km")
    assert (o60.value, o60.source) == (14.651, "derived") and (o77.value, o77.source) == (0.091, "derived")
    curve = ss.value("itu_p676.gamma_o_dry_sea_level")
    assert ss.survey("itu_p676.gamma_o_dry_sea_level").source == "derived"
    assert dict(zip(curve["f_ghz"], curve["db_per_km"]))[60.0] == 14.651
    peak = ss.value("itu_p676.gamma_o_dry_sea_level_peak")
    assert peak == {"f_ghz": 60.81, "db_per_km": 15.06}                            # what the old 15 dB/km was
    assert RadarConfig().oxygen_db_per_km() == (14.651, "derived")
    human = sources.number("rcs.human_dbsm")
    assert (human.value, human.source) == (-10.0, "spec") and "ray tracing" in human.section
    assert ss.value("target_rcs.deep2019_pedestrian_77g")["co_pol_max_dbsm"] == 5.0
    # a derived entry without its upstream or its formula does not load
    with pytest.raises(ValueError, match="derived"):
        sources.SourcedNumber("x", 1.0, "dB", "derived", "cite", note="formula")
    with pytest.raises(ValueError, match="derived"):
        sources.SourcedNumber("x", 1.0, "dB", "derived", "cite", upstream="spec_sources:a.b")


def test_tdc_resolution_is_the_60_ghz_adpll_paper_and_its_floor_carries_over():
    """0.2.12, fmcw_radar#17: the 60 GHz band's TDC is Wu, Staszewski, Long
    (JSSC 2014): 12.2 ps.  Its loop divides CKV/32, ours reads the 15 GHz
    DCO; the time step carries over because the TDC's in-band floor,
    (2 pi)^2 / 12 (dt f_c)^2 / f_ref, depends on the step and the carrier
    alone.  Our own profile's TDC term at the carrier is the paper's formula
    (-77.54, printed -78; measured -77).  The jitter has no source in either
    paper spec_sources read; the 77 GHz band is another chip and keeps 5 ps."""
    from fmcw_radar.lo import LOProfile
    from fmcw_radar.vendor import spec_sources as ss

    tdc = sources.frontend_placeholder("60g_sensing", "tdc_res_s")
    paper = ss.value("adpll60.wu_jssc2014_tdc")
    assert (tdc.value, tdc.source) == (paper["tdc_res_s"], "spec") == (1.22e-11, "spec")
    cfg = RadarConfig()
    assert cfg.lo_value("tdc_res_s")[0] == 1.22e-11 and cfg.lo.fref_hz == paper["f_ref_mhz"] * 1e6
    floor = 10.0 * math.log10((2.0 * math.pi) ** 2 / 12.0 * (tdc.value * cfg.band.center_hz) ** 2 / cfg.lo.fref_hz)
    assert floor == pytest.approx(-77.54, abs=0.005) and round(floor) == paper["inband_pn_theory_dbc_hz"]
    assert floor - paper["inband_pn_meas_dbc_hz"] == pytest.approx(-0.5, abs=0.05)
    prof = LOProfile.from_config(cfg)
    assert 10.0 * math.log10(float(prof.components["tdc_quant"][0]) / 2.0) == pytest.approx(floor, abs=0.1)
    for band in ("60g_sensing", "77g_automotive"):
        jit = sources.frontend_placeholder(band, "tdc_jitter_s")
        assert jit.source == "assumed" and "neither gives it" in jit.cite
    assert sources.frontend_placeholder("77g_automotive", "tdc_res_s").value == 5.0e-12


def test_the_last_surveys_are_read_from_the_originals():
    """0.2.13, fmcw_radar#19: no entry is ``survey`` any more.  The car is
    ISO 19206-3's rear band's lower edge far out (20 - 10 dBsm, derived);
    the four window widths are Harris 1978 Table I (spec, the scipy
    ``sym=False`` windows this library uses).  The corner reflector is this
    library's own test target: Doerry's triangular-trihedral formula gives
    20 dBsm for a 15.6 cm interior edge at 60 GHz (the old "10 cm" is 12.2),
    and the same reflector is 2.17 dB more at 77 GHz."""
    from fmcw_radar.vendor import spec_sources as ss

    assert not [k for k, e in sources.all_entries().items() if e.source == "survey"]
    car = sources.number("rcs.car_dbsm")
    band = ss.value("target_rcs.iso19206_3_car_rear")
    assert (car.value, car.source) == (10.0, "derived") == (band["p_far_dbsm"] - band["half_width_db"], "derived")
    for name in ("rect", "hann", "hamming", "blackman"):
        w = sources.number(f"window.{name}_3db_bins")
        assert w.source == "spec" and w.value == ss.value(f"harris1978.{name}")["bw_3db_bins"]
    assert "exact" not in sources.number("window.blackman_3db_bins").cite
    cr = sources.number("rcs.corner_reflector_dbsm")
    assert (cr.value, cr.source) == (20.0, "assumed") and "4π a⁴ / (3 λ²)" in ss.value("target_rcs.trihedral_peak")["triangular"]

    def trihedral_dbsm(a_m, f_hz):
        lam = 299792458.0 / f_hz
        return 10.0 * math.log10(4.0 * math.pi * a_m ** 4 / (3.0 * lam ** 2))

    assert trihedral_dbsm(0.156, 60e9) == pytest.approx(cr.value, abs=0.05)
    assert trihedral_dbsm(0.138, 77e9) == pytest.approx(cr.value, abs=0.1)
    assert trihedral_dbsm(0.10, 60e9) == pytest.approx(12.2, abs=0.05)
    assert trihedral_dbsm(0.156, 77e9) - trihedral_dbsm(0.156, 60e9) == pytest.approx(20.0 * math.log10(77.0 / 60.0))


def test_vendored_shared_table_counts_its_tags():
    """spec_sources' grep guard on the copy vendored here: for each of its four
    tags, ``grep -c "source: <tag>"`` equals the entries carrying it (the
    attribution header added on top must not break the count)."""
    from fmcw_radar.vendor import spec_sources as ss

    files = ss.data_files()
    assert [f.name for f in files] == ["adpll60.yaml", "atmosphere.yaml", "frontend60.yaml", "radar_targets.yaml", "windows.yaml"]
    for f in files:
        assert ss.audit_tags(f) == []


def test_in_band_compression_follows_the_gain():
    """The radar chip's in-band input P1dB is a straight line against the
    receive gain, 1 dB down per dB (its Figure 7-2): the placeholder is the
    point at the band's gain and a config with another gain reads the line."""
    from fmcw_radar.config import apply_overrides
    from fmcw_radar.vendor import spec_sources as ss

    fig = ss.value("rx60.radar_iwr6843_fig7_2")
    for g, p in zip(fig["gain_db"], fig["p1db_inband_dbm"]):
        assert apply_overrides(RadarConfig(), {"frontend.rx_gain_db": g}).p1db_inband() == (p, "spec")
    assert apply_overrides(RadarConfig(), {"frontend.p1db_inband_dbm": -30.0, "frontend.rx_gain_db": 46.0}).p1db_inband() == (-30.0, "config")
    assert RadarConfig().frontend_value("p1db_oob_dbm") == (-12.0, "spec")                 # the other point does not move with the gain


def test_spec_source_needs_a_quote_and_survey_needs_unverified():
    with pytest.raises(ValueError, match="quoted"):
        sources.SourcedNumber("x", 1, "u", "spec", "cite")
    with pytest.raises(ValueError, match="source"):
        sources.SourcedNumber("x", 1, "u", "rumour", "cite")
    with pytest.raises(ValueError, match="未核实"):
        sources.SourcedNumber("x", 1, "u", "survey", "cite", note="read somewhere")
    ok = sources.SourcedNumber("x", 1, "u", "spec", "cite", quote="the text", section="3.1")
    assert ok.tag() == "1 u (source: spec)"


def test_budget_inputs_carry_their_sources():
    b = link_budget(RadarConfig())
    srcs = {k: s for k, (_, s) in b.inputs.items()}
    assert srcs["tx_power_dbm"] == "spec" and srcs["tx_gain_dbi"] == "assumed" and srcs["rcs_dbsm"] == "spec"
    assert srcs["oxygen_db_per_km"] == "derived"
    assert srcs["range_m"] == "config" and srcs["p1db_inband_dbm"] == "spec"


def test_code_does_not_hardcode_the_table():
    """No engine or config module spells a table value as a literal: the
    oxygen 15 dB/km (now 14.651), the -10 dBsm human, the 10 dBm placeholder power."""
    import re

    from conftest import REPO

    src = REPO / "src" / "fmcw_radar"
    hits = []
    for p in src.rglob("*.py"):
        if "vendor" in p.parts or p.name == "sources.py":
            continue
        code = _code_only(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"oxygen\w*\s*=\s*15\b|rcs\w*\s*=\s*-10\b|tx_power\w*\s*=\s*10\b", code):
            hits.append((p.relative_to(REPO), m.group(0)))
    assert not hits, hits


def _code_only(source: str) -> str:
    import io
    import tokenize

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            out.append(tok.string)
    return " ".join(out)

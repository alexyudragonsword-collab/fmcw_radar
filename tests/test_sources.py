"""Invariant #5: every external number carries its source; ``grep source:`` lists them all."""

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


#: the 60 GHz figures read from originals through mmw60_trx's sourced table (0.2.8); the 77 GHz band has none
SOURCED_60G = ("tx_power_dbm", "nf_db", "p1db_oob_dbm", "p1db_inband_dbm", "tx_rx_isolation_db")


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


def test_vendored_shared_table_counts_its_tags():
    """spec_sources' grep guard on the copy vendored here: for each of its four
    tags, ``grep -c "source: <tag>"`` equals the entries carrying it (the
    attribution header added on top must not break the count)."""
    from fmcw_radar.vendor import spec_sources as ss

    files = ss.data_files()
    assert [f.name for f in files] == ["atmosphere.yaml", "frontend60.yaml", "radar_targets.yaml"]
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

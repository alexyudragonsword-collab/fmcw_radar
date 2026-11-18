"""The regulatory check (link/compliance.py): 47 CFR 15.255(c)(2), the radar
limits of the 57-71 GHz band, read from spec_sources through sources.yaml.

The default radar sweeps 58-62 GHz at 22 dBm EIRP (12 dBm, a datasheet's,
plus a 10 dBi placeholder antenna).  The only tiers whose band holds that
sweep are the default one (10 dBm, and -10 dBm conducted), 57-64 GHz (14
dBm, with 25.5 ms of off-time in any 33 ms) and its outdoor variant (20
dBm, fixed or vehicular).  So it is 8 dB over, and its frame rate is capped
at 31.3 a second -- neither of which the library said before 0.2.19.
"""

import dataclasses

import numpy as np
import pytest
from conftest import REPO

from fmcw_radar import sources
from fmcw_radar.config import RadarConfig, apply_overrides, config_from_dict, config_to_dict, load_config
from fmcw_radar.engine.statistical import run_statistical
from fmcw_radar.link import compliance_check, link_budget
from fmcw_radar.link import compliance as comp
from fmcw_radar.report import report, to_markdown


def _tier(res, name):
    return next(t for t in res.tiers if t.tier == name)


# ---------------------------------------------------------------- the table

def test_every_limit_is_read_from_the_shared_table():
    """44 numbers, one entry each, every one ``spec`` and equal to the field
    of spec_sources' entry it names (loading refuses a table that differs)."""
    from fmcw_radar.vendor import spec_sources as ss

    mine = {k: e for k, e in sources.all_entries().items() if k.startswith("fcc15255.")}
    assert len(mine) == 44
    for key, e in mine.items():
        assert e.source == "spec" and e.quote and e.section and e.upstream.startswith("spec_sources:fcc15255."), key
        assert float(e.value) == float(ss.ref(e.upstream.split(":", 1)[1])), key
    for tier, (_, _, has_off, has_bw, has_cond) in comp.TIERS.items():
        assert f"fcc15255.{tier}.peak_eirp_dbm" in mine and f"fcc15255.{tier}.band_low_hz" in mine
        assert (f"fcc15255.{tier}.off_time_sum_min_s" in mine) == has_off
        assert (f"fcc15255.{tier}.max_bandwidth_hz" in mine) == has_bw
        assert (f"fcc15255.{tier}.peak_conducted_dbm" in mine) == has_cond
    assert sources.number("fcc15255.radar_57_64.peak_eirp_dbm").value == 14.0
    assert sources.number("fcc15255.radar_57_64.off_time_sum_min_s").value == 0.0255


def test_check_follows_the_table_not_a_literal(monkeypatch):
    """Break-check kept as a test: move one limit in the table the module
    reads and the verdict moves with it."""
    real = comp.number

    def moved(key):
        e = real(key)
        return dataclasses.replace(e, value=23.0) if key == "fcc15255.radar_57_64.peak_eirp_dbm" else e

    before = compliance_check(RadarConfig())
    assert _tier(before, "radar_57_64").eirp_margin_db == pytest.approx(-8.0)
    monkeypatch.setattr(comp, "number", moved)
    after = compliance_check(RadarConfig())
    assert _tier(after, "radar_57_64").eirp_margin_db == pytest.approx(+1.0) and after.eirp_cap_dbm == pytest.approx(22.0)


# ---------------------------------------------------------------- the default radar

def test_default_radar_is_8_db_over_and_its_frame_rate_is_capped():
    """58-62 GHz, 22 dBm, a 6.4 ms burst, no frame period, no scenario: the
    57-64 GHz tier governs (14 dBm).  Over by 8 dB whatever the frame
    period; the off-time cannot be judged without one, and wants at least
    33 - (7.5 - 6.4) = 31.9 ms between frame starts: 31.3 frames a second."""
    res = compliance_check(RadarConfig())
    assert res.applies and res.sweep_ghz == (58.0, 62.0) and res.eirp_dbm == 22.0 and res.conducted_dbm == 12.0
    assert res.frame_on_s == pytest.approx(6.4e-3) and res.frame_period_s is None and res.scenario is None
    assert [t.tier for t in res.tiers if t.in_band] == ["radar_default", "radar_57_64", "radar_57_64_outdoor"]
    assert [t.tier for t in res.tiers if t.usable] == ["radar_default", "radar_57_64"]          # the outdoor one: scenario not declared
    g = res.tier
    assert res.governing == "radar_57_64" and g.peak_eirp_limit_dbm == 14.0 and g.conducted_limit_dbm is None
    assert g.eirp_margin_db == pytest.approx(-8.0) and not g.power_ok and g.compliant is False
    assert g.off_time == "frame period not declared" and g.off_time_required_s == 0.0255 and g.off_time_have_s is None
    assert g.min_frame_period_s == pytest.approx(31.9e-3, abs=1e-6) and g.max_frame_rate_hz == pytest.approx(31.35, abs=0.01)
    assert res.eirp_cap_dbm == 14.0
    assert "over the limit by 8.0 dB" in res.verdict and "frame period not declared, cannot be judged" in res.verdict
    d = _tier(res, "radar_default")
    assert d.eirp_margin_db == pytest.approx(-12.0) and d.conducted_margin_db == pytest.approx(-22.0)
    assert _tier(res, "radar_57_64_outdoor").scenario == "not declared" and _tier(res, "radar_57_59p4_indoor").in_band is False
    assert len(res.readings) == 5 and res.sources == {"tx_power_dbm": "spec", "tx_gain_dbi": "assumed", "band": "spec"}


def test_off_time_follows_the_frame_period():
    """A frame every 33 ms leaves 26.6 ms off in the worst 33 ms: met.  At
    31.9 ms exactly met, at 31.8 ms not -- and then the 57-64 GHz tier is
    not open at all (it has no lower-power branch), the default tier is
    what is left: -10 dBm conducted, so 0 dBm EIRP through a 10 dBi antenna."""
    at = lambda t: compliance_check(apply_overrides(RadarConfig(), {"chirp.frame_period_s": t}))      # noqa: E731
    r33 = at(0.033)
    assert r33.tier.off_time == "met" and r33.tier.off_time_have_s == pytest.approx(26.6e-3) and r33.tier.compliant is False
    assert at(0.0319001).tier.off_time == "met" and at(0.0319001).governing == "radar_57_64"
    short = at(0.0318)
    assert _tier(short, "radar_57_64").off_time == "not met" and not _tier(short, "radar_57_64").usable
    assert short.governing == "radar_default" and short.eirp_cap_dbm == pytest.approx(0.0)
    assert "conducted power over its limit by 22.0 dB" in short.verdict
    # a compliant variant: the same radar through a 2 dBi antenna, a frame every 50 ms
    ok = compliance_check(apply_overrides(RadarConfig(), {"frontend.tx_gain_dbi": 2.0, "chirp.frame_period_s": 0.05}))
    assert ok.tier.compliant is True and ok.tier.eirp_margin_db == pytest.approx(0.0) and "EIRP within the limit" in ok.verdict
    # a burst longer than 33 - 25.5 = 7.5 ms can never meet it
    long = compliance_check(apply_overrides(RadarConfig(), {"chirp.n_chirps": 128}))
    assert _tier(long, "radar_57_64").off_time == "cannot be met" and long.governing == "radar_default"
    assert _tier(long, "radar_57_64_outdoor").min_frame_period_s is not None            # 12.8 ms fits the 16.5 ms tier


def test_off_time_counts_only_runs_of_two_milliseconds():
    """The flyback between chirps is not an off-time; an idle of 2 ms or more
    is.  And the evaluator is the brute-force minimum over every placement
    of the window."""
    c = apply_overrides(RadarConfig(), {"chirp.idle_s": 5e-6})
    assert comp.on_bursts(c, 0.002) == [(0.0, pytest.approx(64 * 100e-6 + 63 * 5e-6))]
    gappy = apply_overrides(RadarConfig(), {"chirp.n_chirps": 4, "chirp.duration_s": 1e-3, "chirp.idle_s": 3e-3})
    b = comp.on_bursts(gappy, 0.002)
    assert len(b) == 4 and b[1] == (pytest.approx(4e-3), pytest.approx(5e-3))
    just_under = apply_overrides(gappy, {"chirp.idle_s": 1.999e-3})
    assert len(comp.on_bursts(just_under, 0.002)) == 1

    rng = np.random.default_rng(3)
    for _ in range(12):
        n = int(rng.integers(1, 5))
        edges = np.sort(rng.uniform(0.0, 0.03, 2 * n))
        bursts = [(float(edges[2 * i]), float(edges[2 * i + 1])) for i in range(n)]
        period = float(edges[-1] + rng.uniform(0.0, 0.03))
        # brute force on a fine grid: merge gaps under 2 ms (the wrap too), then slide the window
        dt = 2e-6
        m = int(round(period / dt))
        t = (np.arange(3 * m) + 0.5) * dt
        on = np.zeros(t.size, bool)
        merged = []
        for r in range(-1, 4):
            for a, e in bursts:
                a, e = a + r * period, e + r * period
                if merged and a - merged[-1][1] < 0.002:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((a, e))
        for a, e in merged:
            on |= (t >= a) & (t < e)
        w = int(round(0.033 / dt))
        csum = np.concatenate([[0], np.cumsum(on)])
        worst = (csum[w:] - csum[:-w]).max() * dt
        assert comp.min_off_sum(bursts, period, 0.033, 0.002) == pytest.approx(0.033 - worst, abs=5 * dt)


# ---------------------------------------------------------------- scenario and band

def test_scenario_opens_and_closes_tiers():
    """Outdoors and fixed, with a frame every 33 ms: the 20 dBm tier governs
    and the radar is 2 dB over.  Indoors the same sweep stays on 14 dBm.
    'outdoor' alone is not 'fixed or vehicular'."""
    base = apply_overrides(RadarConfig(), {"chirp.frame_period_s": 0.033})
    fixed = compliance_check(apply_overrides(base, {"regulatory.scenario": "outdoor_fixed"}))
    assert fixed.governing == "radar_57_64_outdoor" and fixed.tier.eirp_margin_db == pytest.approx(-2.0) and fixed.eirp_cap_dbm == 20.0
    assert fixed.tier.off_time == "met" and fixed.tier.min_frame_period_s == pytest.approx(14.65e-3, abs=1e-6)
    assert compliance_check(apply_overrides(base, {"regulatory.scenario": "vehicular"})).governing == "radar_57_64_outdoor"
    for scen in ("indoor", "outdoor", "uav"):
        r = compliance_check(apply_overrides(base, {"regulatory.scenario": scen}))
        assert r.governing == "radar_57_64" and _tier(r, "radar_57_64_outdoor").scenario == "not met", scen
    with pytest.raises(ValueError):
        apply_overrides(RadarConfig(), {"regulatory.scenario": "in a car park"})


@pytest.mark.parametrize("lo, hi, scenario, tier, limit, off", [
    (57.0, 59.4, "indoor", "radar_57_59p4_indoor", 20.0, "none required"),
    (57.0, 59.4, "outdoor", "radar_57_59p4_outdoor", 30.0, "none required"),
    (57.0, 59.4, None, "radar_57_61p56_off_time", 20.0, "frame period not declared"),
    (57.0, 61.56, None, "radar_57_61p56_off_time", 20.0, "frame period not declared"),
    (57.0, 64.0, None, "radar_57_64", 14.0, "frame period not declared"),
    (57.0, 64.0, "outdoor_fixed", "radar_57_64_outdoor", 20.0, "frame period not declared"),
    (60.0, 64.0, "uav", "radar_uav_60_64", 20.0, "frame period not declared"),
    (61.0, 61.5, None, "radar_61_61p5", 43.0, "none required"),
    (62.0, 64.0, None, "radar_57_64", 14.0, "frame period not declared"),
])
def test_the_sweep_picks_the_tiers_whose_band_holds_it(lo, hi, scenario, tier, limit, off):
    """A tier is open only to a sweep that lies inside its band ('limit their
    operation to all or part of the specified frequency band'); among the
    open ones the highest limit governs.  (The config's 60 GHz band window
    is 57-64 GHz, so the default tier is never the only one in band here.)"""
    c = apply_overrides(RadarConfig(), {"band.center_hz": 0.5e9 * (lo + hi), "band.sweep_hz": 1e9 * (hi - lo),
                                        "regulatory.scenario": scenario})
    r = compliance_check(c)
    assert r.applies and r.governing == tier and r.tier.peak_eirp_limit_dbm == limit and r.tier.off_time == off
    assert all(t.in_band == (lo >= t.band_ghz[0] - 1e-9 and hi <= t.band_ghz[1] + 1e-9) for t in r.tiers)


def test_a_sweep_one_megahertz_over_an_edge_loses_the_tier():
    in_ = compliance_check(apply_overrides(RadarConfig(), {"band.center_hz": 59.28e9, "band.sweep_hz": 4.56e9}))
    out = compliance_check(apply_overrides(RadarConfig(), {"band.center_hz": 59.2805e9, "band.sweep_hz": 4.561e9}))
    assert _tier(in_, "radar_57_61p56_off_time").in_band and not _tier(out, "radar_57_61p56_off_time").in_band
    assert in_.governing == "radar_57_61p56_off_time" and out.governing == "radar_57_64"
    wide = compliance_check(apply_overrides(RadarConfig(), {"band.center_hz": 61.25e9, "band.sweep_hz": 0.6e9}))
    assert not _tier(wide, "radar_61_61p5").usable                                      # 600 MHz does not fit 61.0-61.5


def test_77_ghz_is_not_this_sections_business():
    """76-81 GHz is outside 57-71 GHz: the check answers 'not applicable' and
    applies none of the 60 GHz limits -- no tier, no cap, no second column."""
    cfg = load_config(REPO / "configs" / "radar_77g_automotive.yaml")
    r = compliance_check(cfg)
    assert not r.applies and r.verdict == "not applicable" and r.tiers == [] and r.governing is None and r.eirp_cap_dbm is None
    assert "outside the 57-71 GHz band" in r.why
    small = apply_overrides(cfg, {"chirp.n_chirps": 4})
    st = run_statistical(small)
    assert st.budget_capped is None and st.compliance["applies"] is False
    md = to_markdown(report(small, st))
    assert "Not applicable: the sweep 76.5-78.5 GHz lies outside" in md and "at the regulatory limit" not in md


def test_tdm_mimo_radiates_one_transmitter_at_a_time():
    """The rule says nothing on adding transmit channels; this library's MIMO
    is TDM, so the EIRP is one transmitter's and the frame is the same
    6.4 ms burst.  The x10 and the dithered configs are the default radar."""
    ref = compliance_check(load_config(REPO / "configs" / "radar_60g_sensing.yaml")).as_dict()
    mimo_cfg = load_config(REPO / "configs" / "radar_60g_mimo.yaml")
    mimo = compliance_check(mimo_cfg)
    assert mimo_cfg.mimo.n_tx == 2 and mimo.n_tx == 2 and mimo.eirp_dbm == 22.0 and mimo.frame_on_s == pytest.approx(6.4e-3)
    assert mimo.governing == "radar_57_64" and mimo.tier.eirp_margin_db == pytest.approx(-8.0)
    for name in ("radar_60g_x10lo", "radar_60g_dither"):
        got = compliance_check(load_config(REPO / "configs" / f"{name}.yaml")).as_dict()
        assert got == ref, name


# ---------------------------------------------------------------- the capped budget

def test_capped_budget_changes_the_eirp_and_what_follows_from_it():
    cfg = RadarConfig()
    plain = link_budget(cfg)
    assert dataclasses.asdict(link_budget(cfg, eirp_cap_dbm=None)) == dataclasses.asdict(plain)
    assert dataclasses.asdict(link_budget(cfg, eirp_cap_dbm=30.0)).items() >= {"eirp_dbm": 22.0, "snr_cell_db": plain.snr_cell_db}.items()
    cap = link_budget(cfg, eirp_cap_dbm=14.0)
    assert cap.eirp_dbm == 14.0 and cap.pr_dbm == pytest.approx(plain.pr_dbm - 8.0)
    assert cap.snr_cell_db == pytest.approx(plain.snr_cell_db - 8.0, abs=1e-9) and cap.cn0_dbhz == pytest.approx(plain.cn0_dbhz - 8.0)
    for same in ("path_loss_db", "atmos_loss_db", "rcs_dbsm", "n0_thermal_dbm_hz", "n0_total_adc_dbm_hz", "window_loss_db"):
        assert getattr(cap, same) == getattr(plain, same), same
    assert cap.inputs["eirp_cap_dbm"] == (14.0, "spec") and "eirp_cap_dbm" not in plain.inputs


def test_under_the_cap_the_tx_antenna_gain_stops_mattering():
    """Written before it was run (0.2.19, ROADMAP 'upstream' item 1).  The
    default radar is over the 14 dBm tier with any transmit antenna of 2 dBi
    or more (12 + 2 = 14).  Held to the limit, its EIRP is 14 dBm whatever
    ``tx_gain_dbi`` is -- 2, 6 or 10 dBi give the same SNR to the last bit,
    while the configured SNR moves 4 dB a step.  The receive antenna still
    counts dB for dB.  Under the 20 dBm outdoor tier the cap bites only from
    8 dBi up: 2 and 6 dBi are 6 and 2 dB under the capped 10 dBi."""
    def snrs(**ov):
        st = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 4, "lo.engine": "ideal", **ov}))
        return st.snr_cell_db, st.budget_capped.snr_cell_db, st.budget_capped.eirp_dbm

    by_gain = {g: snrs(**{"frontend.tx_gain_dbi": g}) for g in (2.0, 6.0, 10.0)}
    assert [by_gain[g][2] for g in (2.0, 6.0, 10.0)] == [14.0, 14.0, 14.0]
    assert by_gain[2.0][1] == by_gain[6.0][1] == by_gain[10.0][1]                      # bit for bit
    assert by_gain[6.0][0] - by_gain[2.0][0] == pytest.approx(4.0, abs=1e-9)
    assert by_gain[10.0][0] - by_gain[6.0][0] == pytest.approx(4.0, abs=1e-9)
    assert by_gain[2.0][1] == pytest.approx(by_gain[2.0][0], abs=1e-12)                 # at 2 dBi the radar is exactly at the limit
    assert by_gain[10.0][1] == pytest.approx(by_gain[10.0][0] - 8.0, abs=1e-9)
    rx8, rx10 = snrs(**{"frontend.rx_gain_dbi": 8.0}), snrs(**{"frontend.rx_gain_dbi": 10.0})
    assert rx10[1] - rx8[1] == pytest.approx(2.0, abs=1e-9)
    outdoor = {"regulatory.scenario": "outdoor_fixed", "chirp.frame_period_s": 0.033}
    o = {g: snrs(**{"frontend.tx_gain_dbi": g, **outdoor}) for g in (2.0, 6.0, 10.0)}
    assert [o[g][2] for g in (2.0, 6.0, 10.0)] == [14.0, 18.0, 20.0]
    assert o[10.0][1] - o[2.0][1] == pytest.approx(6.0, abs=1e-9) and o[10.0][1] - o[6.0][1] == pytest.approx(2.0, abs=1e-9)


# ---------------------------------------------------------------- config and report

def test_frame_period_is_declared_validated_and_read_by_nothing_else():
    c = RadarConfig()
    assert c.chirp.frame_period_s is None and c.regulatory.scenario is None and c.chirp.frame_on_s == pytest.approx(6.4e-3)
    with pytest.raises(ValueError, match="shorter than the frame"):
        apply_overrides(c, {"chirp.frame_period_s": 6.0e-3})
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            apply_overrides(c, {"chirp.frame_period_s": bad})
    d = apply_overrides(c, {"chirp.frame_period_s": 0.05, "regulatory.scenario": "indoor"})
    assert config_from_dict(config_to_dict(d)) == d
    # nothing in the signal processing reads it: the statistical result is the same but for the compliance block
    small = {"chirp.n_chirps": 4}
    a, b = run_statistical(apply_overrides(c, small)), run_statistical(apply_overrides(d, small))
    assert a.snr_cell_db == b.snr_cell_db and a.pn_rms_rad == b.pn_rms_rad and a.cfar == b.cfar and a.nonlinearity == b.nonlinearity
    assert dataclasses.asdict(a.budget) == dataclasses.asdict(b.budget)
    assert a.compliance["frame_period_s"] is None and b.compliance["frame_period_s"] == 0.05


def test_report_carries_the_check_and_the_second_column():
    cfg = apply_overrides(RadarConfig(), {"lo.engine": "ideal"})                        # the default frame, without the chirp engine's time
    st = run_statistical(cfg)
    rep = report(cfg, st)
    assert [r["value"] for r in rep["budget"]] == [v for _, v, _ in st.budget.as_rows()]             # the old column, untouched
    assert rep["budget"][0] == {"term": "EIRP", "value": 22.0, "unit": "dBm"} and rep["budget_capped"][0]["value"] == 14.0
    K = rep["compliance"]
    assert K["applies"] and K["governing"] == "radar_57_64" and K["limit_dbm"] == 14.0 and K["eirp_margin_db"] == pytest.approx(-8.0)
    assert K["compliant"] is False and K["snr_cell_configured_db"] - K["snr_cell_capped_db"] == pytest.approx(8.0, abs=1e-9)
    assert K["max_frame_rate_hz"] == pytest.approx(31.35, abs=0.01) and len(K["tiers"]) == 9
    assert all(set(t["sources"].values()) == {"spec"} for t in K["tiers"])
    md = to_markdown(rep)
    for want in ("## Regulatory check (47 CFR 15.255(c)(2))", "| term | as configured | at the regulatory limit | unit |",
                 "| EIRP | 22.00 | 14.00 | dBm |", "**57.0-64.0 GHz, with off-time**, peak EIRP 14 dBm (source: spec)",
                 "EIRP over the limit by 8.0 dB", "frame period not declared, cannot be judged",
                 "at least 31.90 ms, at most 31.3 frames a second", "conducted 12.0 dBm (source: spec) + antenna (source: assumed)",
                 "What the rule leaves open, and how it is read here:"):
        assert want in md, want
    mimo = apply_overrides(load_config(REPO / "configs" / "radar_60g_mimo.yaml"), {"chirp.n_chirps": 4})
    assert "2 transmitters in turn (TDM): one on at a time" in to_markdown(report(mimo, run_statistical(mimo)))

"""The regulatory check (link/compliance.py): 47 CFR 15.255(c)(2), the radar
limits of the 57-71 GHz band, read from spec_sources through sources.yaml.

The radar sweeps 58-62 GHz; its transmitter can put out 12 dBm (a
datasheet's) into a 10 dBi placeholder antenna, 22 dBm EIRP.  The only tiers
whose band holds that sweep are the default one (10 dBm, and -10 dBm
conducted), 57-64 GHz (14 dBm, with 25.5 ms of off-time in any 33 ms) and
its outdoor variant (20 dBm, fixed or vehicular).  So at full power it is
8 dB over, and its frame rate is capped at 31.3 a second -- neither of which
the library said before 0.2.19.  Since 0.2.20 the default config is that
radar made compliant: backed off 8 dB to 14 dBm, a frame every 1/30 s.

``FULL`` is the radar of 0.2.19 (no backoff, no frame period declared): the
tests of the check's mechanics run on it, where the limits bite.
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


FULL = apply_overrides(RadarConfig(), {"frontend.tx_backoff_db": 0.0, "chirp.frame_period_s": None})


def _tier(res, name):
    return next(t for t in res.tiers if t.tier == name)


# ---------------------------------------------------------------- the table

def test_every_limit_is_read_from_the_shared_table():
    """44 numbers, one entry each, every one ``spec`` and equal to the field
    of spec_sources' entry it names (loading refuses a table that differs)."""
    from fmcw_radar.vendor import spec_sources as ss

    mine = {k: e for k, e in sources.all_entries().items() if k.startswith("fcc15255.")}
    # 44 numbers, and (0.2.35) two statements read word for word: what is measured, and where that requirement stands
    said = {k: e for k, e in mine.items() if k.startswith("fcc15255.radar_occupied_bandwidth.")}
    assert len(mine) == 46 and sorted(said) == ["fcc15255.radar_occupied_bandwidth.codified", "fcc15255.radar_occupied_bandwidth.quantity"]
    assert all(isinstance(e.value, str) for e in said.values()) and all(not isinstance(e.value, str) for k, e in mine.items() if k not in said)
    for key, e in mine.items():
        assert e.source == "spec" and e.quote and e.section and e.upstream.startswith("spec_sources:fcc15255."), key
        up = ss.ref(e.upstream.split(":", 1)[1])
        assert (e.value == up) if key in said else (float(e.value) == float(up)), key
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
    real = sources.number                                    # check(cfg) reads the library's table through it, at call time

    def moved(key):
        e = real(key)
        return dataclasses.replace(e, value=23.0) if key == "fcc15255.radar_57_64.peak_eirp_dbm" else e

    before = compliance_check(FULL)
    assert _tier(before, "radar_57_64").eirp_margin_db == pytest.approx(-8.0)
    monkeypatch.setattr(sources, "number", moved)
    after = compliance_check(FULL)
    assert _tier(after, "radar_57_64").eirp_margin_db == pytest.approx(+1.0) and after.eirp_cap_dbm == pytest.approx(22.0)


# ---------------------------------------------------------------- the default radar

def test_default_config_is_compliant_at_the_limit():
    """0.2.20, the user's choice (a): keep 58-62 GHz, come down to the 14 dBm
    of the 57-64 GHz tier, declare a frame every 1/30 s.  The backoff is the
    band's ``tx_backoff_db`` and it is exactly what the limit asks of the
    other two placeholders -- 12 + 10 - 14 = 8 dB, inside the 26 dB backoff
    range the datasheet behind the 12 dBm quotes -- so the margin is 0.0 dB
    and the off-time 33 - 6.4 = 26.6 ms of the 25.5 required."""
    cfg = RadarConfig()
    bo = sources.frontend_placeholder("60g_sensing", "tx_backoff_db")
    pt = sources.frontend_placeholder("60g_sensing", "tx_power_dbm")
    gt = sources.frontend_placeholder("60g_sensing", "tx_gain_dbi")
    limit = sources.number("fcc15255.radar_57_64.peak_eirp_dbm").value
    assert bo.source == "assumed" and bo.value == pytest.approx(pt.value + gt.value - limit) and bo.value == 8.0
    assert "Power backoff range 26 dB" in pt.quote and 0.0 <= bo.value <= 26.0
    assert cfg.frontend.tx_backoff_db is None and cfg.tx_conducted_dbm() == 4.0 and cfg.chirp.frame_period_s == pytest.approx(1.0 / 30.0)
    res = compliance_check(cfg)
    assert res.tx_power_dbm == 12.0 and res.tx_backoff_db == 8.0 and res.conducted_dbm == 4.0 and res.eirp_dbm == 14.0
    g = res.tier
    assert res.governing == "radar_57_64" and g.eirp_margin_db == pytest.approx(0.0) and g.power_ok and g.compliant is True
    assert g.off_time == "met" and g.off_time_have_s == pytest.approx(26.6e-3) and g.off_time_required_s == 0.0255
    assert res.eirp_cap_dbm == 14.0 and res.verdict == "EIRP within the limit (margin +0.0 dB); off-time met (26.60 ms of the 25.5 ms required)"
    assert res.sources == {"tx_power_dbm": "spec", "tx_backoff_db": "assumed", "tx_gain_dbi": "assumed", "band": "spec"}
    # the cap does nothing to a radar already at it: the two columns of the budget are the same number
    assert link_budget(cfg, eirp_cap_dbm=res.eirp_cap_dbm).snr_cell_db == link_budget(cfg).snr_cell_db
    assert link_budget(cfg).snr_cell_db == pytest.approx(link_budget(FULL).snr_cell_db - 8.0, abs=1e-9)
    assert link_budget(cfg).snr_cell_db == pytest.approx(43.34, abs=0.01)
    # the default tier is still there and still 4 dB (EIRP) and 14 dB (conducted) short of it: the 57-64 GHz tier is the one that carries it
    d = _tier(res, "radar_default")
    assert d.eirp_margin_db == pytest.approx(-4.0) and d.conducted_margin_db == pytest.approx(-14.0)
    # one more frame a second than 31.3 and the off-time is gone, and with it the tier
    fast = compliance_check(apply_overrides(cfg, {"chirp.frame_period_s": 1.0 / 32.0}))
    assert _tier(fast, "radar_57_64").off_time == "not met" and fast.governing == "radar_default" and fast.tier.compliant is False


def test_backoff_is_a_reduction_and_reaches_everything_computed_from_the_power():
    """``tx_backoff_db`` is not a compliance-only number: the link budget and
    the leakage budget are computed at ``tx_power - tx_backoff``.  It cannot
    be negative, and an explicit ``tx_power_dbm`` is still backed off by the
    band's 8 dB unless the backoff is set too."""
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            apply_overrides(RadarConfig(), {"frontend.tx_backoff_db": bad})
    a, b = link_budget(RadarConfig()), link_budget(apply_overrides(RadarConfig(), {"frontend.tx_backoff_db": 3.0}))
    assert a.inputs["tx_backoff_db"] == (8.0, "assumed") and b.inputs["tx_backoff_db"] == (3.0, "config")
    assert b.eirp_dbm == 19.0 and b.snr_cell_db == pytest.approx(a.snr_cell_db + 5.0, abs=1e-9)
    explicit = apply_overrides(RadarConfig(), {"frontend.tx_power_dbm": 10.0})
    assert explicit.tx_conducted_dbm() == 2.0 and link_budget(explicit).eirp_dbm == 12.0
    mimo = load_config(REPO / "configs" / "radar_60g_mimo.yaml")
    lk0 = run_statistical(apply_overrides(mimo, {"chirp.n_chirps": 4, "frontend.tx_backoff_db": 0.0})).leakage
    lk8 = run_statistical(apply_overrides(mimo, {"chirp.n_chirps": 4})).leakage
    assert lk8.p1db_margin_db - lk0.p1db_margin_db == pytest.approx(8.0, abs=1e-9)          # the leakage is 8 dB down too
    assert lk0.p1db_margin_db == pytest.approx(-4.0, abs=0.01) and lk8.compression_signal_db > lk0.compression_signal_db
    c77 = load_config(REPO / "configs" / "radar_77g_automotive.yaml")
    assert c77.frontend_value("tx_backoff_db") == (0.0, "assumed") and c77.tx_conducted_dbm() == c77.frontend_value("tx_power_dbm")[0]
    d = apply_overrides(RadarConfig(), {"frontend.tx_backoff_db": 2.5})
    assert config_from_dict(config_to_dict(d)) == d


def test_full_power_radar_is_8_db_over_and_its_frame_rate_is_capped():
    """The radar of 0.2.19: 58-62 GHz, 22 dBm, a 6.4 ms burst, no frame
    period, no scenario: the 57-64 GHz tier governs (14 dBm).  Over by 8 dB
    whatever the frame period; the off-time cannot be judged without one,
    and wants at least 33 - (7.5 - 6.4) = 31.9 ms between frame starts:
    31.3 frames a second."""
    res = compliance_check(FULL)
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
    assert len(res.readings) == 6 and res.sources == {"tx_power_dbm": "spec", "tx_backoff_db": "config", "tx_gain_dbi": "assumed", "band": "spec"}


def test_off_time_follows_the_frame_period():
    """A frame every 33 ms leaves 26.6 ms off in the worst 33 ms: met.  At
    31.9 ms exactly met, at 31.8 ms not -- and then the 57-64 GHz tier is
    not open at all (it has no lower-power branch), the default tier is
    what is left: -10 dBm conducted, so 0 dBm EIRP through a 10 dBi antenna."""
    at = lambda t: compliance_check(apply_overrides(FULL, {"chirp.frame_period_s": t}))      # noqa: E731
    r33 = at(0.033)
    assert r33.tier.off_time == "met" and r33.tier.off_time_have_s == pytest.approx(26.6e-3) and r33.tier.compliant is False
    assert at(0.0319001).tier.off_time == "met" and at(0.0319001).governing == "radar_57_64"
    short = at(0.0318)
    assert _tier(short, "radar_57_64").off_time == "not met" and not _tier(short, "radar_57_64").usable
    assert short.governing == "radar_default" and short.eirp_cap_dbm == pytest.approx(0.0)
    assert "conducted power over its limit by 22.0 dB" in short.verdict
    # a compliant variant: the same radar through a 2 dBi antenna, a frame every 50 ms
    ok = compliance_check(apply_overrides(FULL, {"frontend.tx_gain_dbi": 2.0, "chirp.frame_period_s": 0.05}))
    assert ok.tier.compliant is True and ok.tier.eirp_margin_db == pytest.approx(0.0) and "EIRP within the limit" in ok.verdict
    # a burst longer than 33 - 25.5 = 7.5 ms can never meet it
    long = compliance_check(apply_overrides(FULL, {"chirp.n_chirps": 128}))
    assert _tier(long, "radar_57_64").off_time == "cannot be met" and long.governing == "radar_default"
    assert _tier(long, "radar_57_64_outdoor").min_frame_period_s is not None            # 12.8 ms fits the 16.5 ms tier


def test_off_time_counts_only_runs_of_two_milliseconds():
    """The flyback between chirps is not an off-time; an idle of 2 ms or more
    is.  And the evaluator is the brute-force minimum over every placement
    of the window."""
    c = apply_overrides(FULL, {"chirp.idle_s": 5e-6})
    assert comp.on_bursts(c, 0.002) == [(0.0, pytest.approx(64 * 100e-6 + 63 * 5e-6))]
    gappy = apply_overrides(FULL, {"chirp.n_chirps": 4, "chirp.duration_s": 1e-3, "chirp.idle_s": 3e-3})
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
    base = apply_overrides(FULL, {"chirp.frame_period_s": 0.033})
    fixed = compliance_check(apply_overrides(base, {"regulatory.scenario": "outdoor_fixed"}))
    assert fixed.governing == "radar_57_64_outdoor" and fixed.tier.eirp_margin_db == pytest.approx(-2.0) and fixed.eirp_cap_dbm == 20.0
    assert fixed.tier.off_time == "met" and fixed.tier.min_frame_period_s == pytest.approx(14.65e-3, abs=1e-6)
    assert compliance_check(apply_overrides(base, {"regulatory.scenario": "vehicular"})).governing == "radar_57_64_outdoor"
    for scen in ("indoor", "outdoor", "uav"):
        r = compliance_check(apply_overrides(base, {"regulatory.scenario": scen}))
        assert r.governing == "radar_57_64" and _tier(r, "radar_57_64_outdoor").scenario == "not met", scen
    with pytest.raises(ValueError):
        apply_overrides(FULL, {"regulatory.scenario": "in a car park"})


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
    c = apply_overrides(FULL, {"band.center_hz": 0.5e9 * (lo + hi), "band.sweep_hz": 1e9 * (hi - lo),
                                        "regulatory.scenario": scenario})
    r = compliance_check(c)
    assert r.applies and r.governing == tier and r.tier.peak_eirp_limit_dbm == limit and r.tier.off_time == off
    assert all(t.in_band == (lo >= t.band_ghz[0] - 1e-9 and hi <= t.band_ghz[1] + 1e-9) for t in r.tiers)


def test_a_sweep_one_megahertz_over_an_edge_loses_the_tier():
    in_ = compliance_check(apply_overrides(FULL, {"band.center_hz": 59.28e9, "band.sweep_hz": 4.56e9}))
    out = compliance_check(apply_overrides(FULL, {"band.center_hz": 59.2805e9, "band.sweep_hz": 4.561e9}))
    assert _tier(in_, "radar_57_61p56_off_time").in_band and not _tier(out, "radar_57_61p56_off_time").in_band
    assert in_.governing == "radar_57_61p56_off_time" and out.governing == "radar_57_64"
    wide = compliance_check(apply_overrides(FULL, {"band.center_hz": 61.25e9, "band.sweep_hz": 0.6e9}))
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
    6.4 ms burst: backed off like the default radar, it is compliant like
    it.  The x10 and the dithered configs are the default radar."""
    ref = compliance_check(load_config(REPO / "configs" / "radar_60g_sensing.yaml")).as_dict()
    mimo_cfg = load_config(REPO / "configs" / "radar_60g_mimo.yaml")
    mimo = compliance_check(mimo_cfg)
    assert mimo_cfg.mimo.n_tx == 2 and mimo.n_tx == 2 and mimo.eirp_dbm == 14.0 and mimo.frame_on_s == pytest.approx(6.4e-3)
    assert mimo.governing == "radar_57_64" and mimo.tier.eirp_margin_db == pytest.approx(0.0) and mimo.tier.compliant is True
    assert ref["compliant"] is True and ref["tx_backoff_db"] == 8.0
    for name in ("radar_60g_x10lo", "radar_60g_dither"):
        got = compliance_check(load_config(REPO / "configs" / f"{name}.yaml")).as_dict()
        assert got == ref, name


# ---------------------------------------------------------------- the capped budget

def test_capped_budget_changes_the_eirp_and_what_follows_from_it():
    cfg = FULL
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
    full-power radar is over the 14 dBm tier with any transmit antenna of 2 dBi
    or more (12 + 2 = 14).  Held to the limit, its EIRP is 14 dBm whatever
    ``tx_gain_dbi`` is -- 2, 6 or 10 dBi give the same SNR to the last bit,
    while the configured SNR moves 4 dB a step.  The receive antenna still
    counts dB for dB.  Under the 20 dBm outdoor tier the cap bites only from
    8 dBi up: 2 and 6 dBi are 6 and 2 dB under the capped 10 dBi."""
    def snrs(**ov):
        st = run_statistical(apply_overrides(FULL, {"chirp.n_chirps": 4, "lo.engine": "ideal", **ov}))
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
    c = FULL
    assert c.chirp.frame_period_s is None and c.regulatory.scenario is None and c.chirp.frame_on_s == pytest.approx(6.4e-3)
    assert RadarConfig().chirp.frame_period_s == pytest.approx(1.0 / 30.0) and RadarConfig().regulatory.scenario is None
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
    cfg = apply_overrides(FULL, {"lo.engine": "ideal"})                                # the full-power frame, without the chirp engine's time
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
                 "at least 31.90 ms, at most 31.3 frames a second", "conducted 12.0 dBm (12 dBm, source: spec, backed off 0 dB, source: config) + antenna (source: assumed)",
                 "What the rule leaves open, and how it is read here:"):
        assert want in md, want
    mimo = apply_overrides(load_config(REPO / "configs" / "radar_60g_mimo.yaml"), {"chirp.n_chirps": 4})
    assert "2 transmitters in turn (TDM): one on at a time" in to_markdown(report(mimo, run_statistical(mimo)))
    # the default radar's report: at the limit, the two columns equal, the off-time judged
    dflt = apply_overrides(RadarConfig(), {"lo.engine": "ideal"})
    rep_d = report(dflt, run_statistical(dflt))
    Kd = rep_d["compliance"]
    assert Kd["compliant"] is True and Kd["eirp_margin_db"] == pytest.approx(0.0) and Kd["snr_cell_configured_db"] == Kd["snr_cell_capped_db"]
    md_d = to_markdown(rep_d)
    for want in ("| EIRP | 14.00 | 14.00 | dBm |", "EIRP within the limit (margin +0.0 dB)", "off-time met (26.60 ms of the 25.5 ms required)",
                 "conducted 4.0 dBm (12 dBm, source: spec, backed off 8 dB, source: assumed) + antenna (source: assumed)",
                 "frame period 33.3333 ms"):
        assert want in md_d, want


# ---------------------------------------------------------------- 0.2.33 (fmcw_radar#42): the rule on explicit numbers

def _explicit(cfg, **kw):
    """check(cfg)'s own numbers, taken out by hand."""
    c = cfg.chirp
    pt, s_pt = cfg.frontend_value("tx_power_dbm")
    bo, s_bo = cfg.frontend_value("tx_backoff_db")
    gt, s_gt = cfg.frontend_value("tx_gain_dbi")
    args = dict(number=sources.number, tx_backoff_db=bo, frame_period_s=c.frame_period_s, scenario=cfg.regulatory.scenario,
                n_tx=cfg.mimo.n_tx, occupied_bw_hz=cfg.band.sweep_hz, frame_on_s=c.frame_on_s,
                sources={"tx_power_dbm": s_pt, "tx_backoff_db": s_bo, "tx_gain_dbi": s_gt})
    args.update(kw)
    return comp.check_emission(cfg.band.center_hz - 0.5 * cfg.band.sweep_hz, cfg.band.center_hz + 0.5 * cfg.band.sweep_hz, pt, gt,
                               comp.frame_intervals(c.n_chirps, c.duration_s, c.pri_s), **args)


@pytest.mark.parametrize("name", ["radar_60g_sensing", "radar_60g_mimo", "radar_60g_x10lo", "radar_60g_dither", "radar_77g_automotive"])
def test_the_rule_on_explicit_numbers_is_the_configs_check(name):
    """``check(cfg)`` is ``check_emission`` on the config's numbers: the same
    result, field for field, on every bundled config and at full power with
    the scenario declared."""
    for ov in ({}, {"frontend.tx_backoff_db": 0.0}, {"chirp.frame_period_s": None}, {"regulatory.scenario": "outdoor_fixed"}):
        cfg = apply_overrides(load_config(REPO / "configs" / f"{name}.yaml"), ov)
        assert _explicit(cfg).as_dict() == compliance_check(cfg).as_dict()
    assert comp.on_bursts(RadarConfig(), 2e-3) == comp.merge_bursts(comp.frame_intervals(64, 100e-6, 100e-6), 2e-3) == [(0.0, 6.4e-3)]


def test_an_emission_that_is_not_a_radar_config():
    """What another library hands in (jcas60: an 802.11ay sensing frame read
    under the radar limits): 64 bursts of 3.055 us, one every 100 us, 30
    frames a second, occupying 59.40-61.56 GHz, 12 dBm into 10 dBi.  The
    gaps are under 2 ms, so it is one 6.3 ms burst; the band fits the
    57-61.56 GHz tier, 20 dBm with its off-time -- 6 dB over what the
    default radar's 58-62 GHz sweep gets (it crosses 61.56 GHz).  Nothing of
    it is a ``RadarConfig``; the inputs' tags are the caller's to state."""
    on = comp.frame_intervals(64, 3.055e-6, 100e-6)
    r = comp.check_emission(59.40e9, 61.56e9, 12.0, 10.0, on, number=sources.number, frame_period_s=1.0 / 30.0)
    assert r.applies and r.governing == "radar_57_61p56_off_time" and r.tier.peak_eirp_limit_dbm == 20.0
    assert r.eirp_dbm == 22.0 and r.tier.eirp_margin_db == pytest.approx(-2.0) and r.eirp_cap_dbm == 20.0
    assert r.tier.off_time == "met" and r.tier.off_time_have_s == pytest.approx(33e-3 - (63 * 100e-6 + 3.055e-6), abs=1e-9)
    assert r.frame_on_s == pytest.approx(63 * 100e-6 + 3.055e-6) and r.n_tx == 1 and r.scenario is None
    assert r.sources == {"tx_power_dbm": comp.NOT_STATED, "tx_backoff_db": comp.NOT_STATED, "tx_gain_dbi": comp.NOT_STATED, "band": "spec"}
    assert compliance_check(apply_overrides(RadarConfig(), {"frontend.tx_backoff_db": 0.0})).tier.peak_eirp_limit_dbm == 14.0
    # the same bursts 3 ms apart are 64 bursts to the rule: every gap is an off-time of its own
    apart = comp.check_emission(59.40e9, 61.56e9, 12.0, 10.0, comp.frame_intervals(8, 3.055e-6, 3e-3), number=sources.number, frame_period_s=1.0 / 30.0)
    assert apart.tier.off_time_have_s > r.tier.off_time_have_s and len(comp.merge_bursts(comp.frame_intervals(8, 3.055e-6, 3e-3), 2e-3)) == 8
    # no frame period: the power is judged, the off-time is the shortest period that would do
    open_ = comp.check_emission(59.40e9, 61.56e9, 10.0, 10.0, on, number=sources.number)
    assert open_.tier.off_time == "frame period not declared" and open_.tier.compliant is None
    t_min = open_.tier.min_frame_period_s                     # 14.55 ms: two bursts may share a 33 ms window, 8.25 ms of off-time each
    assert t_min == pytest.approx(63 * 100e-6 + 3.055e-6 + 16.5e-3 / 2, abs=1e-6)
    at = lambda period: _tier(comp.check_emission(59.40e9, 61.56e9, 10.0, 10.0, on, number=sources.number, frame_period_s=period),     # noqa: E731
                              "radar_57_61p56_off_time")
    assert at(t_min * 1.001).off_time == "met" and at(t_min * 1.001).compliant is True
    assert at(t_min * 0.99).off_time == "not met" and not at(t_min * 0.99).usable      # the radar falls back to a tier without it
    # the occupied bandwidth is the band's own width unless stated: 61.0-61.5 GHz is the narrow tier's, 501 MHz stated is not
    narrow = comp.check_emission(61.0e9, 61.5e9, 12.0, 10.0, on, number=sources.number)
    wide = comp.check_emission(61.0e9, 61.5e9, 12.0, 10.0, on, number=sources.number, occupied_bw_hz=501e6)
    assert _tier(narrow, "radar_61_61p5").bandwidth_ok is True and _tier(wide, "radar_61_61p5").bandwidth_ok is False
    assert narrow.governing == "radar_61_61p5" and wide.governing != "radar_61_61p5"


def test_the_limits_come_through_the_function_handed_in():
    """``number`` is a parameter: a caller's own table is the one read (and
    only it -- the library's is not touched)."""
    seen = []

    def own(key):
        seen.append(key)
        e = sources.number(key)
        return dataclasses.replace(e, value=17.0, source="assumed") if key == "fcc15255.radar_57_64.peak_eirp_dbm" else e

    r = _explicit(FULL, number=own)
    t = _tier(r, "radar_57_64")
    assert t.peak_eirp_limit_dbm == 17.0 and t.sources["peak_eirp_dbm"] == "assumed" and t.eirp_margin_db == pytest.approx(-5.0)
    assert _tier(compliance_check(FULL), "radar_57_64").peak_eirp_limit_dbm == 14.0
    assert set(seen) >= {"fcc15255.band_low_hz", "fcc15255.band_high_hz"} and all(k.startswith("fcc15255.") for k in seen)
    assert {k.split(".")[1] for k in seen if k.count(".") == 2} == set(comp.TIERS)


def test_the_module_can_be_vendored_as_it_is(tmp_path):
    """Nothing of the library is imported when the module loads: its file,
    copied alone and loaded outside the package, checks an emission against
    a table handed in.  (Only ``check(cfg)`` reaches into the library, when
    called.)"""
    import ast
    import importlib.util
    import sys
    import types

    src = (REPO / "src" / "fmcw_radar" / "link" / "compliance.py").read_text()
    tree = ast.parse(src)
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all(not (isinstance(n, ast.ImportFrom) and n.level) for n in top)                     # no relative import at load time
    assert {n.module if isinstance(n, ast.ImportFrom) else n.names[0].name for n in top} == {"__future__", "dataclasses", "typing"}
    (tmp_path / "compliance_copy.py").write_text(src)
    spec = importlib.util.spec_from_file_location("compliance_copy", tmp_path / "compliance_copy.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["compliance_copy"] = mod
    try:
        spec.loader.exec_module(mod)
        table = {k: types.SimpleNamespace(value=sources.number(k).value, source="vendored") for k in
                 ["fcc15255.band_low_hz", "fcc15255.band_high_hz"]
                 + [f"fcc15255.{t}.{f}" for t, (_, _, off, bw, cond) in comp.TIERS.items()
                    for f in ["band_low_hz", "band_high_hz", "peak_eirp_dbm"] + (["off_time_sum_min_s", "off_time_window_s", "off_time_min_run_s"] if off else [])
                    + (["max_bandwidth_hz"] if bw else []) + (["peak_conducted_dbm"] if cond else [])]}
        got = mod.check_emission(58e9, 62e9, 12.0, 10.0, mod.frame_intervals(64, 100e-6, 100e-6), number=table.__getitem__,
                                 tx_backoff_db=8.0, frame_period_s=1.0 / 30.0, sources={"tx_power_dbm": "spec"})
    finally:
        del sys.modules["compliance_copy"]
    want, have = compliance_check(RadarConfig()).as_dict(), got.as_dict()          # the default: 58-62 GHz, 8 dB backed off, 30 frames a second
    assert have["sources"] == {"tx_power_dbm": "spec", "tx_backoff_db": "not stated", "tx_gain_dbi": "not stated", "band": "vendored"}
    assert have.pop("frame_on_s") == pytest.approx(want.pop("frame_on_s"), rel=1e-12)            # first start to last end, not handed in
    bare = lambda d: {**{k: v for k, v in d.items() if k != "sources"},                           # noqa: E731
                      "tiers": [{k: v for k, v in t.items() if k != "sources"} for t in d["tiers"]]}
    assert bare(have) == bare(want) and have["governing"] == "radar_57_64" and have["compliant"] is True
    assert all(t["sources"]["peak_eirp_dbm"] == "vendored" for t in have["tiers"])

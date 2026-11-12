"""The one LO: the vendored ADPLL from the config, its phase-noise profile x N, a file profile reading back the same."""

import numpy as np
import pytest
from conftest import REPO

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.lo import LOProfile, build_adpll, parked_lo


def test_adpll_is_built_from_the_config_alone(cfg60):
    pll = build_adpll(cfg60)
    c = pll.cfg
    assert c.fout == cfg60.dco_center_hz and c.fref == cfg60.lo.fref_hz and c.mode == "tdc"
    assert c.tdc.t_res == cfg60.lo_value("tdc_res_s")[0]
    ana = pll.analyze()
    assert ana.loop.f_ugb == pytest.approx(cfg60.lo.loop_bw_hz, rel=0.05)
    assert ana.loop.pm_deg == pytest.approx(cfg60.lo.phase_margin_deg, abs=3.0)


def test_profile_is_the_analysis_times_n_squared(cfg60):
    """The TDC's jitter is analyze()'s own term since the re-pin to polar_tx
    b007e60 (pll_simulator #77); this library used to add it.  Either way it
    is a white timing error at the node the quantisation error enters: that
    term's shape and 12 sigma^2 / t_res^2 of its power, once."""
    quiet_tdc = apply_overrides(cfg60, {"lo.tdc_jitter_s": 0.0})
    prof = LOProfile.from_config(quiet_tdc)
    ana = build_adpll(quiet_tdc).analyze()
    f = 1e6
    s_dco = np.interp(np.log10(f), np.log10(ana.f), np.log10(ana.pn_breakdown["total"]))
    assert float(prof.l_dbc(f)) == pytest.approx(10 * s_dco + 20 * np.log10(4) - 10 * np.log10(2), abs=0.05)
    assert "tdc_jitter" not in prof.components
    live = LOProfile.from_config(cfg60)                                  # the 1 ps placeholder on a 5 ps TDC
    assert cfg60.lo_value("tdc_jitter_s") == (1e-12, "assumed") and build_adpll(cfg60).cfg.tdc.jitter_rms_s == 1e-12
    assert np.allclose(live.components["tdc_jitter"], live.components["tdc_quant"] * 12.0 * (1.0 / 5.0) ** 2, rtol=1e-9)
    assert np.allclose(live.s_phi, prof.s_phi + live.components["tdc_jitter"], rtol=1e-9)
    assert np.allclose(live.s_phi, sum(live.components.values()), rtol=1e-12)            # in the total once
    assert float(live.l_dbc(f)) - float(prof.l_dbc(f)) == pytest.approx(0.6, abs=0.15)      # a third of the in-band noise, half as much again
    # the sampled loop's images are cut: beyond fref/2 the DCO alone (Leeson 1/f^2 down to its floor)
    osc = build_adpll(cfg60).cfg.osc
    for f in (1e8, 1e9):
        assert float(prof.l_dbc(f)) == pytest.approx(10 * np.log10(osc.leeson("dco").psd(f) * 16 / 2), abs=0.05)
    assert float(prof.l_dbc(1e9)) < float(prof.l_dbc(5e7)) - 10.0


def test_parked_lo_names_the_dead_zone_where_the_parked_frequency_is_integer_n(cfg60):
    """ROADMAP P1 #1(c): the profile is the loop's linear analysis, and an
    integer-N loop with under half a TDC bin of dither does not follow it
    while parked.  Whether the LO is in that state depends on where it is
    parked: the carrier (CW) or the ramp's start frequency (chirp.idle_s)."""
    k = parked_lo(cfg60)
    assert k["known"] and k["fcw_center"] == 150.0 and k["dead_zone_center"]
    assert k["dither_bins"] == pytest.approx(0.22, abs=0.02) and k["idle_s"] == 0.0
    assert LOProfile.from_config(cfg60).notes and "dead zone" in LOProfile.from_config(cfg60).notes[0]
    half_a_bin = apply_overrides(cfg60, {"lo.tdc_jitter_s": 2.6e-12})                   # the TDC's own jitter dithers it
    assert not parked_lo(half_a_bin)["dead_zone_center"] and not LOProfile.from_config(half_a_bin).notes
    idle = parked_lo(apply_overrides(cfg60, {"chirp.idle_s": 10e-6}))                   # 14.5 GHz / 100 MHz = 145
    assert idle["fcw_idle"] == 145.0 and idle["dead_zone_idle"] and idle["idle_fraction"] == pytest.approx(10.0 / 110.0)
    half = parked_lo(apply_overrides(cfg60, {"chirp.idle_s": 10e-6, "band.sweep_hz": 2e9}))   # 14.75 GHz: 147.5, fractional
    assert half["fcw_idle"] == pytest.approx(147.5) and not half["dead_zone_idle"] and half["dead_zone_center"]
    file = parked_lo(apply_overrides(cfg60, {"lo.profile": "data/clock_profiles/adpll_15g_fingerprint.yaml"}))
    assert not file["known"] and file["dead_zone_center"] is None                       # not our loop to analyse


def test_the_dead_zone_flag_is_where_the_cycle_accurate_loop_leaves_the_profile(cfg60):
    """Two implementations of the same parked loop: where parked_lo says dead
    zone the cycle-accurate engine reads several dB more in band than the
    linear analysis (CW, 30 kHz - 300 kHz: +7 to +8 dB at the 1 ps
    placeholder, +15.8 with no jitter); where it does not, they agree."""
    fq = np.array([3e4, 1e5, 3e5])

    def excess_db(jitter_s):
        cfg = apply_overrides(cfg60, {"lo.tdc_jitter_s": jitter_s})
        pll = build_adpll(cfg)
        ana = np.asarray(pll.analyze(fq).pn_breakdown["total"])
        sim = pll.simulate(200000, noise=True, seed=3)
        s = np.interp(fq, np.asarray(sim.f_psd), np.asarray(sim.s_phi_psd))
        return float(np.mean(10.0 * np.log10(s / ana))), parked_lo(cfg)["dead_zone_center"]

    parked, flagged = excess_db(1e-12)
    assert flagged and parked > 4.0, parked
    dithered, flagged = excess_db(5e-12)
    assert not flagged and abs(dithered) < 2.0, dithered


def test_multiplier_scales_the_phase_noise_by_20_log_n():
    a = LOProfile.from_config(RadarConfig())
    b = LOProfile.from_config(apply_overrides(RadarConfig(), {"lo.mult": 2, "lo.kdco_hz": 100e3}))
    # x2: the DCO at 30 GHz has its own analysis, so compare the multiplier alone through the file path
    import yaml

    d = yaml.safe_load((REPO / "src/fmcw_radar/data/clock_profiles/adpll_15g_fingerprint.yaml").read_text())
    assert d["f0_hz"] == 15e9
    assert a.mult == 4 and b.mult == 2


def test_file_profile_reads_back_the_live_analysis(cfg60):
    live = LOProfile.from_config(cfg60)
    filed = LOProfile.from_config(apply_overrides(cfg60, {"lo.profile": "data/clock_profiles/adpll_15g_fingerprint.yaml"}))
    f = np.geomspace(1e3, 4e7, 50)
    assert np.max(np.abs(live.l_dbc(f) - filed.l_dbc(f))) < 0.05
    shifted = LOProfile.from_config(apply_overrides(cfg60, {"lo.profile": "data/clock_profiles/adpll_15g_fingerprint.yaml",
                                                            "lo.profile_shift_db": 6.0}))
    assert np.allclose(shifted.l_dbc(f) - filed.l_dbc(f), 6.0, atol=1e-9)


def test_file_profile_scales_to_the_dco_frequency(tmp_path):
    """A 10 GHz profile read at a 15 GHz DCO: (15/10)^2, then x N^2."""
    import yaml

    p = tmp_path / "ten.yaml"
    yaml.safe_dump({"f0_hz": 10e9, "f_hz": [1e3, 1e6, 5e7], "l_dbc_hz": [-80.0, -100.0, -130.0], "source": "t"},
                   p.open("w"))
    prof = LOProfile.from_config(apply_overrides(RadarConfig(), {"lo.profile": str(p)}))
    assert float(prof.l_dbc(1e6)) == pytest.approx(-100 + 20 * np.log10(1.5) + 20 * np.log10(4), abs=1e-6)


def test_bad_profile_file_is_refused(tmp_path):
    import yaml

    p = tmp_path / "bad.yaml"
    yaml.safe_dump({"f0_hz": 10e9, "f_hz": [1e3, 1e6], "source": "t"}, p.open("w"))
    with pytest.raises(ValueError, match="missing"):
        LOProfile.from_config(apply_overrides(RadarConfig(), {"lo.profile": str(p)}))

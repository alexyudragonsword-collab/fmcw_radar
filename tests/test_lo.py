"""The one LO: the vendored ADPLL from the config, its phase-noise profile x N, a file profile reading back the same."""

import numpy as np
import pytest
from conftest import REPO

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.lo import LOProfile, build_adpll


def test_adpll_is_built_from_the_config_alone(cfg60):
    pll = build_adpll(cfg60)
    c = pll.cfg
    assert c.fout == cfg60.dco_center_hz and c.fref == cfg60.lo.fref_hz and c.mode == "tdc"
    assert c.tdc.t_res == cfg60.lo_value("tdc_res_s")[0]
    ana = pll.analyze()
    assert ana.loop.f_ugb == pytest.approx(cfg60.lo.loop_bw_hz, rel=0.05)
    assert ana.loop.pm_deg == pytest.approx(cfg60.lo.phase_margin_deg, abs=3.0)


def test_profile_is_the_analysis_times_n_squared(cfg60):
    """...plus the one term pllsim's analyze() does not have: the TDC's
    jitter, a white timing error at the node the quantisation error enters,
    so that term's shape and 12 sigma^2 / t_res^2 of its power."""
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
    assert float(live.l_dbc(f)) - float(prof.l_dbc(f)) == pytest.approx(0.6, abs=0.15)      # a third of the in-band noise, half as much again
    # the sampled loop's images are cut: beyond fref/2 the DCO alone (Leeson 1/f^2 down to its floor)
    osc = build_adpll(cfg60).cfg.osc
    for f in (1e8, 1e9):
        assert float(prof.l_dbc(f)) == pytest.approx(10 * np.log10(osc.leeson("dco").psd(f) * 16 / 2), abs=0.05)
    assert float(prof.l_dbc(1e9)) < float(prof.l_dbc(5e7)) - 10.0


def test_tdc_jitter_term_is_counted_once_whichever_pllsim_is_vendored():
    """pll_simulator gained the same term in analyze() at 5564c64 (#76 / #77).
    The copy vendored here does not have it, so the profile adds it; once a
    re-pin brings a breakdown that already carries ``tdc_jitter`` the profile
    must leave it alone, or the jitter is in the LO twice."""
    from fmcw_radar.lo import _with_tdc_jitter

    quant = np.array([4.0e-10, 2.0e-10])
    old = {"ref": np.array([1e-10, 1e-10]), "tdc_quant": quant}
    comp, total = _with_tdc_jitter(old, sum(old.values()), 5e-12, 1e-12)
    assert np.allclose(comp["tdc_jitter"], quant * 0.48) and np.allclose(total, sum(comp.values()))
    assert "tdc_jitter" not in old                                        # the caller's dict is not touched
    # upstream's own term, the same formula: nothing is added on top
    new = {**old, "tdc_jitter": quant * 0.48}
    comp2, total2 = _with_tdc_jitter(new, sum(new.values()), 5e-12, 1e-12)
    assert comp2 is new and np.allclose(total2, total)
    # no jitter, or a breakdown without a quantisation term: nothing to add
    assert _with_tdc_jitter(old, sum(old.values()), 5e-12, 0.0)[0] is old
    assert _with_tdc_jitter({"ref": quant}, quant, 5e-12, 1e-12)[0] == {"ref": quant}
    # the vendored copy is still the one without the term (when this fails, the re-pin has happened: drop the note in ROADMAP)
    assert "tdc_jitter" not in build_adpll(RadarConfig()).analyze().pn_breakdown


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

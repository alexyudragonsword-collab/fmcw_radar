"""Milestone 2: TX-RX leakage, the IF high-pass, several targets, the CFAR curves."""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.link import leakage_budget
from fmcw_radar.processing import apply_hpf, cfar_pd_monte_carlo, cfar_pd_swerling1, hpf_attenuation_db, pd_swerling0


def _leak(**ov):
    return apply_overrides(RadarConfig(), {"leakage.enabled": True, "leakage.reflector_range_m": 0.02, "chirp.n_chirps": 4, **ov})


def test_leakage_budget_levels_and_flags():
    cfg = _leak()
    lb = leakage_budget(cfg)
    assert lb.isolation_source == "assumed" and lb.isolation_db == 25.0
    direct, refl = lb.terms
    assert direct.level_rx_dbm == pytest.approx(10.0 - 25.0) and refl.level_rx_dbm == pytest.approx(direct.level_rx_dbm - 10.0)
    assert direct.beat_hz == pytest.approx(cfg.slope_hz_per_s * 0.2e-9)
    assert lb.p1db_margin_db < 0.0 and lb.adc_headroom_no_hpf_db < 0.0           # compressed and clipping without a filter
    assert lb.adc_headroom_db == lb.adc_headroom_no_hpf_db                         # no high-pass configured
    assert lb.required_hpf_atten_db > 20.0
    with_hpf = leakage_budget(_leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2}))
    assert with_hpf.adc_headroom_db > 20.0 and with_hpf.required_hpf_atten_db == 0.0
    assert with_hpf.hpf_atten_at_target_db < 0.01                                 # the 1.33 MHz beat is untouched
    assert leakage_budget(RadarConfig()) is None


def test_hpf_attenuation_closed_form_and_filter_agree():
    fs, fc = 10e6, 200e3
    for order in (1, 2, 3):
        assert hpf_attenuation_db(fc, fc, order) == pytest.approx(3.0103, abs=0.01)
        assert hpf_attenuation_db(fc / 10, fc, order) == pytest.approx(20.0 * order, abs=0.05)
        t = np.arange(20000) / fs
        for f in (20e3, 2e6):
            y = apply_hpf(np.exp(2j * np.pi * f * t), fs, fc, order)
            got = -20.0 * math.log10(float(np.mean(np.abs(y[10000:]))))
            assert got == pytest.approx(hpf_attenuation_db(f, fc, order), abs=0.2)
    x = np.ones(10, dtype=complex)
    assert apply_hpf(x, fs, 0.0, 1) is x


def test_time_engine_clips_without_the_high_pass_and_recovers_with_it():
    without = run_time(_leak(), phase_noise=False)
    assert without.extras["clipped_fraction"] > 0.9
    cfg = _leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2})
    with_ = run_time(cfg, phase_noise=False)
    assert with_.extras["clipped_fraction"] < 0.1
    # the leakage after the high-pass still tops the target (the budget says by
    # 16 dB): the map's peak is the leakage at ~0 m and the target is found
    # at 5 m at the level the budget gives it
    lb = leakage_budget(cfg)
    assert with_.peak_range_m < 0.1
    found = with_.extras["targets_found"][0]
    assert found is not None and found[0] == pytest.approx(5.0, abs=0.04)
    assert found[2] == pytest.approx(lb.target_level_adc_dbm - lb.terms[0].level_adc_hpf_dbm, abs=3.0)
    # the leakage shares the LO: with the leakage but no target power the map's peak is the leakage at ~0 m
    lk_only = run_time(_leak(**{"frontend.tx_power_dbm": -190.0, "frontend.p1db_dbm": -200.0, "leakage.isolation_db": 25.0}),
                       phase_noise=False, noise=False, quantise=False)
    assert lk_only.peak_range_m < 0.1


def test_several_targets_statistical_rows_and_time_engine_levels():
    extra = [{"kind": "car", "range_m": 5.3, "velocity_mps": 2.0}, {"kind": "human", "range_m": 9.9, "velocity_mps": -1.0}]
    cfg = apply_overrides(RadarConfig(), {"extra_targets": extra, "chirp.n_chirps": 8})
    st = run_statistical(cfg)
    assert [t["kind"] for t in st.targets] == ["human", "car", "human"]
    assert st.targets[1]["snr_cell_db"] > st.targets[0]["snr_cell_db"] + 15.0     # +20 dBsm, 30 cm farther
    assert not any(t["masked"] for t in st.targets)
    tm = run_time(cfg, phase_noise=False)
    found = tm.extras["targets_found"]
    assert all(f is not None for f in found)
    ref = max(t["ps_adc_dbm"] for t in st.targets)
    for t, f in zip(st.targets, found):
        assert f[0] == pytest.approx(t["range_m"], abs=cfg.range_resolution_m)
        assert f[2] == pytest.approx(t["ps_adc_dbm"] - ref, abs=1.5)


def test_a_weak_target_under_a_strong_ones_skirt_is_called_masked():
    cfg = apply_overrides(RadarConfig(), {"extra_targets": [{"kind": "custom", "range_m": 5.05, "velocity_mps": 2.0, "rcs_dbsm": -45.0}],
                                          "chirp.n_chirps": 4})
    st = run_statistical(cfg)
    weak = st.targets[1]
    assert weak["masked"] and weak["interferer"] == 0 and weak["interference_kind"] == "window"
    assert not st.targets[0]["masked"]


def test_cfar_curves():
    snr = np.array([6.0, 10.0, 14.0])
    pfa = 1e-4
    mc0 = cfar_pd_monte_carlo(snr, pfa, 16, 40_000, seed=1)
    ideal = pd_swerling0(snr, pfa)
    assert np.all(mc0 < ideal)                                       # the CFAR loss
    assert np.all(np.diff(mc0) > 0)
    mc1 = cfar_pd_monte_carlo(snr, pfa, 16, 40_000, seed=2, swerling=1)
    assert np.allclose(mc1, cfar_pd_swerling1(snr, pfa, 16), atol=0.02)
    assert float(cfar_pd_monte_carlo(np.array([-300.0]), pfa, 16, 400_000, seed=3)[0]) == pytest.approx(pfa, rel=0.25)


def test_report_and_fingerprint_carry_milestone_two(tmp_path):
    from fmcw_radar.report import report, to_markdown

    cfg = apply_overrides(RadarConfig(), {"mimo.n_tx": 2, "mimo.n_rx": 4, "target.angle_deg": 20.0, "chirp.n_chirps": 4,
                                          "extra_targets": [{"kind": "car", "range_m": 8.0}], "leakage.enabled": True,
                                          "rx.hpf_corner_hz": 200e3})
    md = to_markdown(report(cfg, run_statistical(cfg)))
    for word in ("## Targets (milestone 2)", "## Angle (TDM-MIMO virtual array)", "## TX-RX leakage", "Cramer-Rao"):
        assert word in md, word

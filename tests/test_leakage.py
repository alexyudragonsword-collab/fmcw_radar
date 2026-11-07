"""Milestone 2: TX-RX leakage, the IF high-pass, several targets, the CFAR curves."""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.link import leakage_budget
from fmcw_radar.processing import apply_hpf, cfar_pd_monte_carlo, cfar_pd_swerling1, hpf_attenuation_db, pd_swerling0
from fmcw_radar.processing.windows import coherent_gain_db, mainlobe_width_bins, peak_sidelobe_db, range_window


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


def _hpf(order: int, corner_hz: float = 200e3, **ov):
    return _leak(**{"rx.hpf_corner_hz": corner_hz, "rx.hpf_order": order, **ov})


def _far_floor_db(tm) -> float:
    ax, pr = tm.range_profile_axis_m, tm.range_profile_db
    return float(np.mean(pr[(ax > 2.0) & (ax < 4.0)]))


def test_blanked_window_keeps_its_sidelobes_and_pays_the_shorter_record():
    """The window refitted to n - k samples: the same peak sidelobe, a lobe
    wider by n / (n - k), an SNR loss of 10 log10 n / (n - k) against white
    noise (coherent gain of the shorter window).  Zeroing k samples under an
    unchanged window instead leaves a step and raises the sidelobes."""
    n, k = 1000, 80
    w = range_window("hann", n, k)
    assert w.size == n and not np.any(w[:k]) and w[k] == 0.0 and w[k + 1] > 0.0
    assert np.array_equal(range_window("hann", n, 0), range_window("hann", n))
    assert peak_sidelobe_db("hann", n, 16, k) == pytest.approx(peak_sidelobe_db("hann", n, 16), abs=0.1)
    assert mainlobe_width_bins("hann", n, -3.0, 16, k) / mainlobe_width_bins("hann", n, -3.0, 16) == pytest.approx(n / (n - k), rel=0.01)
    assert coherent_gain_db(range_window("hann", n)) - coherent_gain_db(w) == pytest.approx(10 * math.log10(n / (n - k)), abs=0.01)
    zeroed = range_window("hann", n).copy()
    zeroed[:k] = 0.0
    from fmcw_radar.processing.windows import spectrum_db

    bins, s_zeroed = spectrum_db(zeroed, 16)
    _, s_refit = spectrum_db(w, 16)
    far = np.abs(bins) > 40.0                                                   # the window's far sidelobes
    assert np.mean(s_zeroed[far]) > np.mean(s_refit[far]) + 20.0
    with pytest.raises(ValueError):
        range_window("hann", 10, 10)


def test_budget_blanking_rows_follow_the_config():
    lb0 = leakage_budget(_hpf(2))
    assert lb0.blank_s == 0.0 and lb0.blank_loss_db == 0.0 and lb0.blank_recommended_s > 0.0
    # the step: every term's 2 A |sin(pi f_beat T_c)| at the ADC, before the filter
    cfg = _hpf(2)
    step = sum(2.0 * math.sqrt(10 ** ((t.level_adc_dbm - 30) / 10) * 50) * abs(math.sin(math.pi * t.beat_hz * cfg.chirp.duration_s))
               for t in lb0.terms)
    assert lb0.transient_step_v == pytest.approx(step)
    assert lb0.hpf_time_constant_s == pytest.approx(1.0 / (2 * math.pi * 200e3 * math.sin(math.pi / 4)))
    lb = leakage_budget(_hpf(2, **{"rx.blank_s": 4e-6}))
    assert lb.blank_s == 4e-6 and lb.blank_loss_db == pytest.approx(10 * math.log10(1000 / 960), abs=0.02)
    assert leakage_budget(_leak()).blank_recommended_s == 0.0                     # no filter: no transient to blank
    with pytest.raises(ValueError, match="blank_s"):
        _hpf(2, **{"rx.blank_s": 30e-6})


@pytest.mark.parametrize("order", [1, 2, 3])
def test_recommended_blank_covers_the_clipped_run_and_restores_the_floor(order):
    """With the high-pass the ADC clips a run at every chirp's start; the
    budget's recommended blank covers it (nothing clipped survives the
    blank), and the range profile's far floor comes back to the no-leakage
    reference, which the unblanked transient had raised."""
    cfg = _hpf(order)
    rec = leakage_budget(cfg).blank_recommended_s
    tm0 = run_time(cfg, phase_noise=False, noise=False)
    frame = tm0.frame
    a_fs = tm0.extras["fullscale_v"]
    step = tm0.extras["adc_step_v"]
    sat = (np.abs(frame.real) >= a_fs - step / 2) | (np.abs(frame.imag) >= a_fs - step / 2)
    run = max(int(np.flatnonzero(sat[m, :500]).max()) + 1 for m in range(frame.shape[0]))
    assert 0 < run <= rec * cfg.rx.adc_fs_hz < 2.0 * run                     # covered, and not by a silly margin
    cb = apply_overrides(cfg, {"rx.blank_s": rec})
    tm = run_time(cb, phase_noise=False, noise=False)
    # what still clips after the blank is at most the last sample of a chirp: the engine's circular
    # brick-wall IF rings the next chirp's step back into it (the window weighs it ~1e-5)
    assert tm.extras["clipped_fraction_after_blanking"] <= 1.0 / cb.n_samples < tm.extras["clipped_fraction"]
    sat_b = (np.abs(tm.frame.real) >= a_fs - step / 2) | (np.abs(tm.frame.imag) >= a_fs - step / 2)
    assert not np.any(sat_b[:, cb.n_blank:-1])
    assert not np.any(tm.frame[:, :cb.n_blank])
    ref = run_time(cb, phase_noise=False, noise=False, leakage=False)
    # the floor relative to the target's own level, blanked vs the no-leakage reference, vs unblanked
    i_t = int(np.argmin(np.abs(tm.range_profile_axis_m - 5.0)))
    rel = lambda t: _far_floor_db(t) - t.range_profile_db[i_t]                    # noqa: E731
    assert rel(tm) == pytest.approx(rel(ref), abs=3.0)      # the transient's tail under the window's rising edge: ~2 dB left
    if order >= 2:
        assert rel(tm0) > rel(tm) + 8.0
    f = tm.extras["targets_found"][0]
    assert f is not None and f[0] == pytest.approx(5.0, abs=0.04)


def test_blanking_zero_is_the_old_path_bit_for_bit():
    cfg = _hpf(2)
    a = run_time(cfg, phase_noise=False, seed=3)
    b = run_time(apply_overrides(cfg, {"rx.blank_s": 0.0}), phase_noise=False, seed=3)
    assert np.array_equal(a.frame, b.frame) and np.array_equal(a.rd_db, b.rd_db)
    st = run_statistical(apply_overrides(cfg, {"rx.blank_s": 4e-6}))
    assert st.range_res_m / run_statistical(cfg).range_res_m == pytest.approx(1000 / 960, rel=0.01)
    assert st.snr_cell_db == pytest.approx(run_statistical(cfg).snr_cell_db - 10 * math.log10(1000 / 960), abs=0.02)

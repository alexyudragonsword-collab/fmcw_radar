"""Invariant #3: the statistical engine is the main one; the time engine checks it.

Acceptance: cell SNR within 1 dB at three ranges; the resolution of the
processed point target against c / 2B (rect, < 2 %) and the window's lobe
(< 5 %); the phase-noise sidelobes measured on the FFT against the closed
form (< 0.5 dB where the noise dominates the window) at 1 / 10 / 100 m; the
chirp curve fed into one FFT against the time engine mixing the same curve.
"""

import numpy as np
import pytest

from fmcw_radar.chirp import ChirpEngine
from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_radar, run_statistical, run_time
from fmcw_radar.engine.statistical import ideal_profile, nonlinearity_profile, pn_floor_table
from fmcw_radar.engine.timedomain import measured_pn_sidelobes
from fmcw_radar.sources import number


@pytest.mark.parametrize("range_m", [2.0, 5.0, 10.0])
def test_cell_snr_statistical_vs_time_within_1_db(range_m):
    cfg = apply_overrides(RadarConfig(), {"target.range_m": range_m, "chirp.n_chirps": 16, "sim.engine": "both"})
    res = run_radar(cfg)
    assert res.time.peak_range_m == pytest.approx(range_m, abs=cfg.range_resolution_m)
    assert res.time.peak_velocity_mps == pytest.approx(cfg.target.velocity_mps, abs=1.5 * cfg.velocity_resolution_mps)
    assert abs(res.time.snr_cell_db - res.stat.extras["snr_cell_expected_db"]) < 1.0
    assert res.stat.pd > 0.999


def test_resolution_rect_is_c_over_2b_and_windows_their_lobes():
    for name in ("rect", "hann", "hamming", "blackman"):
        cfg = apply_overrides(RadarConfig(), {"lo.engine": "ideal", "processing.window_range": name,
                                              "chirp.n_chirps": 2, "processing.range_pad": 8})
        tm = run_time(cfg, noise=False, phase_noise=False, quantise=False)
        th = ideal_profile(cfg)
        if name == "rect":
            assert tm.width_rayleigh_m == pytest.approx(cfg.range_resolution_m, rel=0.02)
        assert tm.width_3db_m == pytest.approx(th["width_3db_m"], rel=0.05)
        assert tm.width_3db_m == pytest.approx(number(f"window.{name}_3db_bins").value * cfg.range_resolution_m, rel=0.05)
        assert tm.peak_sidelobe_db == pytest.approx(th["peak_sidelobe_db"], abs=0.5)


def test_sweep_sets_the_resolution():
    widths = []
    for b, fc in ((2e9, 60e9), (4e9, 60e9), (7e9, 60.5e9)):
        cfg = apply_overrides(RadarConfig(), {"lo.engine": "ideal", "band.sweep_hz": b, "band.center_hz": fc,
                                              "processing.window_range": "rect", "chirp.n_chirps": 2,
                                              "processing.range_pad": 8, "sim.time_osr": 1.0 if b == 7e9 else 1.25})
        tm = run_time(cfg, noise=False, phase_noise=False, quantise=False)
        widths.append(tm.width_rayleigh_m)
        assert tm.width_rayleigh_m == pytest.approx(299_792_458.0 / (2 * b), rel=0.02)
    assert widths[0] > widths[1] > widths[2]


@pytest.mark.parametrize("range_m,sweep,duration,offs", [(1.0, 4e9, 100e-6, (2.0, 5.0)), (10.0, 4e9, 100e-6, (2.0, 3.0)),
                                                         (100.0, 1e9, 1e-3, (2.0, 20.0))])
def test_phase_noise_sidelobes_match_the_closed_form_within_half_a_db(range_m, sweep, duration, offs):
    """Measured on the averaged range FFTs of phase-noise-only chirps, with
    a Blackman window so the window's own sidelobes stay 20 dB under the
    noise at the offsets read; the offsets stay inside the IF band (a 10 m
    target's +5 m sits on the 4 MHz brick wall) and, at 100 m with a 1 ms
    chirp (1 kHz bins), far enough out for the band to hold the same
    hundred-odd bins as the others."""
    cfg = apply_overrides(RadarConfig(), {"target.range_m": range_m, "band.sweep_hz": sweep, "chirp.duration_s": duration,
                                          "target.velocity_mps": 0.0})
    assert cfg.beat_hz() < cfg.rx.if_bw_hz
    m = measured_pn_sidelobes(cfg, offs, n_chirps=64, seed=11, half_bins=10, window_name="blackman")
    closed = pn_floor_table(cfg, offs, window_name="blackman")
    for o in offs:
        assert abs(m[o]["measured_dbc"] - m[o]["closed_form_dbc"]) < 0.5, (range_m, o, m[o])
        # the table's single-point value is the band's centre: near the band average
        assert abs(closed[o][0] - m[o]["closed_form_dbc"]) < 1.0
    if range_m == 100.0:
        # 0.3 rad of residual: the first-order sideband is 20 dB under what the tone really shows 2 m out
        assert m[2.0]["first_order_dbc"] < m[2.0]["closed_form_dbc"] - 15.0


def test_nonlinearity_profile_matches_the_time_engine_on_the_same_curve():
    cfg = apply_overrides(RadarConfig(), {"lo.dp_gain": 1.05, "lo.dp_cal": "none", "chirp.n_chirps": 3,
                                          "processing.range_pad": 8, "target.velocity_mps": 0.0})
    chirp = ChirpEngine(cfg).run(noise=False)
    nl = nonlinearity_profile(cfg, chirp, 2, pad=8)
    tm = run_time(cfg, chirp, noise=False, phase_noise=False, quantise=False)
    assert tm.width_3db_m == pytest.approx(nl["width_3db_m"], rel=0.02)
    assert tm.peak_sidelobe_db == pytest.approx(nl["peak_sidelobe_db"], abs=0.5)
    prof_t = tm.range_profile_db
    i = int(np.argmax(prof_t))
    axis_t = (np.arange(prof_t.size) - i) * (cfg.range_resolution_m / 8)
    sel = np.abs(axis_t) < 0.6
    a = np.interp(axis_t[sel], nl["axis_m"], nl["profile_db"])
    d = (prof_t[sel] - a)[prof_t[sel] > -60.0]
    assert np.sqrt(np.mean(d ** 2)) < 0.5 and np.max(np.abs(d)) < 1.5


def test_mismatch_widens_nothing_but_raises_the_sidelobes_and_calibration_restores():
    base = run_statistical(apply_overrides(RadarConfig(), {"lo.dp_cal": "none", "chirp.n_chirps": 3}))
    bad = run_statistical(apply_overrides(RadarConfig(), {"lo.dp_gain": 1.05, "lo.dp_cal": "none", "chirp.n_chirps": 3}))
    cal = run_statistical(apply_overrides(RadarConfig(), {"lo.dp_gain": 1.05, "lo.dp_cal": "offline", "chirp.n_chirps": 3}))
    assert bad.nonlinearity["phase_rms_rad"] > 10 * base.nonlinearity["phase_rms_rad"]
    assert bad.nonlinearity["islr_db"] > base.nonlinearity["islr_db"] - 1.0
    assert cal.nonlinearity["phase_rms_rad"] == pytest.approx(base.nonlinearity["phase_rms_rad"], rel=0.1)
    assert cal.chirp["dp_gain_used"] == pytest.approx(1.0, abs=0.002)


def test_tdc_ghost_targets_are_reported_and_scale_with_the_tdc():
    """ROADMAP P1 #1a: the TDC's quantisation puts a ghost at a fixed range
    offset (+-4.9 m for the 5 ps default, about -45 dBc); a 2 ps TDC puts
    it 8 dB and more lower; the time engine's map shows the same one."""
    base = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 3}))
    ghosts = base.nonlinearity["ghosts"]
    assert ghosts and base.nonlinearity["ghosts_vouched"]
    off, lvl = ghosts[0]
    assert 4.0 < abs(off) < 6.0 and -50.0 < lvl < -40.0
    assert any(abs(o + off) < 0.1 for o, _ in ghosts)                     # a symmetric pair
    fine = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, "lo.tdc_res_s": 2e-12}))
    assert fine.nonlinearity["ghosts"][0][1] < lvl - 8.0
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 8, "target.velocity_mps": 0.0})
    tm = run_time(cfg, noise=False, phase_noise=False, quantise=False)
    half = tm.rd_db.shape[1] // 2
    i, j = tm.extras["peak_rc"]
    row = tm.rd_db[i, :half] - tm.rd_db[i, j]
    jj = int(np.argmin(np.abs(tm.range_axis_m[:half] - (cfg.target.range_m + off))))
    assert np.max(row[jj - 8:jj + 9]) == pytest.approx(lvl, abs=3.0)
    lin = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, "lo.engine": "response"}))
    assert not lin.nonlinearity["ghosts_vouched"]


def test_statistical_result_reports_what_the_report_prints(cfg60):
    st = run_statistical(apply_overrides(cfg60, {"chirp.n_chirps": 3}))
    assert st.range_bin == pytest.approx(cfg60.beat_hz() * cfg60.chirp.duration_s)
    assert set(st.pn_floor) == {0.1, 0.25, 0.5, 1.0, 2.0, 5.0}
    assert all(a > b for a, b in st.pn_floor.values())            # the cell level is below the single-chirp bin
    assert st.chirp["engine"] == "event" and st.chirp["vouches_for_spurs"]
    assert st.extras["in_if_band"] and st.extras["snr_cell_on_grid_db"] <= st.snr_cell_db


def test_time_engine_switches_isolate_the_effects():
    cfg = apply_overrides(RadarConfig(), {"lo.engine": "ideal", "chirp.n_chirps": 4})
    clean = run_time(cfg, noise=False, phase_noise=False, quantise=False)
    assert clean.snr_cell_db > 100.0                                 # nothing but the tone (float64 rounding)
    q = run_time(cfg, noise=False, phase_noise=False, quantise=True)
    assert 40.0 < q.snr_cell_db < 100.0                              # the quantiser alone (a 1 mV tone on 173 uV steps)
    pn = run_time(cfg, noise=False, phase_noise=True, quantise=False)
    assert 40.0 < pn.snr_cell_db < clean.snr_cell_db                  # the LO's residual alone


def test_77g_config_runs_both_engines():
    from conftest import REPO
    from fmcw_radar.config import load_config

    cfg = load_config(REPO / "configs" / "radar_77g_automotive.yaml", {"chirp.n_chirps": 8, "sim.engine": "both"})
    res = run_radar(cfg)
    assert res.time.peak_range_m == pytest.approx(cfg.target.range_m, abs=cfg.range_resolution_m)
    assert res.time.peak_velocity_mps == pytest.approx(cfg.target.velocity_mps, abs=1.5 * cfg.velocity_resolution_mps)
    assert abs(res.time.snr_cell_db - res.stat.extras["snr_cell_expected_db"]) < 1.0

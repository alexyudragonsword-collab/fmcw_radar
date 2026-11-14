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
    # 1.08 rad over the matched loop's quantisation, 0.134 rad on the 12.2 ps TDC (0.2.12; the bound was 10x on 5 ps)
    assert bad.nonlinearity["phase_rms_rad"] > 5 * base.nonlinearity["phase_rms_rad"]
    assert bad.nonlinearity["islr_db"] > base.nonlinearity["islr_db"] - 1.0
    assert cal.nonlinearity["phase_rms_rad"] == pytest.approx(base.nonlinearity["phase_rms_rad"], rel=0.1)
    assert cal.chirp["dp_gain_used"] == pytest.approx(1.0, abs=0.002)


def test_tdc_ghost_targets_are_reported_and_scale_with_the_tdc():
    """The TDC's quantisation on a ramp, two ways.  Undithered (the noise-off
    curve): a pattern with ghosts at fixed range offsets -- on the sourced
    12.2 ps TDC -34 dBc at -10.3 m and a pair at +-2.8 m (0.2.12; the 5 ps
    placeholder before it: -45 dBc at +-4.9 m), 8 dB and more lower for
    2 ps; the time engine shows the same ones with its phase noise switched
    off.  As a frame sees it (the noise-on curve, what stays coherent over
    the ramps): the TDC's own jitter dithers the pattern, but the 1 ps
    placeholder is 0.08 of a 12.2 ps bin and takes only 2-5 dB off -- every
    spur stays over the search limit.  On the 5 ps TDC the same 1 ps (0.2
    bin) leaves none over it; with no jitter the loop's other noise alone
    leaves them within 3 dB of the undithered ghost."""
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 16})
    base = run_statistical(cfg)
    quiet = base.nonlinearity["ghosts_quiet"]
    assert quiet and base.nonlinearity["ghosts_vouched"]
    off, lvl = quiet[0]
    assert 10.0 < abs(off) < 10.6 and -38.0 < lvl < -30.0
    assert any(abs(o + p) < 0.1 for o, _ in quiet for p, _ in quiet if abs(p) > 1.0)    # a symmetric pair
    fine = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, "lo.tdc_res_s": 2e-12}))
    assert fine.nonlinearity["ghosts_quiet"][0][1] < lvl - 8.0
    c8 = apply_overrides(RadarConfig(), {"chirp.n_chirps": 8, "target.velocity_mps": 0.0})
    tm = run_time(c8, noise=False, phase_noise=False, quantise=False)
    half = tm.rd_db.shape[1] // 2
    i, j = tm.extras["peak_rc"]
    row = tm.rd_db[i, :half] - tm.rd_db[i, j]
    o_v, l_v = next((o, v) for o, v in quiet if 0.5 < c8.target.range_m + o < tm.range_axis_m[half - 9])   # one on the axis
    jj = int(np.argmin(np.abs(tm.range_axis_m[:half] - (c8.target.range_m + o_v))))
    assert np.max(row[jj - 8:jj + 9]) == pytest.approx(l_v, abs=3.0)
    # what a frame sees
    live = base.nonlinearity["ghosts"]
    assert base.nonlinearity["ghost_chirps"] == 15 and live
    assert all(base.nonlinearity["ghost_limit_dbc"] < level < lvl - 2.0 for _, level in live[:3])
    five = run_statistical(apply_overrides(cfg, {"lo.tdc_res_s": 5e-12})).nonlinearity
    assert five["ghosts"] == [] and -50.0 < five["ghosts_quiet"][0][1] < -40.0
    bare = run_statistical(apply_overrides(cfg, {"lo.tdc_jitter_s": 0.0})).nonlinearity
    assert bare["ghosts"] and lvl - 3.0 < bare["ghosts"][0][1] < lvl
    assert bare["ghosts_quiet"] == quiet                                  # the noise-off curve has no jitter in it
    # the search cannot tell a spur from the LO's noise below a limit that falls 3 dB per doubling of the ramps
    longer = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 64})).nonlinearity
    assert longer["ghost_limit_dbc"] < base.nonlinearity["ghost_limit_dbc"] - 4.0
    lin = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, "lo.engine": "response"}))
    assert not lin.nonlinearity["ghosts_vouched"] and lin.nonlinearity["ghosts"] == lin.nonlinearity["ghosts_quiet"]


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

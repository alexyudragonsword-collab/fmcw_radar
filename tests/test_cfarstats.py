"""What the windows and the padding do to the CA-CFAR's false-alarm rate (ROADMAP P2 #0).

Acceptance: the cell correlation is the spectrum of w^2; independent cells
give the textbook Pfa exactly; the exact per-cell Pfa matches a Monte Carlo
of the CFAR itself on windowed, padded noise maps -- including where the
first-order form fails -- and the time engine's noise-only frame.
"""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.processing.cfar import ca_cfar_2d, cfar_window, threshold_factor
from fmcw_radar.processing.cfarstats import (cell_correlation, cfar_pd, cfar_snr_for_pd, cfar_statistics, cfar_statistics_2d,
                                             correlation_length, count_clusters, noise_map, training_mask)
from fmcw_radar.processing.detection import cfar_pd_monte_carlo, pd_swerling0, snr_for_pd
from fmcw_radar.processing.windows import window


def _measure(wd, pad_d, wr, pad_r, guard, train, pfa, frames, seed=0, n_looks=1):
    rng = np.random.default_rng(seed)
    hits = cells = clusters = 0
    for _ in range(frames):
        pm = noise_map(wd, pad_d, wr, pad_r, rng, n_looks)
        _, det = ca_cfar_2d(pm, guard, train, pfa, n_looks)
        hits += int(det.sum())
        clusters += count_clusters(det)
        cells += pm.size
    return hits / cells, clusters


def test_cell_correlation_is_the_spectrum_of_the_squared_window():
    n = 64
    assert np.allclose(cell_correlation(window("rect", n), 1, [0, 1, 2, 5]), [1, 0, 0, 0], atol=1e-12)
    # Hann^2 = 3/8 - cos / 2 + cos2 / 8: its spectrum has lines at 0, +-1, +-2 only
    r = cell_correlation(window("hann", n), 1, [0, 1, 2, 3])
    assert np.allclose(r, [1.0, -2.0 / 3.0, 1.0 / 6.0, 0.0], atol=1e-12)
    # zero-padding interpolates: a quarter of a bin away the cells are nearly the same sample
    assert abs(cell_correlation(window("hann", n), 4, [1])[0]) > 0.95
    assert correlation_length(window("rect", n), 1) == pytest.approx(1.0)
    assert correlation_length(window("hann", n), 1) == pytest.approx(35.0 / 18.0, rel=1e-9)        # N sum w^4 / (sum w^2)^2
    assert correlation_length(window("hann", n), 4) == pytest.approx(4 * 35.0 / 18.0, rel=1e-9)
    # the definition: the sum of |R|^2 over every padded lag
    assert np.sum(np.abs(cell_correlation(window("hann", n), 4, np.arange(4 * n))) ** 2) == pytest.approx(4 * 35.0 / 18.0, rel=1e-9)


def test_training_mask_counts_the_ring():
    m = training_mask(2, 8)
    assert m.shape == (21, 21) and int(m.sum()) == 21 * 21 - 5 * 5 and not m[10, 10] and not m[8, 12] and m[7, 10]


def test_independent_cells_give_the_textbook_pfa_exactly():
    for pfa in (1e-2, 1e-4, 1e-6):
        s = cfar_statistics_2d(window("rect", 64), 1, window("rect", 256), 1, 2, 8, pfa)
        assert s["n_train_eff"] == pytest.approx(416.0, rel=1e-9) and s["cut_correlation"] == pytest.approx(0.0, abs=1e-12)
        assert s["pfa_cell"] == pytest.approx(pfa, rel=1e-6)
        assert s["pfa_training_only"] == pytest.approx(pfa, rel=1e-9) and s["pfa_first_order"] == pytest.approx(pfa, rel=1e-6)
        assert (1.0 + threshold_factor(416, pfa) / 416) ** -416 == pytest.approx(pfa, rel=1e-9)


def test_default_map_two_effects_that_nearly_cancel():
    """Hann / Hann, range pad x4, guard 2 + train 8: the 416 training cells
    are worth 33 (alone: Pfa x2.7) and the half-bin guard leaves them
    correlated with the test cell (alone: Pfa x0.26); together 1.02e-4."""
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 32})
    s = cfar_statistics(cfg)
    assert s["n_train"] == 416 and s["n_train_eff"] == pytest.approx(33.4, abs=0.2)
    assert s["guard_bins_range"] == 0.5 and s["cut_correlation"] == pytest.approx(0.0151, abs=0.0005)
    assert s["pfa_training_only"] > 2.5e-4 and s["pfa_cut_only"] < 0.3e-4
    assert s["pfa_cell"] == pytest.approx(1.02e-4, rel=0.02)
    assert s["cells_in_band"] == 32 * 1600 and s["independent_looks"] == pytest.approx(51200 / (4 * (35 / 18) ** 2), rel=1e-6)
    assert s["false_alarm_cells_per_frame"] == pytest.approx(51200 * s["pfa_cell"])
    wide = cfar_statistics(apply_overrides(cfg, {"processing.cfar_guard": 8}))               # two bins of guard
    assert wide["cut_correlation"] < 1e-3 and wide["pfa_cell"] == pytest.approx(wide["pfa_training_only"], rel=0.05) and wide["pfa_cell"] > 1.5e-4
    carried = run_statistical(cfg).cfar
    assert all(carried[k] == v for k, v in s.items())


@pytest.mark.parametrize("case", [
    ("hann", 32, 1, "hann", 500, 4, 2, 8, 1e-2, 40),            # the default processing
    ("hann", 32, 1, "hann", 500, 4, 2, 8, 1e-3, 80),
    ("hann", 32, 1, "hann", 500, 1, 2, 8, 1e-2, 80),            # no padding: only the window correlates
    ("rect", 32, 1, "rect", 500, 4, 2, 8, 1e-2, 40),            # padding alone
    ("hann", 32, 4, "hann", 500, 4, 2, 8, 1e-2, 20),            # the guard inside the main lobe on both axes
], ids=["default-1e-2", "default-1e-3", "hann-unpadded", "rect-padded", "padded-both"])
def test_exact_pfa_is_what_the_cfar_does_on_correlated_noise(case):
    wd_name, m, pad_d, wr_name, n, pad_r, guard, train, pfa, frames = case
    wd, wr = window(wd_name, m), window(wr_name, n)
    s = cfar_statistics_2d(wd, pad_d, wr, pad_r, guard, train, pfa)
    measured, clusters = _measure(wd, pad_d, wr, pad_r, guard, train, pfa, frames)
    assert clusters > 400                                                    # the count is clustered: this is the sample size
    assert measured == pytest.approx(s["pfa_cell"], rel=5.0 / math.sqrt(clusters) + 0.02)
    if pad_d == 4:
        # the first-order form is off by a third here (alpha c = 0.4); the exact one is not
        assert abs(s["pfa_first_order"] / s["pfa_cell"] - 1.0) > 0.3 and s["pfa_cell"] < 0.7 * pfa


def test_training_window_is_clipped_to_a_short_axis():
    """Eight chirps against a 21-cell window: unclipped it wraps the Doppler
    axis 2.6 times and takes the test cell itself in (the realised Pfa fell
    to 1.4e-6 for a design of 1e-4).  Clipped to 3 cells each side it stays
    within a factor of two of the design, and the closed form follows."""
    assert cfar_window((8, 4000), 2, 8) == ((3, 2), (10, 2))
    assert cfar_window((2, 4000), 2, 8) == ((0, 0), (10, 2)) and cfar_window((64, 4000), 2, 8) == ((10, 2), (10, 2))
    assert training_mask(2, 8, (8, 4000)).shape == (7, 21) and int(training_mask(2, 8, (8, 4000)).sum()) == 7 * 21 - 5 * 5
    assert np.array_equal(training_mask(2, 8, (64, 4000)), training_mask(2, 8))
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 8})
    s = cfar_statistics(cfg)
    assert s["window_half_doppler"] == 3 and s["n_train"] == 122 and 0.5e-4 < s["pfa_cell"] < 1.0e-4
    s2 = cfar_statistics(apply_overrides(cfg, {"processing.cfar_pfa": 1e-2}))
    measured, clusters = _measure(window("hann", 8), 1, window("hann", 1000), 4, 2, 8, 1e-2, 40)
    assert measured == pytest.approx(s2["pfa_cell"], rel=5.0 / math.sqrt(clusters) + 0.02)
    # a map with no room for a single training cell is refused
    with pytest.raises(ValueError, match="no training cells"):
        ca_cfar_2d(np.ones((1, 3)), 2, 8, 1e-3)


def test_threshold_factor_for_a_sum_of_looks():
    """K looks summed: the test cell over itself plus the training sum is
    Beta(K, K N).  K = 1 is the exponential closed form bit for bit; K = 8
    asks 4.6 dB over the mean where the exponential factor asks 9.7 dB, and
    the exponential factor on the sum would give a Pfa of 1e-23."""
    assert threshold_factor(416, 1e-4, 1) == 416 * (1e-4 ** (-1 / 416) - 1)
    a8 = threshold_factor(416, 1e-4, 8)
    assert 10 * math.log10(a8) == pytest.approx(4.6, abs=0.05) and 10 * math.log10(threshold_factor(416, 1e-4)) == pytest.approx(9.7, abs=0.05)
    for k in (1, 2, 8, 16):
        for pfa in (1e-2, 1e-4, 1e-6):
            s = cfar_statistics_2d(window("rect", 64), 1, window("rect", 256), 1, 2, 8, pfa, k)
            assert s["pfa_cell"] == pytest.approx(pfa, rel=1e-5), (k, pfa)       # independent cells: the residue is the Beta tail
    s = cfar_statistics_2d(window("rect", 64), 1, window("rect", 256), 1, 2, 8, 1e-4, 8)
    assert s["pfa_with_single_look_factor"] < 1e-20 and s["single_look_factor_penalty_db"] == pytest.approx(5.1, abs=0.05)
    # correlated cells, 8 looks, against the CFAR itself
    wd, wr = window("hann", 32), window("hann", 500)
    s = cfar_statistics_2d(wd, 1, wr, 4, 2, 8, 1e-2, 8)
    measured, clusters = _measure(wd, 1, wr, 4, 2, 8, 1e-2, 12, n_looks=8)
    assert clusters > 400 and measured == pytest.approx(s["pfa_cell"], rel=5.0 / math.sqrt(clusters) + 0.02)


def _tone_pd(wd, wr, pad_r, guard, train, pfa, snr_db, frames, seed=0, per_frame=24):
    """Tones on the grid, far apart, in white noise: how often the CFAR flags their own cells."""
    m, n = wd.size, wr.size
    rng = np.random.default_rng(seed)
    amp = 10 ** (snr_db / 20) * math.sqrt((wd ** 2).sum() * (wr ** 2).sum()) / (wd.sum() * wr.sum())
    cols = (np.arange(per_frame) * (n // per_frame) + 7) % n
    rows = (np.arange(per_frame) * 5 + 3) % m
    hit = 0
    for _ in range(frames):
        x = (rng.standard_normal((m, n)) + 1j * rng.standard_normal((m, n))) / math.sqrt(2)
        for r, c in zip(rows, cols):
            x = x + amp * np.exp(2j * np.pi * (rng.uniform() + c * np.arange(n)[None, :] / n + r * np.arange(m)[:, None] / m))
        y = np.fft.fft(np.fft.fft(x * wr[None, :], n * pad_r, axis=1) * wd[:, None], axis=0)
        _, det = ca_cfar_2d(np.abs(y) ** 2, guard, train, pfa)
        hit += int(det[rows, cols * pad_r].sum())
    return hit / (frames * per_frame)


def test_cfar_pd_closed_form():
    """Independent cells: the 1-D Monte Carlo of milestone 2, and the known
    noise level as N grows.  On the default map: tones in noise through the
    CFAR itself; a Pd of 0.9 costs half a dB more than the known noise
    level, part of it the target's own leak into its training cells."""
    snr = np.array([6.0, 10.0, 14.0])
    ind16 = {"n_looks": 1, "threshold_factor": threshold_factor(16, 1e-4), "cut_correlation": 0.0, "tone_leak": 0.0, "n_train_eff": 16.0}
    assert np.allclose(cfar_pd(snr, ind16), cfar_pd_monte_carlo(snr, 1e-4, 16, 100_000, seed=4), atol=0.01)
    assert float(cfar_pd(-300.0, ind16)[0]) == pytest.approx(1e-4, rel=1e-3)
    big = {**ind16, "threshold_factor": threshold_factor(4000, 1e-4), "n_train_eff": 4000.0}
    assert np.allclose(cfar_pd(snr, big), pd_swerling0(snr, 1e-4), atol=0.005)
    wd, wr = window("hann", 32), window("hann", 1000)
    s = cfar_statistics_2d(wd, 1, wr, 4, 2, 8, 1e-4)
    assert s["tone_leak"] == pytest.approx(0.0062, abs=0.0005)
    assert float(cfar_pd(-300.0, s)[0]) == pytest.approx(s["pfa_first_order"], rel=0.05)
    for snr_db in (9.0, 12.0):
        assert _tone_pd(wd, wr, 4, 2, 8, 1e-4, snr_db, 30) == pytest.approx(float(cfar_pd(snr_db, s)[0]), abs=0.06)
    loss = cfar_snr_for_pd(0.9, s) - snr_for_pd(0.9, 1e-4)
    assert 0.3 < loss < 0.7
    assert cfar_snr_for_pd(0.9, ind16) - snr_for_pd(0.9, 1e-4) == pytest.approx(1.35, abs=0.1)        # milestone 2's N = 16 loss


def test_ghost_targets_enter_the_false_alarm_account():
    """A coherent spur of the chirp is a steady target at SNR + level.  With
    the placeholder's 1 ps of TDC jitter the spurs sit 55 dB under the
    target and add nothing under the default human.  With the jitter set to
    zero they sit at -49 dBc: under a corner reflector every one in view is
    detected, on the time engine's map too."""
    base = apply_overrides(RadarConfig(), {"chirp.n_chirps": 32})
    human = run_statistical(base).cfar
    assert human["ghosts_vouched"] and human["ghost_detections_per_frame"] < 0.1 and human["pd_target"] > 0.999
    assert all(g["level_dbc"] < -52.0 for g in human["ghosts"])
    assert human["cfar_loss_db"] == pytest.approx(human["snr_pd90_db"] - snr_for_pd(0.9, 1e-4)) and 0.2 < human["cfar_loss_db"] < 1.0
    cfg = apply_overrides(base, {"target.kind": "corner_reflector", "lo.tdc_jitter_s": 0.0})
    strong = run_statistical(cfg).cfar
    view = [g for g in strong["ghosts"] if g["in_view"]]
    assert len(view) >= 2 and all(g["pd"] > 0.95 for g in view) and strong["ghost_detections_per_frame"] == pytest.approx(len(view), abs=0.2)
    assert all(g["snr_db"] == pytest.approx(strong["snr_look_db"] + g["level_dbc"]) for g in view)
    tm = run_time(cfg)                                                    # the same noise-on curve the search read
    d = np.array(tm.cfar_detections)
    strongest = max(view, key=lambda g: g["level_dbc"])
    assert np.any(np.abs(d[:, 1] - strongest["range_m"]) < 1.5 * cfg.range_resolution_m)
    ideal = run_statistical(apply_overrides(base, {"lo.engine": "ideal"})).cfar
    assert ideal["ghosts"] == [] and ideal["ghost_detections_per_frame"] == 0.0 and not ideal["ghosts_vouched"]


def test_mimo_map_uses_the_multi_look_threshold():
    """The 2 x 4 cube's map is a sum of 8 looks: the statistical engine says
    so, and a noise-only frame of the time engine false-alarms at the exact
    rate (with the single-look factor it would not once in 10^20 cells)."""
    cfg = apply_overrides(RadarConfig(), {"mimo.n_tx": 2, "mimo.n_rx": 4, "chirp.n_chirps": 16, "frontend.tx_power_dbm": -190.0,
                                          "processing.cfar_pfa": 1e-2, "lo.engine": "ideal"})
    s = run_statistical(cfg).cfar
    assert s["n_looks"] == 8 and s["window_half_doppler"] == 3 and s["pfa_with_single_look_factor"] < 1e-6
    assert 0.3e-2 < s["pfa_cell"] < 1.5e-2
    tm = run_time(cfg, phase_noise=False, seed=3)
    pw = 10.0 ** (tm.rd_db / 10.0)
    p = cfg.processing
    n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * p.range_pad)
    band = np.zeros(pw.shape[1], dtype=bool)
    band[:n_if - 10] = True
    band[pw.shape[1] - (n_if - 10):] = True
    _, det = ca_cfar_2d(pw, p.cfar_guard, p.cfar_train, p.cfar_pfa, n_looks=8)
    clusters = count_clusters(det[:, band])
    assert clusters > 40 and det[:, band].mean() == pytest.approx(s["pfa_cell"], rel=5.0 / math.sqrt(clusters) + 0.05)


def test_time_engine_noise_only_frame_false_alarms_at_the_exact_rate():
    cfg = apply_overrides(RadarConfig(), {"frontend.tx_power_dbm": -190.0, "chirp.n_chirps": 32, "processing.cfar_pfa": 1e-2})
    p = cfg.processing
    s = cfar_statistics(cfg)
    tm = run_time(cfg, phase_noise=False, seed=5)
    pw = 10.0 ** (tm.rd_db / 10.0)
    n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * p.range_pad)
    edge = p.cfar_guard + p.cfar_train
    band = np.zeros(pw.shape[1], dtype=bool)
    band[:n_if - edge] = True
    band[pw.shape[1] - (n_if - edge):] = True
    _, det = ca_cfar_2d(pw, p.cfar_guard, p.cfar_train, p.cfar_pfa)
    rate = det[:, band].sum() / (pw.shape[0] * band.sum())
    clusters = count_clusters(det[:, band])
    assert clusters > 150 and rate == pytest.approx(s["pfa_cell"], rel=5.0 / math.sqrt(clusters) + 0.02)

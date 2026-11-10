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
from fmcw_radar.processing.cfar import ca_cfar_2d, threshold_factor
from fmcw_radar.processing.cfarstats import (cell_correlation, cfar_statistics, cfar_statistics_2d, correlation_length,
                                             count_clusters, noise_map, training_mask)
from fmcw_radar.processing.windows import window


def _measure(wd, pad_d, wr, pad_r, guard, train, pfa, frames, seed=0):
    rng = np.random.default_rng(seed)
    hits = cells = clusters = 0
    for _ in range(frames):
        pm = noise_map(wd, pad_d, wr, pad_r, rng)
        _, det = ca_cfar_2d(pm, guard, train, pfa)
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
    assert run_statistical(cfg).cfar == s


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


def test_a_training_window_wider_than_the_doppler_axis_wraps_onto_the_test_cell():
    """Eight chirps and a 21-cell training window: the window wraps the
    Doppler axis 2.6 times and takes the test cell itself in.  The realised
    Pfa falls two orders below the design, and the closed form says so."""
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 8})
    s = cfar_statistics(cfg)
    assert s["cut_correlation"] > 0.05 and s["pfa_cell"] < 0.05 * s["pfa_design"]
    s2 = cfar_statistics(apply_overrides(cfg, {"processing.cfar_pfa": 1e-2}))
    measured, clusters = _measure(window("hann", 8), 1, window("hann", 1000), 4, 2, 8, 1e-2, 40)
    assert measured == pytest.approx(s2["pfa_cell"], rel=5.0 / math.sqrt(clusters) + 0.02)


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

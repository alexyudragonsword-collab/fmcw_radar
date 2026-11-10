"""What the windows and the zero-padding do to a CA-CFAR's statistics.

``cfar.threshold_factor`` assumes ``n`` independent exponential training
cells that are independent of the cell under test.  A range-Doppler map is
neither: a window makes neighbouring bins correlated and zero-padding
interpolates between them, so the cells are samples of a smooth field.  For
white noise through a window ``w`` and a pad factor ``p`` the complex
correlation between cells ``k`` padded bins apart is the spectrum of
``w^2``,

    R(k) = sum_n w_n^2 exp(-j 2 pi k n / (N p)) / sum_n w_n^2,

the powers' correlation is ``|R|^2``, and the two axes multiply.  Three
numbers follow, each a closed form checked against a Monte Carlo of the
CFAR itself (``tests/test_cfarstats.py``, example 06):

* **the training set's effective size** ``N_eff = N^2 / sum_ij rho_ij``:
  the mean of N correlated exponentials fluctuates like the mean of
  ``N_eff`` independent ones (a Gamma of that shape), so the threshold is
  noisier than designed and, alone, this *raises* the false-alarm rate;
* **the cell under test's correlation with its training cells**, mean
  ``c``: the guard is counted in padded cells, so with a x4 pad a guard of
  2 is half a bin and the nearest training cells sit on the test cell's
  own main lobe.  A noise peak lifts its own threshold: given the test
  cell's power X the training mean is ``c X + (1 - c) G``, the test
  ``X > alpha (c X + (1 - c) G)`` is ``X > alpha' G`` with
  ``alpha' = alpha (1 - c) / (1 - alpha c)``, and this *lowers* the rate;
* together, to first order, ``Pfa = (1 + alpha' / N_eff)^(-N_eff)`` per
  cell.  That form is the explanation, not the number: it breaks when
  ``alpha c`` nears 1 (a guard deep inside the main lobe on both axes).

The number is exact.  The test ``X > alpha mean(Y)`` asks whether the
Hermitian form ``Q = |x|^2 - (alpha / N) sum |y_i|^2`` of the jointly
Gaussian cells ``z = (x, y_1 .. y_N)`` is positive.  With ``Sigma`` their
covariance (the correlations above) and ``A = diag(1, -alpha / N, ...)``,
``Q`` is distributed as ``sum_k lambda_k E_k`` over the eigenvalues of
``Sigma^(1/2) A Sigma^(1/2)`` with independent unit exponentials ``E_k``;
exactly one eigenvalue is positive (the inertia of ``A``), so

    Pfa = P(lambda_+ E_0 > sum |lambda_j| E_j) = prod_j 1 / (1 + |lambda_j| / lambda_+).

For independent cells this is the textbook ``(1 + alpha / N)^(-N)``.

The count of false-alarm cells in a frame is ``cells x Pfa`` whatever the
correlation (an expectation); what the correlation changes is how they
come -- in clumps the size of a resolution cell -- and how many
independent looks a frame is: ``cells / (L_r L_d)`` with the correlation
length ``L = sum_k |R(k)|^2`` padded cells per axis (the pad factor times
1.94 for a Hann window, times 1 for a rectangular one).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import correlate2d

from ..config.schema import RadarConfig
from .cfar import threshold_factor
from .windows import range_window, window


def cell_correlation(w: np.ndarray, pad: int, lags) -> np.ndarray:
    """Complex correlation coefficient of white noise between two cells of
    a ``pad``-times zero-padded FFT under window ``w``, ``lags`` padded bins
    apart: the normalised spectrum of ``w^2`` (circular in ``n pad``)."""
    w2 = np.asarray(w, dtype=float) ** 2
    n = w2.size
    lags = np.atleast_1d(np.asarray(lags, dtype=float))
    ph = np.exp(-2j * np.pi * lags[:, None] * np.arange(n)[None, :] / (n * pad))
    return (ph @ w2) / w2.sum()


def correlation_length(w: np.ndarray, pad: int) -> float:
    """``sum_k |R(k)|^2`` over every padded lag: how many padded cells one
    independent look spans along this axis (``pad N sum w^4 / (sum w^2)^2``)."""
    w2 = np.asarray(w, dtype=float) ** 2
    return float(pad * w2.size * np.sum(w2 ** 2) / np.sum(w2) ** 2)


def training_mask(guard: int, train: int) -> np.ndarray:
    """The 2-D CA-CFAR's training cells around the cell under test (centre):
    the square of half-width ``guard + train`` minus the guard square."""
    h = guard + train
    m = np.ones((2 * h + 1, 2 * h + 1), dtype=bool)
    m[train:train + 2 * guard + 1, train:train + 2 * guard + 1] = False
    return m


def cfar_statistics_2d(w_doppler: np.ndarray, pad_doppler: int, w_range: np.ndarray, pad_range: int,
                       guard: int, train: int, pfa: float) -> dict:
    """Effective training size, test-cell correlation and the per-cell
    false-alarm probability a 2-D CA-CFAR really has on a windowed, padded
    map of white noise (axis 0 Doppler, axis 1 range)."""
    mask = training_mask(guard, train)
    h = guard + train
    n = int(mask.sum())
    lag = np.arange(-2 * h, 2 * h + 1)
    rho_d = np.abs(cell_correlation(w_doppler, pad_doppler, lag)) ** 2
    rho_r = np.abs(cell_correlation(w_range, pad_range, lag)) ** 2
    rho = rho_d[:, None] * rho_r[None, :]                                  # power correlation at every 2-D lag
    pairs = correlate2d(mask.astype(float), mask.astype(float), mode="full")   # training-cell pairs at every lag
    n_eff = n * n / float(np.sum(pairs * rho))
    c = float(np.sum(rho[h:3 * h + 1, h:3 * h + 1][mask]) / n)             # lags from the centre out to +-h
    alpha = threshold_factor(n, pfa)
    out = {"n_train": n, "n_train_eff": n_eff, "cut_correlation": c, "threshold_factor": alpha,
           "correlation_length_range": correlation_length(w_range, pad_range),
           "correlation_length_doppler": correlation_length(w_doppler, pad_doppler)}
    # the first-order closed form and each effect alone, for the attribution
    out["pfa_training_only"] = float((1.0 + alpha / n_eff) ** (-n_eff))
    if alpha * c < 1.0:
        a_eff = alpha * (1.0 - c) / (1.0 - alpha * c)
        out.update({"threshold_factor_effective": a_eff, "pfa_first_order": float((1.0 + a_eff / n_eff) ** (-n_eff)),
                    "pfa_cut_only": float((1.0 + a_eff / n) ** (-n))})
    else:
        out.update({"threshold_factor_effective": float("inf"), "pfa_first_order": 0.0, "pfa_cut_only": 0.0})
    # the exact value: the sign of a Hermitian form in the jointly Gaussian cells (test cell first)
    dd, rr = np.nonzero(mask)
    dd = np.concatenate([[0], dd - h])                                     # lags from the test cell
    rr = np.concatenate([[0], rr - h])
    r_d = cell_correlation(w_doppler, pad_doppler, lag)                    # complex, indexed by lag + 2h
    r_r = cell_correlation(w_range, pad_range, lag)
    sigma = r_d[(dd[:, None] - dd[None, :]) + 2 * h] * r_r[(rr[:, None] - rr[None, :]) + 2 * h]
    a = np.full(n + 1, -alpha / n)
    a[0] = 1.0
    ev, vec = np.linalg.eigh(sigma)
    root = vec * np.sqrt(np.maximum(ev, 0.0))[None, :]                     # Sigma = root root^H
    lam = np.linalg.eigvalsh(root.conj().T @ (a[:, None] * root))
    lam_pos = float(lam.max())
    neg = -lam[lam < 0.0]
    out["pfa_cell"] = float(np.exp(-np.sum(np.log1p(neg / lam_pos)))) if lam_pos > 0.0 else 0.0
    return out


def cfar_statistics(cfg: RadarConfig) -> dict:
    """``cfar_statistics_2d`` for the config's map (one TX's chirps along
    Doppler), plus the frame: cells inside the IF band on the positive-beat
    half, how many independent looks they are, and the false-alarm cells a
    noise-only frame should show."""
    p = cfg.processing
    m = cfg.chirp.n_chirps // cfg.mimo.n_tx
    n = cfg.n_samples
    out = cfar_statistics_2d(window(p.window_doppler, m), p.doppler_pad, range_window(p.window_range, n, cfg.n_blank), p.range_pad,
                             p.cfar_guard, p.cfar_train, p.cfar_pfa)
    n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * p.range_pad)       # padded range cells inside the IF band, one sign
    cells = m * p.doppler_pad * min(n_if, n * p.range_pad // 2)
    looks = cells / (out["correlation_length_range"] * out["correlation_length_doppler"])
    out.update({"pfa_design": p.cfar_pfa, "cells_in_band": cells, "independent_looks": looks,
                "false_alarm_cells_per_frame": cells * out["pfa_cell"],
                "guard_bins_range": p.cfar_guard / p.range_pad, "guard_bins_doppler": p.cfar_guard / p.doppler_pad})
    return out


def noise_map(w_doppler: np.ndarray, pad_doppler: int, w_range: np.ndarray, pad_range: int, rng: np.random.Generator) -> np.ndarray:
    """One noise-only power map (white complex noise through the two
    windowed, padded FFTs): what the Monte Carlo checks run the CFAR on."""
    m, n = w_doppler.size, w_range.size
    x = (rng.standard_normal((m, n)) + 1j * rng.standard_normal((m, n))) / math.sqrt(2.0)
    y = np.fft.fft(x * w_range[None, :], n * pad_range, axis=1)
    y = np.fft.fft(y * w_doppler[:, None], m * pad_doppler, axis=0)
    return np.abs(y) ** 2


def count_clusters(det: np.ndarray) -> int:
    """Connected groups of detections (8-neighbour, circular on both axes)."""
    from scipy.ndimage import label

    lab, k = label(det, structure=np.ones((3, 3), dtype=int))
    if k == 0:
        return 0
    # merge across the wrap: union the labels that touch on opposite edges
    parent = list(range(k + 1))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in ((lab[0, :], lab[-1, :]), (lab[:, 0], lab[:, -1])):
        for d in (-1, 0, 1):
            bb = np.roll(b, d)
            for u, v in zip(a[(a > 0) & (bb > 0)], bb[(a > 0) & (bb > 0)]):
                parent[find(int(u))] = find(int(v))
    return len({find(i) for i in range(1, k + 1)})


__all__ = ["cell_correlation", "correlation_length", "training_mask", "cfar_statistics_2d", "cfar_statistics",
           "noise_map", "count_clusters"]

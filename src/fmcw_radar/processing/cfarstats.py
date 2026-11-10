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

A map summed over ``K`` independent looks (the MIMO cube's virtual
channels, each with the same correlation) repeats every eigenvalue ``K``
times: the moment generating function of ``Q`` is ``prod (1 - s
lambda_k)^(-K)`` with a single positive pole of order ``K``, and the tail
is its residue,

    Pfa = (-1)^(K+1) / (K-1)!  d^(K-1)/du^(K-1) [ u^-1 prod_j (1 + u |lambda_j| / lambda_+)^(-K) ] at u = 1,

which for independent cells is the Beta(K, K N) tail ``threshold_factor``
inverts.

Detection.  A steady target of SNR ``S`` in the cell under test also sits
in its own training cells: the window's response to a tone, ``|W(k)|^2 /
|W(0)|^2``, has a mean ``c_w`` over them (the same half-bin guard), so the
threshold a target sees is ``alpha (c_w S + c |n|^2 + (1 - c) G)``.
Completing the square in the test cell's noise turns the test into a
non-central chi-square against a Gamma-distributed threshold, one integral
(``cfar_pd``): the CFAR loss on this map, self-masking included.  A
deterministic spur -- a TDC ghost target -- is such a target and its
detection probability is what it adds to a frame's false alarms.

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
from scipy.special import roots_genlaguerre
from scipy.stats import beta as _beta
from scipy.stats import gamma as _gamma
from scipy.stats import ncx2 as _ncx2

from ..config.schema import RadarConfig
from .cfar import cfar_window, threshold_factor
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


def tone_response(w: np.ndarray, pad: int, lags) -> np.ndarray:
    """The windowed, padded FFT's response to a tone sitting on a cell, read
    ``lags`` padded bins away, relative to the cell itself: the normalised
    spectrum of ``w`` (the deterministic counterpart of ``cell_correlation``)."""
    w = np.asarray(w, dtype=float)
    n = w.size
    lags = np.atleast_1d(np.asarray(lags, dtype=float))
    ph = np.exp(-2j * np.pi * lags[:, None] * np.arange(n)[None, :] / (n * pad))
    return (ph @ w) / w.sum()


def cfar_pd(snr_db, stats: dict, n_grid: int = 400) -> np.ndarray:
    """Detection probability of a steady target under the CA-CFAR that
    ``stats`` (``cfar_statistics_2d``) describes.  ``snr_db`` is the SNR in
    the cell of one look; on a K-look map every look carries it.

    With ``S`` the target's power summed over the looks, the training mean
    is ``c_w S + c sum |n_k|^2 + (1 - c) K G`` (its own leak, the test
    cell's noise, and the rest: ``G`` a Gamma of shape ``K N_eff`` and mean
    1).  ``sum |a_k + n_k|^2 > alpha x`` that, after completing the square
    in ``n_k``, is ``2 sum |n_k + a_k / (1 - alpha c)|^2`` -- non-central
    chi-square, 2K degrees, non-centrality ``2 S / (1 - alpha c)^2`` --
    against ``2 [alpha (c_w S + (1 - c) K G) + S alpha c / (1 - alpha c)] /
    (1 - alpha c)``, averaged over ``G``.  At S = 0 it is ``pfa_first_order``."""
    k = int(stats["n_looks"])
    alpha, c, c_w, n_eff = stats["threshold_factor"], stats["cut_correlation"], stats["tone_leak"], stats["n_train_eff"]
    a = alpha                                                              # the threshold is alpha x the training cells' mean (K-look sums)
    snr = 10.0 ** (np.atleast_1d(np.asarray(snr_db, dtype=float)) / 10.0)
    if a * c >= 1.0:
        return np.zeros(snr.shape)
    shape = k * n_eff
    if shape < 150.0:
        # Gauss-Laguerre on the Gamma's own weight: exact for the exponential tail the Pfa end needs
        x, wq = roots_genlaguerre(48, shape - 1.0)
        g, wq = x / shape, wq / wq.sum()
    else:
        g = _gamma.ppf((np.arange(n_grid) + 0.5) / n_grid, a=shape, scale=1.0 / shape)   # nearly a point mass: equal-probability nodes
        wq = np.full(n_grid, 1.0 / n_grid)
    s_tot = k * snr[:, None]
    rhs = (a * (c_w * s_tot + (1.0 - c) * k * g[None, :]) + s_tot * a * c / (1.0 - a * c)) / (1.0 - a * c)
    pd = _ncx2.sf(2.0 * rhs, 2 * k, np.maximum(2.0 * s_tot / (1.0 - a * c) ** 2, 1e-12))
    return pd @ wq


def cfar_snr_for_pd(pd: float, stats: dict) -> float:
    """The per-look cell SNR [dB] at which ``cfar_pd`` reaches ``pd`` (inf if
    the target's own leak into its training cells keeps it from getting there)."""
    lo, hi = -20.0, 80.0
    if float(cfar_pd(hi, stats)[0]) < pd:
        return float("inf")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(cfar_pd(mid, stats)[0]) < pd:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def correlation_length(w: np.ndarray, pad: int) -> float:
    """``sum_k |R(k)|^2`` over every padded lag: how many padded cells one
    independent look spans along this axis (``pad N sum w^4 / (sum w^2)^2``)."""
    w2 = np.asarray(w, dtype=float) ** 2
    return float(pad * w2.size * np.sum(w2 ** 2) / np.sum(w2) ** 2)


def training_mask(guard: int, train: int, shape: tuple[int, int] | None = None) -> np.ndarray:
    """The 2-D CA-CFAR's training cells around the cell under test (centre):
    the window of half-width ``guard + train`` minus the guard block, each
    clipped to a map of ``shape`` the way ``ca_cfar_2d`` clips it."""
    if shape is None:
        (h0, g0), (h1, g1) = (guard + train, guard), (guard + train, guard)
    else:
        (h0, g0), (h1, g1) = cfar_window(shape, guard, train)
    m = np.ones((2 * h0 + 1, 2 * h1 + 1), dtype=bool)
    m[h0 - g0:h0 + g0 + 1, h1 - g1:h1 + g1 + 1] = False
    return m


def _tail_of_form(lam: np.ndarray, n_looks: int) -> float:
    """P(sum_k lambda_k G_k > 0) for independent Gamma(n_looks) ``G_k`` and
    eigenvalues with exactly one positive entry: the residue at its pole."""
    lam_pos = float(lam.max())
    if lam_pos <= 0.0:
        return 0.0
    mu = -lam[lam < 0.0] / lam_pos
    k = int(n_looks)
    if k == 1:
        return float(np.exp(-np.sum(np.log1p(mu))))
    # F(u) = exp(g(u)), g = -ln u - K sum ln(1 + u mu); derivatives of g at u = 1 in closed form,
    # those of F by Leibniz: F^(n+1) = sum_i C(n, i) g^(i+1) F^(n-i).  Everything is scaled by F(1).
    r = mu / (1.0 + mu)
    gd = [0.0] + [(-1.0) ** n * math.factorial(n - 1) * (1.0 + k * float(np.sum(r ** n))) for n in range(1, k)]
    f = [1.0]
    for n in range(k - 1):
        f.append(sum(math.comb(n, i) * gd[i + 1] * f[n - i] for i in range(n + 1)))
    log_f1 = -k * float(np.sum(np.log1p(mu)))
    return float((-1.0) ** (k + 1) * f[k - 1] / math.factorial(k - 1) * math.exp(log_f1))


def cfar_statistics_2d(w_doppler: np.ndarray, pad_doppler: int, w_range: np.ndarray, pad_range: int,
                       guard: int, train: int, pfa: float, n_looks: int = 1) -> dict:
    """Effective training size, test-cell correlation and the per-cell
    false-alarm probability a 2-D CA-CFAR really has on a windowed, padded
    map of white noise (axis 0 Doppler, axis 1 range), each cell the sum of
    ``n_looks`` independent looks."""
    shape = (w_doppler.size * pad_doppler, w_range.size * pad_range)
    mask = training_mask(guard, train, shape)
    h0, h1 = mask.shape[0] // 2, mask.shape[1] // 2
    n = int(mask.sum())
    lag0 = np.arange(-2 * h0, 2 * h0 + 1)
    lag1 = np.arange(-2 * h1, 2 * h1 + 1)
    r_d = cell_correlation(w_doppler, pad_doppler, lag0)                   # complex, indexed by lag + 2 h
    r_r = cell_correlation(w_range, pad_range, lag1)
    rho = (np.abs(r_d) ** 2)[:, None] * (np.abs(r_r) ** 2)[None, :]        # power correlation at every 2-D lag
    pairs = correlate2d(mask.astype(float), mask.astype(float), mode="full")   # training-cell pairs at every lag
    n_eff = n * n / float(np.sum(pairs * rho))
    c = float(np.sum(rho[h0:3 * h0 + 1, h1:3 * h1 + 1][mask]) / n)         # lags from the centre out to +-h
    tone = (np.abs(tone_response(w_doppler, pad_doppler, lag0[h0:3 * h0 + 1])) ** 2)[:, None] \
        * (np.abs(tone_response(w_range, pad_range, lag1[h1:3 * h1 + 1])) ** 2)[None, :]
    c_w = float(np.sum(tone[mask]) / n)                                    # a tone in the test cell, seen by its training cells
    k = int(n_looks)
    alpha = threshold_factor(n, pfa, k)
    out = {"n_train": n, "n_train_eff": n_eff, "cut_correlation": c, "tone_leak": c_w, "threshold_factor": alpha, "n_looks": k,
           "window_half_doppler": h0, "window_half_range": h1,
           "correlation_length_range": correlation_length(w_range, pad_range),
           "correlation_length_doppler": correlation_length(w_doppler, pad_doppler)}

    def independent(factor: float, cells: float) -> float:
        """Pfa of K-look cells under ``factor`` over the mean of ``cells`` independent ones."""
        if k == 1:
            return float((1.0 + factor / cells) ** (-cells))
        t = factor / cells
        return float(_beta.sf(t / (1.0 + t), k, k * cells))

    # the first-order closed form and each effect alone, for the attribution
    out["pfa_training_only"] = independent(alpha, n_eff)
    if alpha * c < 1.0:
        a_eff = alpha * (1.0 - c) / (1.0 - alpha * c)
        out.update({"threshold_factor_effective": a_eff, "pfa_first_order": independent(a_eff, n_eff),
                    "pfa_cut_only": independent(a_eff, n)})
    else:
        out.update({"threshold_factor_effective": float("inf"), "pfa_first_order": 0.0, "pfa_cut_only": 0.0})
    if k > 1:
        # what the exponential (single-look) factor would do on this map, and what it costs in threshold
        a1 = threshold_factor(n, pfa, 1)
        out["pfa_with_single_look_factor"] = independent(a1, n)
        out["single_look_factor_penalty_db"] = 10.0 * math.log10(a1 / alpha)
    # the exact value: the sign of a Hermitian form in the jointly Gaussian cells (test cell first)
    dd, rr = np.nonzero(mask)
    dd = np.concatenate([[0], dd - h0])                                    # lags from the test cell
    rr = np.concatenate([[0], rr - h1])
    sigma = r_d[(dd[:, None] - dd[None, :]) + 2 * h0] * r_r[(rr[:, None] - rr[None, :]) + 2 * h1]
    a = np.full(n + 1, -alpha / n)
    a[0] = 1.0
    ev, vec = np.linalg.eigh(sigma)
    root = vec * np.sqrt(np.maximum(ev, 0.0))[None, :]                     # Sigma = root root^H
    lam = np.linalg.eigvalsh(root.conj().T @ (a[:, None] * root))
    out["pfa_cell"] = _tail_of_form(lam, k)
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
                             p.cfar_guard, p.cfar_train, p.cfar_pfa, cfg.mimo.n_virtual)
    n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * p.range_pad)       # padded range cells inside the IF band, one sign
    cells = m * p.doppler_pad * min(n_if, n * p.range_pad // 2)
    looks = cells / (out["correlation_length_range"] * out["correlation_length_doppler"])
    out.update({"pfa_design": p.cfar_pfa, "cells_in_band": cells, "independent_looks": looks,
                "false_alarm_cells_per_frame": cells * out["pfa_cell"],
                "guard_bins_range": p.cfar_guard / p.range_pad, "guard_bins_doppler": p.cfar_guard / p.doppler_pad})
    return out


def noise_map(w_doppler: np.ndarray, pad_doppler: int, w_range: np.ndarray, pad_range: int, rng: np.random.Generator,
              n_looks: int = 1) -> np.ndarray:
    """One noise-only power map (white complex noise through the two
    windowed, padded FFTs, summed over ``n_looks`` independent looks): what
    the Monte Carlo checks run the CFAR on."""
    m, n = w_doppler.size, w_range.size
    out = 0.0
    for _ in range(n_looks):
        x = (rng.standard_normal((m, n)) + 1j * rng.standard_normal((m, n))) / math.sqrt(2.0)
        y = np.fft.fft(x * w_range[None, :], n * pad_range, axis=1)
        y = np.fft.fft(y * w_doppler[:, None], m * pad_doppler, axis=0)
        out = out + np.abs(y) ** 2
    return out


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


__all__ = ["cell_correlation", "tone_response", "correlation_length", "training_mask", "cfar_statistics_2d", "cfar_statistics",
           "cfar_pd", "cfar_snr_for_pd", "noise_map", "count_clusters"]

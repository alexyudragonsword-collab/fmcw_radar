"""The simplest cell-averaging CFAR, in one and two dimensions.

For exponentially distributed cell powers (Gaussian noise, square-law
detector) the threshold factor that gives a false-alarm probability
``pfa`` with ``n`` training cells is ``alpha = n (pfa^(-1/n) - 1)``; the
threshold is ``alpha`` times the training cells' mean.  A map that is the
non-coherent sum of ``K`` looks (the MIMO cube's virtual channels) has
Gamma(K) cells instead: the test cell over the test cell plus the training
sum is Beta(K, K n), and the factor comes from its quantile -- at K = 8 it
is 4.6 dB where the exponential one is 9.7 dB.

The training window is ``guard + train`` cells each side on both axes,
clipped to what the map has: an axis shorter than the window (a frame of
eight chirps against 21 cells) would otherwise wrap round onto the cell
under test.  What the windows' and the padding's correlation make of the
false-alarm rate is ``cfarstats.py``; the detection probability at the
threshold is ``detection.py``.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d
from scipy.stats import beta as _beta


def threshold_factor(n_train: int, pfa: float, n_looks: int = 1) -> float:
    """CA-CFAR threshold over the training mean for ``pfa``: ``n (pfa^(-1/n)
    - 1)`` on exponential cells, the Beta(K, K n) quantile on cells that are
    sums of ``n_looks`` exponentials."""
    if n_looks == 1:
        return n_train * (pfa ** (-1.0 / n_train) - 1.0)
    b = float(_beta.isf(pfa, n_looks, n_looks * n_train))
    return n_train * b / (1.0 - b)


def cfar_window(shape: tuple[int, int], guard: int, train: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """``((half_0, guard_0), (half_1, guard_1))``: the training window's
    half-width and guard on each axis of a map of ``shape``, clipped so the
    window never wraps onto itself (at most ``(len - 1) // 2`` each side)."""
    out = []
    for length in shape:
        half = min(guard + train, (int(length) - 1) // 2)
        out.append((half, min(guard, half)))
    return out[0], out[1]


def ca_cfar_1d(power: np.ndarray, guard: int, train: int, pfa: float) -> tuple[np.ndarray, np.ndarray]:
    """``(threshold, detections)`` along a range profile: the mean of ``train``
    cells on each side of a ``guard`` on each side, circular."""
    power = np.asarray(power, dtype=float)
    k = 2 * (guard + train) + 1
    outer = uniform_filter1d(power, k, mode="wrap") * k
    inner = uniform_filter1d(power, 2 * guard + 1, mode="wrap") * (2 * guard + 1)
    mean = (outer - inner) / (2 * train)
    thr = threshold_factor(2 * train, pfa) * mean
    return thr, power > thr


def ca_cfar_2d(power: np.ndarray, guard: int, train: int, pfa: float, n_looks: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """The same on a range-Doppler map: a (2 guard + 1)^2 inner and a
    (2 (guard + train) + 1)^2 outer window, each clipped to the map's axes
    (``cfar_window``).  ``n_looks``: how many independent looks were summed
    into every cell."""
    power = np.asarray(power, dtype=float)
    (h0, g0), (h1, g1) = cfar_window(power.shape, guard, train)
    ko = (2 * h0 + 1, 2 * h1 + 1)
    ki = (2 * g0 + 1, 2 * g1 + 1)
    n = ko[0] * ko[1] - ki[0] * ki[1]
    if n <= 0:
        raise ValueError(f"no training cells: map {power.shape}, guard {guard}, train {train}")
    if ko[0] == ko[1] and ki[0] == ki[1]:
        outer = uniform_filter(power, ko[0], mode="wrap") * ko[0] * ko[0]
        inner = uniform_filter(power, ki[0], mode="wrap") * ki[0] * ki[0]
    else:
        outer = uniform_filter(power, ko, mode="wrap") * (ko[0] * ko[1])
        inner = uniform_filter(power, ki, mode="wrap") * (ki[0] * ki[1])
    mean = (outer - inner) / n
    thr = threshold_factor(n, pfa, n_looks) * mean
    return thr, power > thr


def detections(mask: np.ndarray) -> list[tuple[int, ...]]:
    return [tuple(int(v) for v in idx) for idx in np.argwhere(mask)]


__all__ = ["threshold_factor", "cfar_window", "ca_cfar_1d", "ca_cfar_2d", "detections"]

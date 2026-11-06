"""The simplest cell-averaging CFAR, in one and two dimensions.

For exponentially distributed cell powers (Gaussian noise, square-law
detector) the threshold factor that gives a false-alarm probability
``pfa`` with ``n`` training cells is ``alpha = n (pfa^(-1/n) - 1)``; the
threshold is ``alpha`` times the training cells' mean.  The detection
probability of a non-fluctuating target at that threshold is in
``detection.py``; the CFAR loss (the threshold's own fluctuation) is not
taken into the statistical engine's Pd -- milestone 2's detection curves
measure it.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d


def threshold_factor(n_train: int, pfa: float) -> float:
    """``n (pfa^(-1/n) - 1)``: CA-CFAR on exponential cell powers."""
    return n_train * (pfa ** (-1.0 / n_train) - 1.0)


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


def ca_cfar_2d(power: np.ndarray, guard: int, train: int, pfa: float) -> tuple[np.ndarray, np.ndarray]:
    """The same on a range-Doppler map with a square (2 guard + 1)^2 inner
    and (2 (guard + train) + 1)^2 outer window."""
    power = np.asarray(power, dtype=float)
    ko = 2 * (guard + train) + 1
    ki = 2 * guard + 1
    outer = uniform_filter(power, ko, mode="wrap") * ko * ko
    inner = uniform_filter(power, ki, mode="wrap") * ki * ki
    n = ko * ko - ki * ki
    mean = (outer - inner) / n
    thr = threshold_factor(n, pfa) * mean
    return thr, power > thr


def detections(mask: np.ndarray) -> list[tuple[int, ...]]:
    return [tuple(int(v) for v in idx) for idx in np.argwhere(mask)]


__all__ = ["threshold_factor", "ca_cfar_1d", "ca_cfar_2d", "detections"]

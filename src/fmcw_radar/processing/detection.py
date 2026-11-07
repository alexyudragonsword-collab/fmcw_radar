"""Detection and false-alarm probability of one cell (statistical).

A square-law detector on a cell of Gaussian noise and, when the target is
there, a steady (Swerling 0) tone of SNR ``snr``: the cell power is
exponential without the target and non-central chi-square with two degrees
of freedom with it.  Against a threshold ``T`` (in units of the mean noise
power) ``P_fa = e^-T`` and ``P_d = Q_1(sqrt(2 snr), sqrt(2 T))`` -- Marcum's
Q, evaluated here through scipy's non-central chi-square.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import ncx2


def threshold_for_pfa(pfa: float) -> float:
    """``T = -ln pfa`` in units of the mean noise power (known noise level)."""
    return -math.log(pfa)


def pfa_of_threshold(t: float) -> float:
    return math.exp(-t)


def pd_swerling0(snr_db, pfa: float) -> np.ndarray:
    """Detection probability of a non-fluctuating target at ``snr_db`` against
    the threshold that gives ``pfa`` with a known noise level."""
    snr = 10.0 ** (np.asarray(snr_db, dtype=float) / 10.0)
    t = threshold_for_pfa(pfa)
    return ncx2.sf(2.0 * t, 2, 2.0 * snr)


def cfar_threshold_factor(n_train: int, pfa: float) -> float:
    return n_train * (pfa ** (-1.0 / n_train) - 1.0)


def cfar_pd_swerling1(snr_db, pfa: float, n_train: int) -> np.ndarray:
    """CA-CFAR detection probability of a Swerling 1 (Rayleigh) target in
    closed form: ``(1 + alpha / (N (1 + snr)))^-N`` (Gandhi & Kassam 1988)."""
    snr = 10.0 ** (np.asarray(snr_db, dtype=float) / 10.0)
    a = cfar_threshold_factor(n_train, pfa)
    return (1.0 + a / (n_train * (1.0 + snr))) ** (-n_train)


def cfar_pd_monte_carlo(snr_db, pfa: float, n_train: int, trials: int = 100_000, seed: int = 0,
                        swerling: int = 0) -> np.ndarray:
    """CA-CFAR detection probability by simulation: ``trials`` cells of unit
    complex Gaussian noise power, a threshold ``alpha`` times the mean of
    ``n_train`` such training cells, and a target of SNR ``snr_db`` --
    steady (Swerling 0) or Rayleigh-fluctuating (Swerling 1).  ``snr_db =
    -inf`` gives the realised false-alarm rate."""
    rng = np.random.default_rng(seed)
    snr = 10.0 ** (np.asarray(snr_db, dtype=float) / 10.0)
    a = cfar_threshold_factor(n_train, pfa)
    out = np.empty(snr.shape)
    for i, s in np.ndenumerate(snr):
        noise = (rng.standard_normal(trials) + 1j * rng.standard_normal(trials)) / math.sqrt(2.0)
        train = rng.exponential(1.0, (trials, n_train)).mean(axis=1)
        if swerling == 1:
            amp = np.sqrt(s) * (rng.standard_normal(trials) + 1j * rng.standard_normal(trials)) / math.sqrt(2.0)
        else:
            amp = np.sqrt(s) * np.exp(2j * np.pi * rng.uniform(size=trials))
        cell = np.abs(amp + noise) ** 2
        out[i] = np.mean(cell > a * train)
    return out


def snr_for_pd(pd: float, pfa: float) -> float:
    """The SNR [dB] a non-fluctuating target needs for ``pd`` at ``pfa`` (bisection)."""
    lo, hi = -10.0, 40.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(pd_swerling0(mid, pfa)) < pd:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


__all__ = ["threshold_for_pfa", "pfa_of_threshold", "pd_swerling0", "snr_for_pd", "cfar_threshold_factor",
           "cfar_pd_swerling1", "cfar_pd_monte_carlo"]

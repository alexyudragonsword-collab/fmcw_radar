"""The IF high-pass (the leakage notch): a Butterworth of ``order`` at
``corner_hz``, applied causally per chirp (a real filter has a transient
at the chirp start), with its magnitude response in closed form for the
statistical side.  ``corner_hz = 0`` is no filter and returns the input
object (bit-identical to milestone 1)."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, sosfilt


def hpf_attenuation_db(f_hz: float, corner_hz: float, order: int) -> float:
    """``-20 log |H(f)|`` of the Butterworth high-pass (0 without a filter)."""
    if corner_hz <= 0.0:
        return 0.0
    if f_hz <= 0.0:
        return float("inf")
    r = (abs(f_hz) / corner_hz) ** (2 * order)
    return float(-10.0 * math.log10(r / (1.0 + r)))


def hpf_response(f_hz, corner_hz: float, order: int) -> np.ndarray:
    """|H(f)| on a grid (1 without a filter)."""
    f = np.asarray(f_hz, dtype=float)
    if corner_hz <= 0.0:
        return np.ones(f.shape)
    r = (np.abs(f) / corner_hz) ** (2 * order)
    return np.sqrt(r / (1.0 + r))


def hpf_sos(fs: float, corner_hz: float, order: int) -> np.ndarray:
    return butter(order, corner_hz, btype="highpass", fs=fs, output="sos")


def apply_hpf(x: np.ndarray, fs: float, corner_hz: float, order: int, state=None, sos=None):
    """The filter on a complex beat record (I and Q alike), causal, with the
    state carried from the previous record (``state`` -> ``(y, state)``;
    without it just ``y``).  The receiver's filter runs on across chirps:
    the leakage tone it is there for never stops, so a state reset at every
    chirp would put a transient the hardware does not have at each start."""
    if corner_hz <= 0.0:
        return x if state is None else (x, state)
    sos = hpf_sos(fs, corner_hz, order) if sos is None else sos
    if state is None:
        return sosfilt(sos, x.real) + 1j * sosfilt(sos, x.imag)
    zr, zi = state
    yr, zr = sosfilt(sos, x.real, zi=zr)
    yi, zi = sosfilt(sos, x.imag, zi=zi)
    return yr + 1j * yi, (zr, zi)


def hpf_initial_state(sos: np.ndarray):
    """A zero state pair (I, Q) for ``apply_hpf``."""
    z = np.zeros((sos.shape[0], 2))
    return z, z.copy()


__all__ = ["hpf_attenuation_db", "hpf_response", "apply_hpf", "hpf_sos", "hpf_initial_state"]

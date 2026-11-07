"""Window functions and what they do to a tone: coherent gain, noise
bandwidth, mainlobe width (the numbers the resolution table rests on).

Windows are DFT-even (``sym=False``), the form Harris 1978 tabulates and
the one a spectral analysis uses.  ``mainlobe_width_bins`` reads the width
from the window's own zero-padded spectrum -- the *theory* side of the
resolution acceptance -- while the engines measure the same width on a
processed point target; the survey table (``window.*_3db_bins``, Harris's
two-digit values) is a third, external, reading of the same thing.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import windows as _w

NAMES = ("rect", "hann", "hamming", "blackman")


def window(name: str, n: int) -> np.ndarray:
    if name == "rect":
        return np.ones(n)
    if name == "hann":
        return _w.hann(n, sym=False)
    if name == "hamming":
        return _w.hamming(n, sym=False)
    if name == "blackman":
        return _w.blackman(n, sym=False)
    raise ValueError(f"unknown window {name!r} (one of {NAMES})")


def range_window(name: str, n: int, n_blank: int = 0) -> np.ndarray:
    """The range window of a chirp of ``n`` beat samples whose first
    ``n_blank`` are blanked (the flyback transient through the IF
    high-pass): zeros there, then the window fitted to the samples that
    remain.  Zeroing the samples under an unchanged window would leave a
    step at the blank's edge and raise the window's far sidelobes by tens
    of dB; refitting keeps the sidelobes and widens the lobe by
    ``n / (n - n_blank)``.  With no blanking this is ``window(name, n)``."""
    if n_blank <= 0:
        return window(name, n)
    if n_blank >= n:
        raise ValueError(f"blanking {n_blank} of {n} samples leaves nothing")
    w = np.zeros(n)
    w[n_blank:] = window(name, n - n_blank)
    return w


def coherent_gain_db(w: np.ndarray) -> float:
    """SNR gain of a windowed FFT on a tone against white noise:
    ``(sum w)^2 / sum w^2`` (N for a rectangular window)."""
    w = np.asarray(w, dtype=float)
    return 10.0 * math.log10(float(np.sum(w)) ** 2 / float(np.sum(w * w)))


def enbw_bins(w: np.ndarray) -> float:
    """Equivalent noise bandwidth in bins: ``N sum w^2 / (sum w)^2`` (1 for rect, 1.5 for Hann)."""
    w = np.asarray(w, dtype=float)
    return w.size * float(np.sum(w * w)) / float(np.sum(w)) ** 2


def enbw_hz(w: np.ndarray, fs: float) -> float:
    """The same in Hz on a record sampled at ``fs``: ``fs sum w^2 / (sum w)^2``."""
    return enbw_bins(w) * fs / w.size


def spectrum_db(w: np.ndarray, pad: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """``(offset in bins, |W|^2 in dB relative to the peak)`` of the window's
    zero-padded spectrum, centred."""
    n = w.size
    m = n * pad
    s = np.abs(np.fft.fftshift(np.fft.fft(w, m))) ** 2
    s = 10.0 * np.log10(np.maximum(s / s.max(), 1e-300))
    bins = (np.arange(m) - m // 2) / pad
    return bins, s


def width_at_level(x: np.ndarray, y_db: np.ndarray, level_db: float) -> float:
    """Full width of the lobe around the peak of ``y_db`` at ``level_db``
    below it, with linear interpolation across the crossing on each side."""
    i0 = int(np.argmax(y_db))
    thr = y_db[i0] + level_db

    def cross(step):
        i = i0
        while 0 <= i + step < y_db.size and y_db[i + step] >= thr:
            i += step
        j = i + step
        if not (0 <= j < y_db.size):
            return x[i]
        frac = (y_db[i] - thr) / (y_db[i] - y_db[j])
        return x[i] + frac * (x[j] - x[i])

    return float(abs(cross(+1) - cross(-1)))


def mainlobe_width_bins(name: str, n: int = 1024, level_db: float = -3.0, pad: int = 64, n_blank: int = 0) -> float:
    """The window's mainlobe width at ``level_db`` [bins], from its own spectrum."""
    bins, s = spectrum_db(range_window(name, n, n_blank), pad)
    return width_at_level(bins, s, level_db)


def peak_sidelobe_db(name: str, n: int = 1024, pad: int = 64, n_blank: int = 0) -> float:
    """Highest sidelobe of the window's spectrum relative to its peak [dB]."""
    bins, s = spectrum_db(range_window(name, n, n_blank), pad)
    return float(peak_sidelobe_of(bins, s))


def peak_sidelobe_of(x: np.ndarray, y_db: np.ndarray) -> float:
    """Highest sidelobe of a lobe shape: the maximum beyond the first null on
    either side of the peak.  A side whose main lobe runs off the end of
    ``x`` before a null (a beam steered near the edge of the u grid) has no
    sidelobe to read and contributes nothing."""
    i0 = int(np.argmax(y_db))

    def first_null(step):
        i = i0
        while 0 <= i + step < y_db.size and y_db[i + step] <= y_db[i]:
            i += step
        return i if 0 <= i + step < y_db.size else None

    lo, hi = first_null(-1), first_null(+1)
    parts = [y_db[:lo + 1] if lo is not None else y_db[:0], y_db[hi:] if hi is not None else y_db[:0]]
    outside = np.concatenate(parts)
    return float(outside.max() - y_db[i0]) if outside.size else float("-inf")


__all__ = ["NAMES", "window", "range_window", "coherent_gain_db", "enbw_bins", "enbw_hz", "spectrum_db", "width_at_level",
           "mainlobe_width_bins", "peak_sidelobe_db", "peak_sidelobe_of"]

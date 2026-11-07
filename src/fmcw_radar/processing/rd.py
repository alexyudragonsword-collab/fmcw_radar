"""Range FFT, Doppler FFT, the axes, and how a point target's response is read.

The beat frame is ``(n_chirps, n_samples)`` complex.  The range FFT runs
along the samples (zero-padded ``range_pad`` times for a finer read of the
profile; the resolution is the window's, not the padding's), the Doppler
FFT along the chirps, centred with ``fftshift`` so the velocity axis runs
``-v_max .. +v_max``.
"""

from __future__ import annotations

import numpy as np

from ..config.schema import C0, RadarConfig
from .windows import peak_sidelobe_of, width_at_level, window


def range_fft(frame: np.ndarray, name: str, pad: int = 1) -> np.ndarray:
    """Windowed FFT along the last axis; the window is normalised to unit
    sum so a tone of amplitude A reads A at its bin."""
    frame = np.asarray(frame)
    n = frame.shape[-1]
    w = window(name, n)
    w = w / w.sum()
    return np.fft.fft(frame * w, n * pad, axis=-1)


def doppler_fft(ranged: np.ndarray, name: str, pad: int = 1) -> np.ndarray:
    """Windowed FFT along the first axis (chirps), centred."""
    ranged = np.asarray(ranged)
    m = ranged.shape[0]
    w = window(name, m)
    w = w / w.sum()
    w = w.reshape((-1,) + (1,) * (ranged.ndim - 1))                  # the chirp axis first, whatever follows
    return np.fft.fftshift(np.fft.fft(ranged * w, m * pad, axis=0), axes=0)


def range_doppler_map(frame: np.ndarray, cfg: RadarConfig) -> np.ndarray:
    """Complex range-Doppler map ``(n_chirps x doppler_pad, n_samples x range_pad)``
    of a beat frame, the config's windows and padding."""
    p = cfg.processing
    return doppler_fft(range_fft(frame, p.window_range, p.range_pad), p.window_doppler, p.doppler_pad)


def range_axis_m(cfg: RadarConfig, n_fft: int) -> np.ndarray:
    """Range of each range bin: ``f c / (2 S)`` with f the FFT bin frequency (0 .. fs)."""
    f = np.fft.fftfreq(n_fft, d=1.0 / cfg.rx.adc_fs_hz)
    return f * C0 / (2.0 * cfg.slope_hz_per_s)


def velocity_axis_mps(cfg: RadarConfig, n_fft: int) -> np.ndarray:
    """Radial velocity of each (centred) Doppler bin, positive receding:
    ``v = f_d lambda / 2`` (``RadarConfig.doppler_hz`` has the sign)."""
    fd = np.fft.fftshift(np.fft.fftfreq(n_fft, d=cfg.chirp.pri_s))
    return fd * cfg.band.wavelength_m / 2.0


def power_db(x: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(np.abs(x) ** 2, 1e-300))


def read_peak(axis: np.ndarray, profile_db: np.ndarray, level_db: float = -3.0) -> dict:
    """Where the peak is (parabolic interpolation in dB), how wide the lobe
    is at ``level_db`` (and at the Rayleigh level -3.92 dB, where a
    rectangular window's lobe is exactly one bin wide), its highest sidelobe."""
    i = int(np.argmax(profile_db))
    pos = float(axis[i])
    if 0 < i < profile_db.size - 1:
        a, b, c = profile_db[i - 1], profile_db[i], profile_db[i + 1]
        den = a - 2.0 * b + c
        if den < 0.0:
            d = 0.5 * (a - c) / den
            pos = float(axis[i] + d * (axis[1] - axis[0]))
    return {"peak_db": float(profile_db[i]), "peak_index": i, "peak_pos": pos,
            "width_3db": width_at_level(axis, profile_db, level_db),
            "width_rayleigh": width_at_level(axis, profile_db, 20.0 * np.log10(2.0 / np.pi)),
            "peak_sidelobe_db": peak_sidelobe_of(axis, profile_db)}


def noise_floor(power_map: np.ndarray, peak_rc: tuple[int, int], exclude: tuple[int, int]) -> float:
    """Mean cell power away from the target: cells farther than ``exclude``
    (Doppler, range) bins from the peak (circularly in Doppler, which is
    centred; linearly in range, which may be a cropped band)."""
    m, n = power_map.shape
    d_i = np.abs((np.arange(m) - peak_rc[0] + m // 2) % m - m // 2)
    d_j = np.abs(np.arange(n) - peak_rc[1])
    mask = (d_i[:, None] > exclude[0]) & (d_j[None, :] > exclude[1])
    return float(np.mean(power_map[mask]))


__all__ = ["range_fft", "doppler_fft", "range_doppler_map", "range_axis_m", "velocity_axis_mps", "power_db",
           "read_peak", "noise_floor"]

"""The occupied band of the transmitted chirp, measured as the rule's
definition has it (0.2.35, fmcw_radar#46).

47 CFR 2.1049 / 2.202(a): the occupied bandwidth is the band below whose
lower limit and above whose upper limit the mean powers radiated are each a
stated share of the emission's total mean power -- the share is read from
the source table (``fcc2.occupied_bandwidth.power_outside_each_limit_pct``),
not written here.  FCC 23-35 para. 62 has a 60 GHz radar's occupied
bandwidth measured that way as part of its compliance measurements, the
device sweeping normally.

How it is measured here.  A chirp is a constant-envelope emission whose
frequency moves through the band: with a time-bandwidth product far above
one its power spectrum is the distribution of its instantaneous frequency
(stationary phase), so the limits are two quantiles, in time, of the
frequency the loop actually produced -- ``chirp.engine``'s trajectory, the
ramp's overshoot and settling in it, not the commanded line.  The spectrum
itself (the trajectory integrated to a phase and transformed) gives the same
limits to the spectrum's own edge width, about ``sqrt(B / T)``:
``occupied_band_from_spectrum`` is that second route, kept for the tests.

What a linear sweep gives: the power is spread evenly over the sweep, so the
outer share at each end lies in the outer share of the sweep, and the
occupied band is *inside* the commanded one by that much.  The loop's
overshoot past a commanded edge lasts a thousandth of a ramp and does not
move a limit.  The commanded sweep the compliance check judges on is
therefore the wider, stricter reading -- for a transmitter that is on during
the ramps only.  If it stays on through the idle time between ramps
(``chirp.idle_s``), the flyback's transient and the parked LO are part of the
emission and its lower limit moves to (or past) the commanded edge:
``with_idle`` in the result is that emission, reported whenever there is idle
time, because this library does not model whether the PA is keyed off there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..chirp import ChirpResult
    from ..config.schema import RadarConfig


def occupied_band(freq_hz, outside_each_limit_pct: float) -> tuple[float, float]:
    """``(lower, upper)`` limits [Hz] of the occupied band of a
    constant-envelope emission whose instantaneous frequency is ``freq_hz``,
    sampled evenly in time: the frequencies below / above which it spends
    ``outside_each_limit_pct`` percent of its time (and so radiates that
    share of its mean power)."""
    f = np.asarray(freq_hz, dtype=float)
    if f.size == 0:
        raise ValueError("occupied_band: no samples of the emission's frequency")
    share = outside_each_limit_pct / 100.0
    lo, hi = np.quantile(f, [share, 1.0 - share])
    return float(lo), float(hi)


def occupied_band_from_spectrum(freq_hz, sample_rate_hz: float, outside_each_limit_pct: float, fs_hz: float) -> tuple[float, float]:
    """The same limits read off the emission's power spectrum: the
    trajectory (one value per ``1 / sample_rate_hz``, held) integrated to a
    phase on a grid of ``fs_hz``, transformed, and the cumulative power cut at
    the share on either side.  ``fs_hz`` has to hold the whole excursion."""
    f = np.asarray(freq_hz, dtype=float)
    up = int(round(fs_hz / sample_rate_hz))
    if up < 1 or 2.0 * np.max(np.abs(f)) >= fs_hz:
        raise ValueError(f"occupied_band_from_spectrum: fs = {fs_hz:g} Hz does not hold a +-{np.max(np.abs(f)):g} Hz excursion")
    x = np.exp(2j * np.pi * np.cumsum(np.repeat(f, up)) / fs_hz)
    p = np.abs(np.fft.fftshift(np.fft.fft(x))) ** 2
    axis = np.fft.fftshift(np.fft.fftfreq(x.size, 1.0 / fs_hz))
    c = np.cumsum(p) / np.sum(p)
    share = outside_each_limit_pct / 100.0
    return float(axis[np.searchsorted(c, share)]), float(axis[np.searchsorted(c, 1.0 - share)])


def _trajectories(cfg: RadarConfig, chirp: ChirpResult | None) -> tuple[np.ndarray, np.ndarray | None, str]:
    """The carrier's deviation from the band centre [Hz] over the ramps the
    transmitter is taken to be on in, the same with the idle time between
    them (None without any), and the engine it came from.  The loop's first
    ramp is its start-up and is left out when there is another."""
    b = cfg.band.sweep_hz
    if chirp is None or chirp.engine == "ideal":
        n = max(int(round(cfg.chirp.duration_s * cfg.lo.fref_hz)), 2)
        ramp = -0.5 * b + b * np.arange(n) / n
        n_idle = int(round(cfg.chirp.idle_s * cfg.lo.fref_hz))
        return ramp, (np.concatenate([ramp, np.full(n_idle, ramp[0])]) if n_idle else None), "ideal"
    f = chirp.mult * (np.asarray(chirp.f_cmd_dco_hz) + np.asarray(chirp.f_err_dco_hz))
    first = 1 if chirp.n_chirps > 1 else 0
    pri = chirp.pri_cycles
    ramps = np.concatenate([f[k * pri:k * pri + chirp.n_ramp] for k in range(first, chirp.n_chirps)])
    whole = f[first * pri:chirp.n_chirps * pri] if chirp.n_idle else None
    return ramps, whole, chirp.engine


def _summary(f: np.ndarray, f_centre: float, b: float, pct: float) -> dict:
    lo, hi = occupied_band(f, pct)
    c_lo, c_hi = -0.5 * b, 0.5 * b
    return {"lo_hz": f_centre + lo, "hi_hz": f_centre + hi, "bandwidth_hz": hi - lo,
            "margin_lo_hz": lo - c_lo, "margin_hi_hz": c_hi - hi,                 # inside the commanded edge when positive
            "inside_commanded": bool(lo >= c_lo and hi <= c_hi),
            "excursion_lo_hz": float(max(0.0, c_lo - np.min(f))), "excursion_hi_hz": float(max(0.0, np.max(f) - c_hi)),
            "time_outside_lo_pct": float(100.0 * np.mean(f < c_lo)), "time_outside_hi_pct": float(100.0 * np.mean(f > c_hi))}


def chirp_occupied_band(cfg: RadarConfig, chirp: ChirpResult | None = None) -> dict:
    """The occupied band of the config's chirp train as its LO made it (the
    report's ``compliance.occupied_band``): the limits and the bandwidth,
    where they sit against the commanded sweep, how far and for how long the
    frequency goes past a commanded edge -- over the ramps, and again with
    the idle time between them when there is any."""
    from ..sources import number

    share = number("fcc2.occupied_bandwidth.power_outside_each_limit_pct")
    pct = float(share.value)
    b, fc = cfg.band.sweep_hz, cfg.band.center_hz
    ramps, whole, engine = _trajectories(cfg, chirp)
    out = {"quantity": number("fcc15255.radar_occupied_bandwidth.quantity").value,
           "codified": number("fcc15255.radar_occupied_bandwidth.codified").value,
           "outside_each_limit_pct": pct, "source": share.source,
           "method": "the instantaneous frequency of the chirp engine's LO over the ramps (its start-up ramp left out), "
                     "the limits its quantiles in time: the spectrum of a sweep with a time-bandwidth product far above one",
           "engine": engine, "time_bandwidth": b * cfg.chirp.duration_s,
           "commanded_lo_hz": fc - 0.5 * b, "commanded_hi_hz": fc + 0.5 * b, "commanded_bw_hz": b,
           **_summary(ramps, fc, b, pct),
           "with_idle": None if whole is None else _summary(whole, fc, b, pct)}
    return out


__all__ = ["occupied_band", "occupied_band_from_spectrum", "chirp_occupied_band"]

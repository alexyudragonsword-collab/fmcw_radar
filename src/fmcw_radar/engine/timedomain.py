"""The time-domain engine: a real waveform, a real mixer, a real FFT (invariant #3's cross-check).

Per chirp, on a complex-envelope grid of ``time_osr x B`` samples per second
(the envelope of a 4 GHz sweep needs 4 GS/s; the carrier itself never has
to be sampled)::

    TX(t) = exp(j [Phi(t) + psi(t)])                  Phi: the ideal sweep, psi: LO error (chirp + phase noise)
    RX(t) = A TX(t - tau(t))                           tau(t) = 2 (R + v t) / c, the carrier term 2 pi f_c tau included
    beat  = TX conj(RX) + noise -> brick-wall IF filter -> ADC rate -> quantiser

The ideal part of ``Phi(t) - Phi(t - tau)`` is written out exactly (a
quadratic in t, nothing is sampled at RF); the LO's error phase ``psi`` is a
sampled sequence delayed by the same ``tau``: the chirp engine's curve
interpolated at ``t`` and ``t - tau`` (exact, the phase is piecewise linear
on the reference grid), the phase noise synthesised from the LO profile and
delayed in the FFT domain.  Range correlation is therefore not modelled
here -- it *happens*, which is what makes this engine the check of the
closed form.  The phase noise is synthesised per chirp (independent blocks
of one ramp): below ``1 / T_c`` the residual ``2 (1 - cos 2 pi f tau)``
is 50 dB down at any range in the IF band, so chirp-to-chirp correlation
of the LO noise is not represented and not needed (the Doppler dimension's
noise floor is the thermal one).

Switches (``noise``, ``phase_noise``, ``quantise``) exist for the
consistency tests, not for the config: a radar has all three.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..chirp import ChirpEngine, ChirpResult
from ..config.schema import RadarConfig
from ..link.budget import adc_amplitudes, link_budget
from ..lo import LOProfile
from ..phase_noise import RangeCorrelation
from ..processing.cfar import ca_cfar_2d
from ..processing.rd import (noise_floor, power_db, range_axis_m, range_doppler_map, range_fft, read_peak,
                             velocity_axis_mps)
from ..processing.windows import enbw_bins, window

TWOPI = 2.0 * np.pi


@dataclass
class TimeResult:
    frame: np.ndarray                   # the beat frame at the ADC (n_chirps, n_samples), volts
    rd_db: np.ndarray                   # range-Doppler power map [dB], (doppler, range)
    range_axis_m: np.ndarray
    velocity_axis_mps: np.ndarray
    peak_range_m: float
    peak_velocity_mps: float
    snr_cell_db: float                  # peak over the mean noise cell, away from the target
    n_chirps: int
    range_profile_db: np.ndarray        # the last chirp's range profile [dB], padded
    range_profile_axis_m: np.ndarray
    width_3db_m: float
    width_rayleigh_m: float
    peak_sidelobe_db: float
    cfar_detections: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)


def beat_frame(cfg: RadarConfig, chirp: ChirpResult | None, *, noise: bool = True, phase_noise: bool = True,
               quantise: bool = True, seed: int | None = None, n_chirps: int | None = None,
               rc: RangeCorrelation | None = None) -> tuple[np.ndarray, dict]:
    """The ADC frame ``(n_chirps, n_samples)`` and a dict of what was used."""
    seed = cfg.sim.seed if seed is None else seed
    rng = np.random.default_rng(seed)
    m_chirps = cfg.time_chirps() if n_chirps is None else n_chirps
    budget = link_budget(cfg)
    a_s, a_fs, n0_50 = adc_amplitudes(cfg, budget)
    fs_w = cfg.sim.time_osr * cfg.band.sweep_hz
    n_w = int(round(cfg.chirp.duration_s * fs_w))
    n_adc = cfg.n_samples
    if abs(cfg.chirp.duration_s * fs_w - n_w) > 1e-6 or n_w % n_adc != 0:
        raise ValueError(f"time engine: the envelope grid ({fs_w:g} S/s over {cfg.chirp.duration_s:g} s) must hold a "
                         f"whole multiple of the ADC's {n_adc} samples; change sim.time_osr")
    t = np.arange(n_w) / fs_w
    f_c, b, s = cfg.band.center_hz, cfg.band.sweep_hz, cfg.slope_hz_per_s
    r0, v = cfg.target.range_m, cfg.target.velocity_mps
    pri = cfg.chirp.pri_s
    c0 = 299_792_458.0
    # the LO error phase along the whole frame on the reference grid
    if chirp is not None and chirp.engine != "ideal":
        t_ref = np.arange(chirp.f_err_dco_hz.size) / chirp.fref_hz
        psi_ref = chirp.phase_err_carrier_rad()
    else:
        t_ref = psi_ref = None
    if phase_noise:
        rc = RangeCorrelation(LOProfile.from_config(cfg), cfg.tau_s()) if rc is None else rc
    # the IF brick wall and the decimation: the two grids share the bin spacing 1 / T_c
    f_w = np.fft.fftfreq(n_w, d=1.0 / fs_w)
    keep = np.abs(f_w) <= cfg.rx.if_bw_hz
    f_adc = np.fft.fftfreq(n_adc, d=1.0 / cfg.rx.adc_fs_hz)
    idx_adc = np.rint(f_adc * cfg.chirp.duration_s).astype(int) % n_w
    sigma = math.sqrt(n0_50 * fs_w)
    step = 2.0 * a_fs / (2 ** cfg.rx.adc_bits)
    frame = np.empty((m_chirps, n_adc), dtype=complex)
    for m in range(m_chirps):
        tau = 2.0 * (r0 + v * (m * pri + t)) / c0
        phase = TWOPI * (f_c - 0.5 * b) * tau + TWOPI * s * tau * t - math.pi * s * tau * tau
        if psi_ref is not None:
            t_abs = m * pri + t
            phase = phase + np.interp(t_abs, t_ref, psi_ref) - np.interp(t_abs - tau, t_ref, psi_ref)
        if phase_noise:
            pn = rc.synthesize_lo(n_w, fs_w, rng)
            phase = phase + rc.residual(pn, fs_w)
            for f0, a in rc.profile.spurs:
                ph0 = rng.uniform(0.0, TWOPI)
                t_abs = m * pri + t
                phase = phase + a * (np.sin(TWOPI * f0 * t_abs + ph0) - np.sin(TWOPI * f0 * (t_abs - tau) + ph0))
        x = a_s * np.exp(1j * phase)
        if noise:
            x = x + (sigma / math.sqrt(2.0)) * (rng.standard_normal(n_w) + 1j * rng.standard_normal(n_w))
        spec = np.fft.fft(x)
        spec = np.where(keep, spec, 0.0)
        y = np.fft.ifft(spec[idx_adc]) * (n_adc / n_w)
        if quantise:
            y = np.clip(np.round(y.real / step) * step, -a_fs, a_fs) + 1j * np.clip(np.round(y.imag / step) * step,
                                                                                  -a_fs, a_fs)
        frame[m] = y
    info = {"fs_wave_hz": fs_w, "n_wave": n_w, "signal_amplitude_v": a_s, "fullscale_v": a_fs,
            "noise_sigma_wave_v": sigma, "adc_step_v": step, "budget": budget, "n_chirps": m_chirps}
    return frame, info


def process_frame(cfg: RadarConfig, frame: np.ndarray, info: dict | None = None) -> TimeResult:
    """Window + range FFT + Doppler FFT + CFAR on an ADC frame; the target read off the map."""
    m_chirps, n = frame.shape
    rd = range_doppler_map(frame, cfg)
    p = np.abs(rd) ** 2
    rd_db = 10.0 * np.log10(np.maximum(p, 1e-300))
    n_r = n * cfg.processing.range_pad
    n_d = m_chirps * cfg.processing.doppler_pad
    r_axis = range_axis_m(cfg, n_r)
    v_axis = velocity_axis_mps(cfg, n_d)
    half = n_r // 2
    sub = p[:, :half]                                    # positive beat frequencies only
    i, j = np.unravel_index(int(np.argmax(sub)), sub.shape)
    excl = (min(max(2, n_d // 8), max(n_d // 2 - 1, 0)), max(8, half // 16))   # a 2-chirp frame keeps its other row
    # the noise floor is read inside the IF band only: beyond it the brick
    # wall leaves empty cells that would read the mean low
    n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * cfg.processing.range_pad)
    floor = noise_floor(p[:, :min(n_if, half)], (i, j), excl)
    snr = 10.0 * math.log10(p[i, j] / floor) if floor > 0.0 else float("inf")
    prof = power_db(range_fft(frame[-1], cfg.processing.window_range, cfg.processing.range_pad))[:half]
    rp = read_peak(r_axis[:half], prof)
    _, det = ca_cfar_2d(p, cfg.processing.cfar_guard, cfg.processing.cfar_train, cfg.processing.cfar_pfa)
    dets = [(float(v_axis[a]), float(r_axis[b])) for a, b in np.argwhere(det[:, :half])]
    res = TimeResult(frame=frame, rd_db=rd_db, range_axis_m=r_axis, velocity_axis_mps=v_axis,
                     peak_range_m=float(r_axis[j]), peak_velocity_mps=float(v_axis[i]), snr_cell_db=snr,
                     n_chirps=m_chirps, range_profile_db=prof - prof.max(), range_profile_axis_m=r_axis[:half],
                     width_3db_m=rp["width_3db"], width_rayleigh_m=rp["width_rayleigh"],
                     peak_sidelobe_db=rp["peak_sidelobe_db"], cfar_detections=dets,
                     extras={"peak_rc": (int(i), int(j)), "noise_floor": floor, "peak_power": float(p[i, j]),
                             "peak_range_interp_m": rp["peak_pos"]})
    if info:
        res.extras.update({k: v for k, v in info.items() if k != "budget"})
    return res


def run_time(cfg: RadarConfig, chirp: ChirpResult | None = None, **kw) -> TimeResult:
    if chirp is None and cfg.lo.engine != "ideal":
        chirp = ChirpEngine(cfg).run(noise=False, n_chirps=cfg.time_chirps())
    frame, info = beat_frame(cfg, chirp, **kw)
    return process_frame(cfg, frame, info)


def measured_pn_sidelobes(cfg: RadarConfig, offsets_m, n_chirps: int = 32, seed: int | None = None,
                          half_bins: int = 3, window_name: str | None = None) -> dict:
    """The phase-noise sidelobe at each range offset as the range FFT measures
    it: ``n_chirps`` noiseless, unquantised chirps with phase noise only,
    their range profiles averaged, read in a band of ``2 half_bins + 1``
    (unpadded) bins around each offset, relative to the tone's peak [dBc].
    The window's own sidelobes add to what is read: a Hann window sits at
    -32 dB three bins out and falls 18 dB per octave, so offsets under ten
    bins want ``window_name = "blackman"`` (-58 dB) to see the noise."""
    from .statistical import beat_sideband

    name = cfg.processing.window_range if window_name is None else window_name
    rc = RangeCorrelation(LOProfile.from_config(cfg), cfg.tau_s())
    sb = beat_sideband(cfg, rc)
    frame, _ = beat_frame(cfg, None, noise=False, phase_noise=True, quantise=False, seed=seed, n_chirps=n_chirps,
                          rc=rc)
    spec = range_fft(frame, name, 1)
    p = np.mean(np.abs(spec) ** 2, axis=0)
    n = cfg.n_samples
    df = cfg.rx.adc_fs_hz / n
    enbw = enbw_bins(window(name, n)) * df
    peak = int(np.argmax(p))
    # the tone's power read on a 16x padded grid: its peak bin on the plain
    # grid sits up to half a bin off and loses up to 1 dB of scalloping the
    # noise bins do not (a 5 m target's beat lands 0.43 bins off: +0.75 dB)
    tone = float(np.max(np.mean(np.abs(range_fft(frame, name, 16)) ** 2, axis=0)))
    out = {}
    for dr in offsets_m:
        k = int(round(cfg.slope_hz_per_s * cfg.tau_s(dr) / df))
        band = [(peak + k + d) % n for d in range(-half_bins, half_bins + 1)]
        measured = 10.0 * math.log10(float(np.mean(p[band])) / tone)
        # the closed form averaged over the same bins (the residual PSD curves
        # across a band: its mean is not its value at the centre)
        offs = (k + np.arange(-half_bins, half_bins + 1)) * df
        closed = 10.0 * math.log10(float(np.mean(10.0 ** (sb.sidelobe_dbc(offs, enbw) / 10.0))))
        first = 10.0 * math.log10(float(np.mean(10.0 ** (rc.sidelobe_dbc(np.abs(offs), enbw) / 10.0))))
        out[float(dr)] = {"measured_dbc": measured, "closed_form_dbc": closed, "first_order_dbc": first, "bins": int(k)}
    return out


__all__ = ["TimeResult", "beat_frame", "process_frame", "run_time", "measured_pn_sidelobes"]

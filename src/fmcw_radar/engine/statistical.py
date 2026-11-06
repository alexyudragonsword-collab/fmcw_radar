"""The statistical engine: the range-Doppler map's SNR, sidelobes and detection
probability in closed form (invariant #3: this is the main engine).

Nothing here is simulated with noise.  The point target's cell SNR comes
from the radar equation and the windows' coherent gains (``link.budget``);
the phase-noise sidelobes from the range-correlated residual PSD and the
range FFT's noise bandwidth (``phase_noise``); the resolution and the window
sidelobes from the window's own spectrum; the chirp-nonlinearity sidelobes
from the chirp engine's frequency-error curve fed straight into one range
FFT (``nonlinearity_profile``: the beat phase a frequency error ``f_err(t)``
leaves is ``2 pi integral_{t - tau}^{t} f_err``, which is what the time
engine's mixer produces from the same curve -- tests/test_engines.py holds
the two together).  The time engine (``timedomain``) exists to check these
numbers on a real waveform, not to produce them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..chirp import ChirpEngine, ChirpResult
from ..config.schema import C0, RadarConfig
from ..link.budget import LinkBudget, link_budget
from ..lo import LOProfile
from ..phase_noise import RangeCorrelation
from ..processing.detection import pd_swerling0
from ..processing.rd import power_db, range_axis_m, range_fft, read_peak, velocity_axis_mps
from ..processing.windows import (coherent_gain_db, enbw_bins, mainlobe_width_bins, peak_sidelobe_db, spectrum_db,
                                  window)

TWOPI = 2.0 * np.pi

#: range offsets [m] from the target the report tabulates the phase-noise floor at
REPORT_OFFSETS_M = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0)


@dataclass
class StatResult:
    budget: LinkBudget
    beat_hz: float
    doppler_hz: float
    range_bin: float                    # the target's beat frequency in (unpadded) range bins
    doppler_bin: float                  # the Doppler frequency in (unpadded) Doppler bins, from the centre
    snr_cell_db: float
    snr_chirp_db: float
    pd: float                           # at the config's CFAR pfa, known noise level (no CFAR loss)
    range_res_rect_m: float             # c / 2B
    range_res_m: float                  # the window's -3 dB mainlobe x c / 2B
    range_res_rayleigh_m: float         # the window's lobe at -3.92 dB x c / 2B (= c / 2B for rect)
    velocity_res_mps: float
    window_sidelobe_db: float           # the range window's highest sidelobe
    pn_floor: dict = field(default_factory=dict)      # offset [m] -> (single-chirp dBc per bin, per RD cell)
    pn_rms_rad: float = 0.0             # residual phase RMS over [1 / T_c, if_bw]
    lo_rms_rad: float = 0.0             # the LO's own, same band
    nonlinearity: dict = field(default_factory=dict)  # from the chirp curve: width, sidelobe, ISLR
    chirp: dict = field(default_factory=dict)         # the chirp engine's metrics
    extras: dict = field(default_factory=dict)


def scalloping_loss_db(cfg: RadarConfig) -> tuple[float, float]:
    """``(range, Doppler)`` loss [dB] of reading the target at the nearest
    cell of the (padded) grids instead of at its exact frequency: the
    window's spectrum at the fractional-bin offset.  A Hann window loses
    1.4 dB half a bin out; the padding factors put the grid closer."""
    n, m = cfg.n_samples, cfg.chirp.n_chirps
    p = cfg.processing
    dims = ((p.window_range, cfg.beat_hz() * cfg.chirp.duration_s, p.range_pad, n),
            (p.window_doppler, cfg.doppler_hz() * cfg.chirp.pri_s * m, p.doppler_pad, m))
    out = []
    for name, bin_, pad, length in dims:
        frac = bin_ * pad - round(bin_ * pad)          # offset from the nearest padded cell, in padded bins
        w = window(name, length)
        k = np.arange(length)
        resp = np.abs(np.sum(w * np.exp(-2j * np.pi * (frac / pad) * k / length))) / np.sum(w)
        out.append(float(-20.0 * np.log10(max(resp, 1e-300))))
    return out[0], out[1]


def pn_floor_mean_cell(cfg: RadarConfig, rc: RangeCorrelation, exclude_m: float) -> float:
    """The phase-noise floor per range-Doppler cell averaged over the IF
    band's range bins farther than ``exclude_m`` from the target, relative
    to the target's peak (linear): what a map-wide noise estimate (the time
    engine's) sees of the LO noise on top of the thermal floor."""
    n = cfg.n_samples
    df = cfg.rx.adc_fs_hz / n
    n_if = int(cfg.rx.if_bw_hz / df)
    offs = (np.arange(n_if) - round(cfg.beat_hz() / df)) * df
    dr = np.abs(offs) / cfg.slope_hz_per_s * C0 / 2.0
    offs = offs[dr > exclude_m]
    enbw = enbw_bins(window(cfg.processing.window_range, n)) * df
    lvl = beat_sideband(cfg, rc).sidelobe_dbc(offs, enbw) + rd_cell_pn_offset_db(cfg)
    return float(np.mean(10.0 ** (lvl / 10.0)))


def rd_cell_pn_offset_db(cfg: RadarConfig) -> float:
    """How much lower than the single-chirp range-bin level the phase-noise
    floor sits per range-Doppler cell: the noise-like sideband spreads over
    the Doppler bins while the tone gains the window's coherent gain."""
    return -coherent_gain_db(window(cfg.processing.window_doppler, cfg.chirp.n_chirps))


def beat_sideband(cfg: RadarConfig, rc: RangeCorrelation):
    """The exact (Gaussian) sideband spectrum of the beat tone on a grid
    spanning +-4 x the IF band, the residual out to the envelope grid's
    Nyquist taken from the carrier."""
    return rc.beat_sideband(4.0 * cfg.rx.if_bw_hz, 1 << 16, 0.5 * cfg.sim.time_osr * cfg.band.sweep_hz)


def pn_floor_table(cfg: RadarConfig, offsets_m=REPORT_OFFSETS_M, rc: RangeCorrelation | None = None,
                   window_name: str | None = None, exact: bool = True) -> dict:
    """Phase-noise sidelobe at each range offset from the target [dBc]:
    ``(per range bin of one chirp, per range-Doppler cell)``.  ``exact``
    uses the Gaussian-phase spectrum (every order); ``False`` the
    first-order ``S_res / 2``."""
    rc = RangeCorrelation.from_config(cfg) if rc is None else rc
    name = cfg.processing.window_range if window_name is None else window_name
    enbw = enbw_bins(window(name, cfg.n_samples)) / cfg.chirp.duration_s
    cell = rd_cell_pn_offset_db(cfg)
    sb = beat_sideband(cfg, rc) if exact else None
    out = {}
    for dr in offsets_m:
        df = cfg.slope_hz_per_s * cfg.tau_s(dr)
        lvl = float(sb.sidelobe_dbc(df, enbw)) if sb is not None else float(rc.sidelobe_dbc(df, enbw))
        out[float(dr)] = (lvl, lvl + cell)
    return out


def nonlinearity_profile(cfg: RadarConfig, chirp: ChirpResult, k: int | None = None, pad: int | None = None) -> dict:
    """The range profile a point target gets from the chirp's frequency
    error alone: the beat phase perturbation ``psi(t) - psi(t - tau)`` of
    ramp ``k`` on the ADC grid, on the ideal beat tone, through the config's
    range window and FFT.  Returns the profile [dB rel. peak] on a range
    axis relative to the target, its -3 dB and Rayleigh widths in metres,
    the highest sidelobe and the integrated sidelobe ratio (power outside
    the mainlobe over the mainlobe's)."""
    k = chirp.n_chirps - 1 if k is None else k
    pad = cfg.processing.range_pad if pad is None else pad
    n = cfg.n_samples
    fs = cfg.rx.adc_fs_hz
    t_ref = np.arange(chirp.f_err_dco_hz.size) / chirp.fref_hz
    psi = chirp.phase_err_carrier_rad()
    t0 = k * chirp.pri_cycles / chirp.fref_hz
    tau = cfg.tau_s()
    # the beat on the reference grid (the flyback transient's sidebands reach
    # tens of MHz), then the IF brick wall and the ADC rate exactly as the
    # time engine applies them; on the ADC grid directly when the reference
    # is not a multiple of the ADC clock
    up = chirp.fref_hz / fs
    if abs(up - round(up)) < 1e-9 and round(up) > 1:
        n_fine = n * int(round(up))
        t = np.arange(n_fine) / chirp.fref_hz
        dpsi = np.interp(t0 + t, t_ref, psi) - np.interp(t0 + t - tau, t_ref, psi)
        fine = np.exp(1j * (TWOPI * cfg.beat_hz() * t + dpsi))
        f_fine = np.fft.fftfreq(n_fine, d=1.0 / chirp.fref_hz)
        spec = np.where(np.abs(f_fine) <= cfg.rx.if_bw_hz, np.fft.fft(fine), 0.0)
        f_adc = np.fft.fftfreq(n, d=1.0 / fs)
        idx = np.rint(f_adc * cfg.chirp.duration_s).astype(int) % n_fine
        beat = np.fft.ifft(spec[idx]) * (n / n_fine)
        dpsi = dpsi[:: int(round(up))]
    else:
        t = np.arange(n) / fs
        dpsi = np.interp(t0 + t, t_ref, psi) - np.interp(t0 + t - tau, t_ref, psi)
        beat = np.exp(1j * (TWOPI * cfg.beat_hz() * t + dpsi))
    prof = power_db(range_fft(beat, cfg.processing.window_range, pad))
    m = n * pad
    # centre the profile on the target so the lobe is contiguous; the axis is
    # the range offset from the peak bin
    i = int(np.argmax(prof))
    prof_rel = np.roll(prof, m // 2 - i) - prof[i]
    axis_rel = (np.arange(m) - m // 2) * (cfg.range_resolution_m / pad)
    rp = read_peak(axis_rel, prof_rel)
    # ISLR: mainlobe between the first nulls
    i0 = int(np.argmax(prof_rel))
    lo = i0
    while lo > 0 and prof_rel[lo - 1] <= prof_rel[lo]:
        lo -= 1
    hi = i0
    while hi < prof_rel.size - 1 and prof_rel[hi + 1] <= prof_rel[hi]:
        hi += 1
    p = 10.0 ** (prof_rel / 10.0)
    main = float(np.sum(p[lo:hi + 1]))
    side = float(np.sum(p) - main)
    return {"axis_m": axis_rel, "profile_db": prof_rel, "width_3db_m": rp["width_3db"],
            "width_rayleigh_m": rp["width_rayleigh"], "peak_sidelobe_db": rp["peak_sidelobe_db"],
            "islr_db": 10.0 * math.log10(max(side, 1e-300) / main), "ramp": k,
            "phase_rms_rad": float(np.std(dpsi)), "phase_peak_rad": float(np.max(np.abs(dpsi - dpsi.mean())))}


def ideal_profile(cfg: RadarConfig, name: str | None = None) -> dict:
    """The same profile with no frequency error: the window's own lobe on the
    config's grid (what every nonlinearity profile is compared with)."""
    name = cfg.processing.window_range if name is None else name
    n, pad = cfg.n_samples, cfg.processing.range_pad
    bins, s = spectrum_db(window(name, n), pad)
    axis = bins * cfg.range_resolution_m
    rp = read_peak(axis, s)
    return {"axis_m": axis, "profile_db": s, "width_3db_m": rp["width_3db"], "width_rayleigh_m": rp["width_rayleigh"],
            "peak_sidelobe_db": rp["peak_sidelobe_db"]}


def run_statistical(cfg: RadarConfig, chirp: ChirpResult | None = None) -> StatResult:
    budget = link_budget(cfg)
    n = cfg.n_samples
    fs = cfg.rx.adc_fs_hz
    beat = cfg.beat_hz()
    fd = cfg.doppler_hz()
    prof = LOProfile.from_config(cfg)
    rc = RangeCorrelation(prof, cfg.tau_s())
    f1, f2 = 1.0 / cfg.chirp.duration_s, cfg.rx.if_bw_hz
    res = StatResult(
        budget=budget, beat_hz=beat, doppler_hz=fd, range_bin=beat / (fs / n), doppler_bin=fd * cfg.chirp.pri_s * cfg.chirp.n_chirps,
        snr_cell_db=budget.snr_cell_db, snr_chirp_db=budget.snr_chirp_db,
        pd=float(pd_swerling0(budget.snr_cell_db, cfg.processing.cfar_pfa)),
        range_res_rect_m=cfg.range_resolution_m,
        range_res_m=mainlobe_width_bins(cfg.processing.window_range, n, -3.0, cfg.processing.range_pad) * cfg.range_resolution_m,
        range_res_rayleigh_m=mainlobe_width_bins(cfg.processing.window_range, n, 20.0 * math.log10(2.0 / math.pi),
                                                 cfg.processing.range_pad) * cfg.range_resolution_m,
        velocity_res_mps=cfg.velocity_resolution_mps,
        window_sidelobe_db=peak_sidelobe_db(cfg.processing.window_range, n, cfg.processing.range_pad),
        pn_floor=pn_floor_table(cfg, rc=rc), pn_rms_rad=rc.rms_residual_rad(f1, f2), lo_rms_rad=prof.rms_phase_rad(f1, f2))
    sc_r, sc_d = scalloping_loss_db(cfg)
    res.extras["scalloping_range_db"] = sc_r
    res.extras["scalloping_doppler_db"] = sc_d
    res.extras["snr_cell_on_grid_db"] = budget.snr_cell_db - sc_r - sc_d
    # what a map-wide noise estimate sees: the thermal floor plus the LO's
    # residual noise averaged over the band (outside the target's own lobe)
    pn_cell = pn_floor_mean_cell(cfg, rc, 25.0 * cfg.range_resolution_m)
    thermal_cell = 10.0 ** (-res.extras["snr_cell_on_grid_db"] / 10.0)
    res.extras["pn_cell_mean_dbc"] = 10.0 * math.log10(max(pn_cell, 1e-300))
    # the beat tone's coherent part is exp(-sigma^2 / 2) of its amplitude: the
    # residual LO noise over the whole receive band (to the envelope grid's
    # Nyquist, the time engine's reach) takes that much out of the peak
    sb = beat_sideband(cfg, rc)
    res.extras["pn_carrier_loss_db"] = sb.carrier_loss_db
    res.extras["pn_residual_total_rad"] = math.sqrt(sb.sigma2)
    res.extras["snr_cell_expected_db"] = (-10.0 * math.log10(thermal_cell + pn_cell)
                                          + res.extras["pn_carrier_loss_db"])
    res.extras["max_range_m"] = cfg.max_range_m
    res.extras["max_velocity_mps"] = cfg.max_velocity_mps
    res.extras["in_if_band"] = bool(beat <= cfg.rx.if_bw_hz)
    res.extras["lo_source"] = prof.source
    res.extras["range_axis_m"] = range_axis_m(cfg, n)[: n // 2]
    res.extras["velocity_axis_mps"] = velocity_axis_mps(cfg, cfg.chirp.n_chirps)
    if chirp is None and cfg.lo.engine != "ideal":
        chirp = ChirpEngine(cfg).run(noise=False, n_chirps=min(3, cfg.chirp.n_chirps))
    if chirp is not None and chirp.engine != "ideal":
        k = chirp.n_chirps - 1
        res.chirp = {**chirp.metrics(k), "engine": chirp.engine, "dp_gain_used": chirp.dp_gain_used,
                     "ui_per_ref_cycle_p99": chirp.ui_per_ref_cycle_p99, "vouches_for_spurs": chirp.vouches_for_spurs,
                     "dp_cal_passes": [p["eps_hat"] for p in chirp.dp_cal_passes]}
        nl = nonlinearity_profile(cfg, chirp, k)
        res.nonlinearity = {key: nl[key] for key in ("width_3db_m", "width_rayleigh_m", "peak_sidelobe_db", "islr_db",
                                                      "phase_rms_rad", "phase_peak_rad", "ramp")}
        res.nonlinearity["engine"] = chirp.engine
        res.extras["nonlinearity_profile"] = (nl["axis_m"], nl["profile_db"])
    return res


__all__ = ["StatResult", "run_statistical", "pn_floor_table", "nonlinearity_profile", "ideal_profile",
           "rd_cell_pn_offset_db", "scalloping_loss_db", "pn_floor_mean_cell", "beat_sideband", "REPORT_OFFSETS_M"]

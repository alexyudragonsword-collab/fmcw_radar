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

from ..chirp import ChirpEngine, ChirpResult, noisy_chirp
from ..config.schema import C0, RadarConfig
from ..link.budget import LinkBudget, link_budget
from ..link.leakage import LeakageBudget, leakage_budget
from ..lo import LOProfile, parked_lo
from ..mimo import VirtualArray
from ..phase_noise import RangeCorrelation
from ..processing.cfar import threshold_factor
from ..processing.cfarstats import cfar_pd, cfar_snr_for_pd, cfar_statistics, correlation_length
from ..processing.detection import pd_swerling0, snr_for_pd
from ..processing.rd import power_db, range_axis_m, range_fft, read_peak, velocity_axis_mps
from ..processing.windows import (coherent_gain_db, enbw_bins, mainlobe_width_bins, peak_sidelobe_db, range_window, spectrum_db,
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
    targets: list = field(default_factory=list)       # milestone 2: one row per point target (the primary first)
    angle: dict = field(default_factory=dict)         # milestone 2: the virtual array's angle metrics
    leakage: LeakageBudget | None = None              # milestone 2: TX-RX leakage budget (None when off)
    cfar: dict = field(default_factory=dict)          # what the windows and padding make of the CA-CFAR's Pfa
    extras: dict = field(default_factory=dict)


def scalloping_loss_db(cfg: RadarConfig) -> tuple[float, float]:
    """``(range, Doppler)`` loss [dB] of reading the target at the nearest
    cell of the (padded) grids instead of at its exact frequency: the
    window's spectrum at the fractional-bin offset.  A Hann window loses
    1.4 dB half a bin out; the padding factors put the grid closer."""
    n, m = cfg.n_samples, cfg.chirp.n_chirps
    p = cfg.processing
    dims = ((p.window_range, cfg.beat_hz() * cfg.chirp.duration_s, p.range_pad, n, cfg.n_blank),
            (p.window_doppler, cfg.doppler_hz() * cfg.chirp.pri_s * m, p.doppler_pad, m, 0))
    out = []
    for name, bin_, pad, length, n_blank in dims:
        frac = bin_ * pad - round(bin_ * pad)          # offset from the nearest padded cell, in padded bins
        w = range_window(name, length, n_blank)
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
    enbw = enbw_bins(range_window(cfg.processing.window_range, n, cfg.n_blank)) * df
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
    enbw = enbw_bins(range_window(name, cfg.n_samples, cfg.n_blank)) / cfg.chirp.duration_s
    cell = rd_cell_pn_offset_db(cfg)
    sb = beat_sideband(cfg, rc) if exact else None
    out = {}
    for dr in offsets_m:
        df = cfg.slope_hz_per_s * cfg.tau_s(dr)
        lvl = float(sb.sidelobe_dbc(df, enbw)) if sb is not None else float(rc.sidelobe_dbc(df, enbw))
        out[float(dr)] = (lvl, lvl + cell)
    return out


def _ramp_beat(cfg: RadarConfig, chirp: ChirpResult, k: int, psi: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """``(beat on the ADC grid, psi(t) - psi(t - tau) there)`` of ramp ``k``:
    the chirp's carrier phase error on the ideal beat tone, on the reference
    grid (the flyback transient's sidebands reach tens of MHz), then the IF
    brick wall and the ADC rate exactly as the time engine applies them; on
    the ADC grid directly when the reference is not a multiple of the ADC
    clock."""
    n = cfg.n_samples
    fs = cfg.rx.adc_fs_hz
    t_ref = np.arange(chirp.f_err_dco_hz.size) / chirp.fref_hz
    psi = chirp.phase_err_carrier_rad() if psi is None else psi
    t0 = k * chirp.pri_cycles / chirp.fref_hz
    tau = cfg.tau_s()
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
    return beat, dpsi


def coherent_spurs(cfg: RadarConfig, chirp: ChirpResult, first: int = 1, n_max: int = 6, floor_db: float = -70.0) -> dict:
    """The chirp's deterministic spurs as a frame sees them: what of the
    LO's error is the same on every ramp.  The ramps' range spectra are
    averaged coherently (the zero-Doppler row of a frame at rest) and
    incoherently; a spur is a local maximum of the coherent mean, beyond the
    window's own sidelobes and above ``floor_db``, that the ramps' *noise*
    would not leave in a mean of M.  That noise is ``(incoherent -
    coherent) / (M - 1)`` per bin, estimated from M - 1 looks, so the test
    is a CA-CFAR's: the factor ``K (p^(-1/K) - 1)`` with K = M - 1 and p set
    for one false spur in a hundred searches over the profile's independent
    bins (15 dB at 8 ramps, 11 dB at 64).  With the loop's noise on, the
    TDC's jitter dithers its quantisation and little is left; with it off
    the same search returns the undithered pattern.

    Returns ``ghosts`` [(range offset [m], level [dBc])], the number of
    ramps, and ``limit_dbc``: the median level under which a spur cannot be
    told from the LO's noise in that many ramps."""
    pad = cfg.processing.range_pad
    ramps = list(range(min(first, chirp.n_chirps - 1), chirp.n_chirps))
    psi = chirp.phase_err_carrier_rad()
    spec = np.stack([range_fft(_ramp_beat(cfg, chirp, k, psi)[0], cfg.processing.window_range, pad, cfg.n_blank) for k in ramps])
    m = len(ramps)
    coh = np.abs(spec.mean(axis=0)) ** 2
    inc = np.mean(np.abs(spec) ** 2, axis=0)
    i = int(np.argmax(coh))
    n_bins = coh.size
    axis = (np.arange(n_bins) - n_bins // 2) * (cfg.range_resolution_m / pad)
    coh_db = np.roll(10.0 * np.log10(np.maximum(coh / coh[i], 1e-300)), n_bins // 2 - i)
    noise = np.roll(np.maximum(inc - coh, 0.0) / max(m - 1, 1) / coh[i], n_bins // 2 - i)   # in the mean, per bin, rel. the peak
    far = np.abs(axis) > 15 * cfg.range_resolution_m
    if m > 1:
        looks = max(float(np.count_nonzero(far)) / correlation_length(range_window(cfg.processing.window_range, cfg.n_samples,
                                                                                    cfg.n_blank), pad), 1.0)
        factor = threshold_factor(m - 1, 1e-2 / looks)
    else:
        factor = 0.0                                                       # one ramp: nothing to tell a spur from
    limit_db = 10.0 * np.log10(np.maximum(factor * noise, 1e-300))
    # the window's own skirt is coherent too: a spur has to stand 6 dB clear of the error-free response
    t = np.arange(cfg.n_samples) / cfg.rx.adc_fs_hz
    clean = np.abs(range_fft(np.exp(1j * TWOPI * cfg.beat_hz() * t), cfg.processing.window_range, pad, cfg.n_blank)) ** 2
    clean_db = np.roll(10.0 * np.log10(np.maximum(clean / clean.max(), 1e-300)), n_bins // 2 - int(np.argmax(clean)))
    in_band = np.abs(axis + cfg.target.range_m) < cfg.max_range_m          # either beat sign inside the IF band
    idx = [j for j in range(1, n_bins - 1)
           if far[j] and coh_db[j] > floor_db and coh_db[j] > limit_db[j] and coh_db[j] > clean_db[j] + 6.0
           and coh_db[j] > coh_db[j - 1] and coh_db[j] >= coh_db[j + 1]]
    idx.sort(key=lambda j: -coh_db[j])
    sel = far & in_band
    return {"ghosts": [(float(axis[j]), float(coh_db[j])) for j in idx[:n_max]], "chirps": m,
            "limit_dbc": float(np.median(limit_db[sel])) if (m > 1 and np.any(sel)) else float("-inf"),
            "noise": bool(chirp.noise)}


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
    beat, dpsi = _ramp_beat(cfg, chirp, k)
    prof = power_db(range_fft(beat, cfg.processing.window_range, pad, cfg.n_blank))
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
            "phase_rms_rad": float(np.std(dpsi)), "phase_peak_rad": float(np.max(np.abs(dpsi - dpsi.mean()))),
            "ghosts": ghost_targets(axis_rel, prof_rel, 15 * cfg.range_resolution_m)}


def ghost_targets(axis_m: np.ndarray, profile_db: np.ndarray, exclude_m: float, floor_db: float = -70.0,
                  n_max: int = 6) -> list[tuple[float, float]]:
    """Deterministic spurs of the chirp's frequency error as the range FFT
    shows them: the local maxima of the profile farther than ``exclude_m``
    from the target (the window's own sidelobes live inside) and above
    ``floor_db``, as ``(range offset [m], level [dBc])``, strongest first.
    A TDC quantisation ghost (cairn/chirp-engine.md) sits here at a fixed
    offset; the time engine finds the same one on its map.  Only a
    cycle-accurate curve can vouch for these (invariant #6)."""
    far = np.abs(axis_m) > exclude_m
    idx = [i for i in range(1, profile_db.size - 1)
           if far[i] and profile_db[i] > floor_db and profile_db[i] > profile_db[i - 1] and profile_db[i] >= profile_db[i + 1]]
    idx.sort(key=lambda i: -profile_db[i])
    return [(float(axis_m[i]), float(profile_db[i])) for i in idx[:n_max]]


def ideal_profile(cfg: RadarConfig, name: str | None = None) -> dict:
    """The same profile with no frequency error: the window's own lobe on the
    config's grid (what every nonlinearity profile is compared with)."""
    name = cfg.processing.window_range if name is None else name
    n, pad = cfg.n_samples, cfg.processing.range_pad
    bins, s = spectrum_db(range_window(name, n, cfg.n_blank), pad)
    axis = bins * cfg.range_resolution_m
    rp = read_peak(axis, s)
    return {"axis_m": axis, "profile_db": s, "width_3db_m": rp["width_3db"], "width_rayleigh_m": rp["width_rayleigh"],
            "peak_sidelobe_db": rp["peak_sidelobe_db"]}


def target_rows(cfg: RadarConfig, rc: RangeCorrelation, n_tx: int = 1) -> list[dict]:
    """One row per point target: its own budget, cell position, and the
    masking by the others -- the strongest interferer's response at this
    target's cell (the range window's sidelobe at the range offset times
    the Doppler window's at the Doppler offset, the LO's residual noise at
    the range offset through range correlation at the interferer's tau,
    whichever is higher) relative to this target's own level.  A target
    whose margin is negative sits under another's skirt."""
    import dataclasses

    from ..processing.windows import spectrum_db

    n, m = cfg.n_samples, cfg.chirp.n_chirps // n_tx
    df = cfg.rx.adc_fs_hz / n
    dfd = 1.0 / (cfg.chirp.pri_s * n_tx * m)
    bins_r, w_r = spectrum_db(range_window(cfg.processing.window_range, n, cfg.n_blank), 16)
    bins_d, w_d = spectrum_db(window(cfg.processing.window_doppler, m), 16)
    enbw = enbw_bins(range_window(cfg.processing.window_range, n, cfg.n_blank)) * df
    cell_off = -coherent_gain_db(window(cfg.processing.window_doppler, m))
    rows = []
    for t in cfg.targets:
        c = dataclasses.replace(cfg, target=t, extra_targets=())
        b = link_budget(c)
        rows.append({"kind": t.kind, "range_m": t.range_m, "velocity_mps": t.velocity_mps, "angle_deg": t.angle_deg,
                     "rcs_dbsm": b.rcs_dbsm, "rcs_source": b.inputs["rcs_dbsm"][1], "beat_hz": c.beat_hz(),
                     "doppler_hz": c.doppler_hz(), "ps_adc_dbm": b.ps_adc_dbm,
                     "snr_cell_db": b.snr_cell_db - 10.0 * math.log10(n_tx), "pd": float(pd_swerling0(b.snr_cell_db - 10.0 * math.log10(n_tx), cfg.processing.cfar_pfa)),
                     "in_if_band": bool(c.beat_hz() <= cfg.rx.if_bw_hz)})
    for i, r in enumerate(rows):
        worst = None
        for j, o in enumerate(rows):
            if j == i:
                continue
            d_r = abs(r["beat_hz"] - o["beat_hz"]) / df
            d_d = abs(r["doppler_hz"] - o["doppler_hz"]) / dfd
            d_d = min(d_d, m - d_d) if m > 1 else 0.0
            # the window's skirt at that offset: the lobe's envelope within half a bin (a DFT-even window's
            # spectrum is exactly zero at whole-bin offsets, where a plain lookup would read nothing)
            side = _envelope(bins_r, w_r, d_r) + (_envelope(bins_d, w_d, d_d) if m > 1 else 0.0)
            rc_o = RangeCorrelation(rc.profile, cfg.tau_s(o["range_m"]))
            pn = float(rc_o.sidelobe_dbc(max(abs(r["beat_hz"] - o["beat_hz"]), df), enbw)) + cell_off if d_r >= 1.0 else 0.0
            lvl = o["ps_adc_dbm"] + max(side, pn) - r["ps_adc_dbm"]
            if worst is None or lvl > worst[1]:
                worst = (j, lvl, "window" if side >= pn else "phase noise")
        r["interferer"] = None if worst is None else worst[0]
        r["interference_dbc"] = None if worst is None else worst[1]          # the interferer's skirt at this cell rel. this target
        r["interference_kind"] = None if worst is None else worst[2]
        r["margin_db"] = None if worst is None else -worst[1]
        r["masked"] = bool(worst is not None and worst[1] > 0.0)
    return rows


def _envelope(bins: np.ndarray, spec_db: np.ndarray, offset: float) -> float:
    sel = np.abs(bins - offset) <= 0.5
    return float(spec_db[sel].max()) if np.any(sel) else -300.0


def angle_metrics(cfg: RadarConfig, snr_cell_db: float, snr_chirp_db: float | None = None,
                  range_scalloping_db: float = 0.0) -> dict:
    """The virtual array's angle resolution, accuracy bound and biases for
    the primary target (empty for one TX, one RX).  With ``snr_chirp_db``
    (one chirp's range bin on one receiver) the estimator's own expected
    scatter and what separates it from the bound are added
    (``VirtualArray.angle_error_budget``)."""
    m = cfg.mimo
    if m.n_virtual < 2:
        return {}
    va = VirtualArray(cfg)
    th = cfg.target.angle_deg
    fd = cfg.doppler_hz()
    snr_el = snr_cell_db - 10.0 * math.log10(m.n_tx)               # one TX block's Doppler FFT per virtual element
    est = va.estimate(va.snapshot(th, fd, coupled=True), fd)
    sq = va.sweep_squint(th)
    return {"n_virtual": va.n, "filled": va.filled, "aperture_m": va.aperture_m, "beamwidth_deg": va.beamwidth_deg(th),
            "crlb_sigma_deg": va.crlb_sigma_deg(snr_el, th), "snr_element_db": snr_el,
            "theta_est_deg": est["theta_deg"], "peak_sidelobe_db": est["peak_sidelobe_db"],
            "coupling_bias_deg": va.coupling_bias_deg(th), "tdm_bias_uncompensated_deg": va.tdm_bias_deg(th, fd),
            "coupling_source": m.coupling.source, "coupling_calibrated": m.coupling.calibrated,
            "coupling_max_offdiag_db": (va.coupling.max_offdiag_db() if va.coupling is not None else None),
            "max_velocity_mps": cfg.max_velocity_mps, **sq,
            **(va.angle_error_budget(snr_chirp_db, th, fd, range_scalloping_db) if snr_chirp_db is not None else {})}


def cfar_detection(cfg: RadarConfig, res: "StatResult") -> dict:
    """What the map's CA-CFAR does with what is really on it: the primary
    target's detection probability at its processed per-look SNR (the
    threshold's fluctuation and the target's own leak into its training
    cells included), the SNR a Pd of 0.9 takes and the loss against a known
    noise level, and the deterministic spurs of the chirp -- every listed
    ghost target as a steady target at ``SNR + level``, its Pd, and their
    sum over the ghosts in view: the detections per frame that are neither
    targets nor noise."""
    cf = res.cfar
    k = cf["n_looks"]
    snr_look = res.angle["snr_element_cell_db"] if k > 1 and res.angle else res.extras["snr_cell_expected_db"]
    out = {"snr_look_db": snr_look, "pd_target": float(cfar_pd(snr_look, cf)[0]), "snr_pd90_db": cfar_snr_for_pd(0.9, cf)}
    if k == 1:
        out["cfar_loss_db"] = out["snr_pd90_db"] - snr_for_pd(0.9, cfg.processing.cfar_pfa)
    rows = []
    for off, lvl in res.nonlinearity.get("ghosts") or []:
        r = cfg.target.range_m + off
        rows.append({"offset_m": off, "range_m": r, "level_dbc": lvl, "snr_db": snr_look + lvl,
                     "pd": float(cfar_pd(snr_look + lvl, cf)[0]), "in_view": bool(0.0 < r < cfg.max_range_m)})
    out["ghosts"] = rows
    out["ghost_detections_per_frame"] = float(sum(g["pd"] for g in rows if g["in_view"]))
    out["ghosts_vouched"] = bool(res.nonlinearity.get("ghosts_vouched", False))
    return out


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
        range_res_m=mainlobe_width_bins(cfg.processing.window_range, n, -3.0, cfg.processing.range_pad, cfg.n_blank) * cfg.range_resolution_m,
        range_res_rayleigh_m=mainlobe_width_bins(cfg.processing.window_range, n, 20.0 * math.log10(2.0 / math.pi),
                                                 cfg.processing.range_pad, cfg.n_blank) * cfg.range_resolution_m,
        velocity_res_mps=cfg.velocity_resolution_mps,
        window_sidelobe_db=peak_sidelobe_db(cfg.processing.window_range, n, cfg.processing.range_pad, cfg.n_blank),
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
    res.targets = target_rows(cfg, rc, cfg.mimo.n_tx)
    res.angle = angle_metrics(cfg, budget.snr_cell_db, budget.snr_chirp_db, sc_r)
    res.leakage = leakage_budget(cfg, budget)
    res.cfar = cfar_statistics(cfg)
    if cfg.mimo.n_tx > 1:
        res.extras["snr_cell_per_tx_db"] = budget.snr_cell_db - 10.0 * math.log10(cfg.mimo.n_tx)
    res.extras["max_range_m"] = cfg.max_range_m
    res.extras["max_velocity_mps"] = cfg.max_velocity_mps
    res.extras["in_if_band"] = bool(beat <= cfg.rx.if_bw_hz)
    res.extras["lo_source"] = prof.source
    res.extras["lo_notes"] = list(prof.notes)
    res.extras["lo_parked"] = parked_lo(cfg)
    res.extras["range_axis_m"] = range_axis_m(cfg, n)[: n // 2]
    res.extras["velocity_axis_mps"] = velocity_axis_mps(cfg, cfg.chirp.n_chirps)
    if chirp is None and cfg.lo.engine != "ideal":
        chirp = ChirpEngine(cfg).run(noise=False, n_chirps=min(3, cfg.chirp.n_chirps))
    if chirp is not None and chirp.engine != "ideal":
        k = chirp.n_chirps - 1
        res.chirp = {**chirp.metrics(k), "engine": chirp.engine, "dp_gain_used": chirp.dp_gain_used,
                     "ui_per_ref_cycle_p99": chirp.ui_per_ref_cycle_p99, "dco_dev_frac_p99": chirp.dco_dev_frac_p99,
                     "vouches_for_spurs": chirp.vouches_for_spurs,
                     "dp_cal_passes": [p["eps_hat"] for p in chirp.dp_cal_passes]}
        nl = nonlinearity_profile(cfg, chirp, k)
        res.nonlinearity = {key: nl[key] for key in ("width_3db_m", "width_rayleigh_m", "peak_sidelobe_db", "islr_db",
                                                      "phase_rms_rad", "phase_peak_rad", "ramp", "ghosts")}
        res.nonlinearity["engine"] = chirp.engine
        res.nonlinearity["ghosts_vouched"] = chirp.vouches_for_spurs
        # the single quiet ramp's list is the undithered pattern; what a frame sees is what stays coherent
        # over its ramps with the loop's noise on (the TDC's jitter dithers the quantisation)
        res.nonlinearity["ghosts_quiet"] = res.nonlinearity["ghosts"]
        if chirp.engine == "event":
            live = chirp if chirp.noise else noisy_chirp(cfg, n_chirps=min(max(cfg.time_chirps(), 5), 64))
            cs = coherent_spurs(cfg, live)
            res.nonlinearity.update({"ghosts": cs["ghosts"], "ghost_chirps": cs["chirps"], "ghost_limit_dbc": cs["limit_dbc"],
                                     "tdc_jitter_s": cfg.lo_value("tdc_jitter_s")[0], "tdc_res_s": cfg.lo_value("tdc_res_s")[0]})
        res.extras["nonlinearity_profile"] = (nl["axis_m"], nl["profile_db"])
    res.cfar.update(cfar_detection(cfg, res))
    return res


__all__ = ["StatResult", "run_statistical", "pn_floor_table", "nonlinearity_profile", "ideal_profile", "ghost_targets",
           "target_rows", "angle_metrics",
           "rd_cell_pn_offset_db", "scalloping_loss_db", "pn_floor_mean_cell", "beat_sideband", "REPORT_OFFSETS_M"]

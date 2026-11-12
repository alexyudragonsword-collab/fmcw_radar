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

from ..chirp import ChirpEngine, ChirpResult, noisy_chirp
from ..config.schema import RadarConfig
from ..link.budget import adc_amplitudes, link_budget
from ..link.leakage import leakage_tones
from ..lo import LOProfile
from ..mimo import VirtualArray
from ..phase_noise import RangeCorrelation
from ..processing.cfar import ca_cfar_2d
from ..processing.iffilter import apply_hpf, hpf_initial_state, hpf_sos
from ..processing.rd import (noise_floor, power_db, range_axis_m, range_doppler_map, range_fft, read_peak,
                             velocity_axis_mps)
from ..processing.windows import enbw_bins, range_window

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
               rc: RangeCorrelation | None = None, leakage: bool = True, hpf: bool = True) -> tuple[np.ndarray, dict]:
    """The ADC frame and a dict of what was used: ``(n_chirps, n_samples)``
    for one TX and one RX (milestone 1, bit for bit), ``(n_chirps, n_rx,
    n_samples)`` otherwise -- chirp m is transmitted by TX ``m % n_tx``
    (TDM) and every RX samples it; every target (``cfg.targets``), the
    leakage tones and the IF high-pass are in."""
    seed = cfg.sim.seed if seed is None else seed
    rng = np.random.default_rng(seed)
    m_chirps = cfg.time_chirps() if n_chirps is None else n_chirps
    budget = link_budget(cfg)
    a_s, a_fs, n0_50 = adc_amplitudes(cfg, budget)
    import dataclasses

    mimo = cfg.mimo
    multi = mimo.n_virtual > 1
    va = VirtualArray(cfg) if multi else None
    # every target's amplitude at the ADC, its own delay and velocity; the primary's amplitude is the milestone-1 one
    tgt = []
    for t in cfg.targets:
        c_t = dataclasses.replace(cfg, target=t, extra_targets=())
        amp = adc_amplitudes(c_t, link_budget(c_t))[0] if t is not cfg.target else a_s
        tgt.append((t.range_m, t.velocity_mps, t.angle_deg, amp))
    leaks = leakage_tones(cfg) if (leakage and cfg.leakage.enabled) else []
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
    split = "no phase noise"
    if phase_noise and rc is None:
        # who carries which part of the LO's noise: the error curve first, the profile for the rest
        prof = LOProfile.from_config(cfg)
        content = chirp.lo_noise_in_curve if chirp is not None else "none"
        if content == "unverified":
            raise ValueError("time engine: a linearised chirp curve with its noise on cannot be split against the LO profile; "
                             "run the response engine with noise=False (the profile is its noise) or use the event engine")
        if content == "all":
            prof = prof.above(0.5 * cfg.lo.fref_hz)
            split = "curve: the loop to fref/2 (cycle-accurate, noise on); profile: above fref/2"
        elif content == "quantisation" and prof.components:
            prof = prof.without("tdc_quant", "dco_quant")
            split = "curve: TDC and DCO quantisation (cycle-accurate); profile: everything else"
        elif content == "quantisation":
            split = "curve: TDC and DCO quantisation; profile: no breakdown to take them out of, synthesised whole"
        else:
            split = "profile: everything"
        rc = RangeCorrelation(prof, cfg.tau_s())
    elif phase_noise:
        split = "profile: the caller's"
    # the IF brick wall and the decimation: the two grids share the bin spacing 1 / T_c
    f_w = np.fft.fftfreq(n_w, d=1.0 / fs_w)
    keep = np.abs(f_w) <= cfg.rx.if_bw_hz
    f_adc = np.fft.fftfreq(n_adc, d=1.0 / cfg.rx.adc_fs_hz)
    idx_adc = np.rint(f_adc * cfg.chirp.duration_s).astype(int) % n_w
    sigma = math.sqrt(n0_50 * fs_w)
    step = 2.0 * a_fs / (2 ** cfg.rx.adc_bits)
    n_rx = mimo.n_rx
    frame = np.empty((m_chirps, n_rx, n_adc), dtype=complex) if multi else np.empty((m_chirps, n_adc), dtype=complex)
    clipped = 0
    clipped_kept = 0
    n_blank = cfg.n_blank
    use_hpf = hpf and cfg.rx.hpf_corner_hz > 0.0
    sos = hpf_sos(cfg.rx.adc_fs_hz, cfg.rx.hpf_corner_hz, cfg.rx.hpf_order) if use_hpf else None
    hpf_state = [hpf_initial_state(sos) for _ in range(n_rx)] if use_hpf else None
    x_tx = va.tx.x_m if multi else np.zeros(1)
    x_rx = va.rx.x_m if multi else np.zeros(1)

    def beat_phase(tau):
        """The ideal beat phase for a delay tau(t): exact for the sweep."""
        return TWOPI * (f_c - 0.5 * b) * tau + TWOPI * s * tau * t - math.pi * s * tau * tau

    for m in range(m_chirps):
        t_abs = m * pri + t
        i_tx = m % mimo.n_tx
        # the LO's error at this chirp: the chirp engine's curve and the phase noise, delayed by the
        # primary target's round trip; the channels' extra delays (tens of ps across the aperture, the
        # leakage's fraction of a ns) are far below the error's own resolution and share this term
        tau0 = 2.0 * (r0 + v * t_abs) / c0
        err = np.zeros(n_w)
        if psi_ref is not None:
            err = err + np.interp(t_abs, t_ref, psi_ref) - np.interp(t_abs - tau0, t_ref, psi_ref)
        if phase_noise:
            pn = rc.synthesize_lo(n_w, fs_w, rng)
            err = err + rc.residual(pn, fs_w)
            for f0, a in rc.profile.spurs:
                ph0 = rng.uniform(0.0, TWOPI)
                err = err + a * (np.sin(TWOPI * f0 * t_abs + ph0) - np.sin(TWOPI * f0 * (t_abs - tau0) + ph0))
        ys = []
        for n in range(n_rx):
            x = np.zeros(n_w, dtype=complex)
            for r_t, v_t, th_t, amp in tgt:
                tau = 2.0 * (r_t + v_t * t_abs) / c0
                if multi:
                    tau = tau + (x_tx[i_tx] + x_rx[n]) * math.sin(math.radians(th_t)) / c0
                g = va.element_gain(th_t) if multi else 1.0
                x = x + (amp * g) * np.exp(1j * (beat_phase(tau) + err))
            for tau_l, amp_l in leaks:
                # the leakage shares the LO: its error phase is the same curve at a tau of ~0, i.e. nothing
                x = x + amp_l * np.exp(1j * beat_phase(np.full(n_w, tau_l)))
            if noise:
                x = x + (sigma / math.sqrt(2.0)) * (rng.standard_normal(n_w) + 1j * rng.standard_normal(n_w))
            ys.append(x)
        if multi and va.coupling is not None:
            # the receive array's mutual coupling at the carrier: received_k = a_k + sum_j S_kj a_j
            c = va.c_rx
            ys = [sum(c[k, j] * ys[j] for j in range(n_rx)) if np.any(c[k] != np.eye(n_rx)[k]) else ys[k] for k in range(n_rx)]
        for n, x in enumerate(ys):
            spec = np.fft.fft(x)
            spec = np.where(keep, spec, 0.0)
            y = np.fft.ifft(spec[idx_adc]) * (n_adc / n_w)
            if use_hpf:
                if m == 0:
                    # warm the filter up on the first chirp (the receiver has been running), then filter it for real
                    _, hpf_state[n] = apply_hpf(y, cfg.rx.adc_fs_hz, cfg.rx.hpf_corner_hz, cfg.rx.hpf_order, hpf_state[n], sos)
                y, hpf_state[n] = apply_hpf(y, cfg.rx.adc_fs_hz, cfg.rx.hpf_corner_hz, cfg.rx.hpf_order, hpf_state[n], sos)
            if quantise:
                over = (np.abs(y.real) > a_fs) | (np.abs(y.imag) > a_fs)
                clipped += int(np.count_nonzero(over))
                clipped_kept += int(np.count_nonzero(over[n_blank:]))
                y = np.clip(np.round(y.real / step) * step, -a_fs, a_fs) + 1j * np.clip(np.round(y.imag / step) * step,
                                                                                      -a_fs, a_fs)
            if n_blank:
                y = y.copy()
                y[:n_blank] = 0.0                                    # blanked: the range window is zero there too
            if multi:
                frame[m, n] = y
            else:
                frame[m] = y
    info = {"fs_wave_hz": fs_w, "n_wave": n_w, "signal_amplitude_v": a_s, "fullscale_v": a_fs,
            "noise_sigma_wave_v": sigma, "adc_step_v": step, "budget": budget, "n_chirps": m_chirps,
            "clipped_fraction": clipped / float(frame.size), "n_targets": len(tgt), "n_leakage_tones": len(leaks),
            "clipped_fraction_after_blanking": clipped_kept / float(frame.size), "n_blank": n_blank, "lo_noise_split": split}
    return frame, info


def process_frame(cfg: RadarConfig, frame: np.ndarray, info: dict | None = None) -> TimeResult:
    """Window + range FFT + Doppler FFT + CFAR on an ADC frame; the target
    read off the map.  A MIMO cube ``(n_chirps, n_rx, n_samples)`` is
    processed per TX block and RX channel; the map is the non-coherent sum
    over the virtual channels, the angle the DBF estimate at the primary
    target's cell (``extras['angle_deg']``), the Doppler for the TDM
    compensation the peak's own."""
    cube = frame.ndim == 3
    if cube:
        return _process_cube(cfg, frame, info)
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
    prof = power_db(range_fft(frame[-1], cfg.processing.window_range, cfg.processing.range_pad, cfg.n_blank))[:half]
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
    res.extras["targets_found"] = found_targets(cfg, p[:, :half], r_axis[:half], v_axis)
    return res


def found_targets(cfg: RadarConfig, power: np.ndarray, r_axis: np.ndarray, v_axis: np.ndarray) -> list:
    """For every configured target, the map's peak within +-3 range bins and
    +-2 Doppler bins of where it should be: ``(range, velocity, level dB rel.
    the primary's peak)``, or None when the target is not seen there.  Two
    targets closer than the window share it: each one's search stops at the
    bins nearer the other's place, and the peak must be a local maximum
    along range (a point on another target's skirt is not this target) and
    rise 6 dB above the map's median (the noise)."""
    import dataclasses

    n_d, n_r = power.shape
    pad = cfg.processing.range_pad
    ref = float(power.max())
    floor = float(np.median(power))
    places = []
    for t in cfg.targets:
        c = dataclasses.replace(cfg, target=t, extra_targets=())
        places.append((int(round(c.beat_hz() * cfg.chirp.duration_s * pad)), int(np.argmin(np.abs(v_axis - t.velocity_mps)))))
    out = []
    for n_t, (j0, i0) in enumerate(places):
        js = []
        for d in range(-3 * pad, 3 * pad + 1):
            j = (j0 + d) % n_r
            others = [abs(j - jo) for k, (jo, io) in enumerate(places) if k != n_t and abs(io - i0) <= 2]
            if not others or abs(d) <= min(others):                     # nearer this target than any other
                js.append(j)
        is_ = [(i0 + d) % n_d for d in range(-2, 3)]
        sub = power[np.ix_(is_, js)]
        local = np.ones_like(sub, dtype=bool)
        for col, j in enumerate(js):
            local[:, col] = (power[is_, j] >= power[is_, (j - 1) % n_r]) & (power[is_, j] >= power[is_, (j + 1) % n_r])
        cand = np.where(local, sub, -1.0)
        k = np.unravel_index(int(np.argmax(cand)), sub.shape)
        pk = float(cand[k])
        if pk < 4.0 * floor:
            out.append(None)
        else:
            out.append((float(r_axis[js[k[1]]]), float(v_axis[is_[k[0]]]), 10.0 * math.log10(pk / ref)))
    return out


def doppler_fine_hz(x: np.ndarray, pri_s: float, coarse_hz: float) -> float:
    """The Doppler of the tone in ``x`` (``(n_tx, m_tx, n_rx)`` range-FFT
    values of one range bin, chirp by chirp) finer than the Doppler FFT's
    bin: the phase advance between consecutive same-TX chirps, averaged over
    the TX and RX channels (the ML estimate of a single tone's frequency at
    high SNR, unbiased where the FFT bin is quantised to 1 / (m_tx PRI)).
    Falls back to ``coarse_hz`` for a single chirp per TX or an empty bin."""
    if x.shape[1] < 2:
        return coarse_hz
    z = np.sum(np.conj(x[:, :-1]) * x[:, 1:])
    if abs(z) == 0.0:
        return coarse_hz
    return float(np.angle(z) / (2.0 * math.pi * pri_s))


def _process_cube(cfg: RadarConfig, cube: np.ndarray, info: dict | None) -> TimeResult:
    from ..processing.rd import doppler_fft, range_fft

    m_chirps, n_rx, n = cube.shape
    n_tx = cfg.mimo.n_tx
    p_ = cfg.processing
    va = VirtualArray(cfg)
    # per TX block: its own chirps (every n_tx-th), range FFT, Doppler FFT over them
    blocks, ranges = [], []
    for i_tx in range(n_tx):
        sub = cube[i_tx::n_tx]                                          # (m / n_tx, n_rx, n)
        rr = range_fft(sub, p_.window_range, p_.range_pad, cfg.n_blank)
        ranges.append(rr)
        blocks.append(doppler_fft(rr, p_.window_doppler, p_.doppler_pad))   # (m_tx x pad, n_rx, n x pad)
    maps = np.stack(blocks)                                             # (n_tx, m_tx, n_rx, n_r)
    rmaps = np.stack(ranges)                                            # (n_tx, m_tx, n_rx, n_r) before the Doppler FFT
    p = np.sum(np.abs(maps) ** 2, axis=(0, 2))                          # non-coherent sum over the virtual channels
    rd_db = 10.0 * np.log10(np.maximum(p, 1e-300))
    n_d, n_r = p.shape
    r_axis = range_axis_m(cfg, n_r)
    pri_tx = cfg.chirp.pri_s * n_tx
    fd = np.fft.fftshift(np.fft.fftfreq(n_d, d=pri_tx))
    v_axis = fd * cfg.band.wavelength_m / 2.0
    half = n_r // 2
    i, j = np.unravel_index(int(np.argmax(p[:, :half])), (n_d, half))
    excl = (min(max(2, n_d // 8), max(n_d // 2 - 1, 0)), max(8, half // 16))
    n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * p_.range_pad)
    floor = noise_floor(p[:, :min(n_if, half)], (i, j), excl)
    snr = 10.0 * math.log10(p[i, j] / floor) if floor > 0.0 else float("inf")
    # the virtual snapshot at the peak cell (TX-major) and the angle; the TDM
    # compensation wants the Doppler finer than the frame's few bins give it
    snap = maps[:, i, :, j].ravel()
    fd_fine = doppler_fine_hz(rmaps[:, :, :, j], pri_tx, float(fd[i]))
    est = va.estimate(snap, fd_fine)
    prof = power_db(range_fft(cube[-1, 0], p_.window_range, p_.range_pad, cfg.n_blank))[:half]
    rp = read_peak(r_axis[:half], prof)
    _, det = ca_cfar_2d(p, p_.cfar_guard, p_.cfar_train, p_.cfar_pfa, n_looks=va.n)   # a sum over the virtual channels
    dets = [(float(v_axis[a]), float(r_axis[b])) for a, b in np.argwhere(det[:, :half])]
    res = TimeResult(frame=cube, rd_db=rd_db, range_axis_m=r_axis, velocity_axis_mps=v_axis,
                     peak_range_m=float(r_axis[j]), peak_velocity_mps=float(v_axis[i]), snr_cell_db=snr,
                     n_chirps=m_chirps, range_profile_db=prof - prof.max(), range_profile_axis_m=r_axis[:half],
                     width_3db_m=rp["width_3db"], width_rayleigh_m=rp["width_rayleigh"],
                     peak_sidelobe_db=rp["peak_sidelobe_db"], cfar_detections=dets,
                     extras={"peak_rc": (int(i), int(j)), "noise_floor": floor, "peak_power": float(p[i, j]),
                             "peak_range_interp_m": rp["peak_pos"], "angle_deg": est["theta_deg"],
                             "angle_peak_sidelobe_db": est["peak_sidelobe_db"], "angle_spectrum": (est["u_grid"], est["spectrum_db"]),
                             "snapshot": snap, "n_virtual": va.n, "doppler_fine_hz": fd_fine})
    if info:
        res.extras.update({k: v for k, v in info.items() if k != "budget"})
    found = found_targets(cfg, p[:, :half], r_axis[:half], v_axis)
    # the angle of every target found: the DBF estimate at its own cell
    out = []
    for f_ in found:
        if f_ is None:
            out.append(None)
            continue
        jj = int(np.argmin(np.abs(r_axis[:half] - f_[0])))
        ii = int(np.argmin(np.abs(v_axis - f_[1])))
        e = va.estimate(maps[:, ii, :, jj].ravel(), doppler_fine_hz(rmaps[:, :, :, jj], pri_tx, float(fd[ii])))
        out.append(f_ + (e["theta_deg"],))
    res.extras["targets_found"] = out
    return res


def run_time(cfg: RadarConfig, chirp: ChirpResult | None = None, chirp_noise: bool | None = None, **kw) -> TimeResult:
    """``chirp_noise``: run the chirp engine with the loop's noise sources
    on (seeded like the frame), so the cycle-accurate engine carries the
    LO's noise up to fref / 2 -- its TDC's jitter dithering the
    quantisation -- and the profile only what is above it.  That is the
    default when the LO is the vendored loop itself (event engine, no
    profile file).  Off, the curve is the deterministic one and the profile
    carries the noise, less the quantisation the curve already is: the
    undithered pattern, and the only choice when ``lo.profile`` is another
    LO's file or the engine is the linearised one."""
    if chirp is None and cfg.lo.engine != "ideal":
        if chirp_noise is None:
            # with the frame's phase noise switched off the curve is the deterministic one too
            chirp_noise = cfg.lo.engine == "event" and cfg.lo.profile is None and kw.get("phase_noise", True)
        chirp = (noisy_chirp(cfg, kw.get("seed"), cfg.time_chirps()) if chirp_noise
                 else ChirpEngine(cfg).run(noise=False, n_chirps=cfg.time_chirps()))
    frame, info = beat_frame(cfg, chirp, **kw)
    return process_frame(cfg, frame, info)


def measured_pn_sidelobes(cfg: RadarConfig, offsets_m, n_chirps: int = 32, seed: int | None = None,
                          half_bins: int = 3, window_name: str | None = None, chirp: ChirpResult | None = None) -> dict:
    """The phase-noise sidelobe at each range offset as the range FFT measures
    it: ``n_chirps`` noiseless, unquantised chirps with phase noise only,
    their range profiles averaged, read in a band of ``2 half_bins + 1``
    (unpadded) bins around each offset, relative to the tone's peak [dBc].
    The window's own sidelobes add to what is read: a Hann window sits at
    -32 dB three bins out and falls 18 dB per octave, so offsets under ten
    bins want ``window_name = "blackman"`` (-58 dB) to see the noise.

    With ``chirp`` the frame carries that error curve as well and the LO's
    noise is split between it and the profile the way ``beat_frame`` does:
    what is read is then everything the LO puts at the offset, the curve's
    deterministic pattern included, against the same closed form -- the
    check that nothing is counted twice."""
    from .statistical import beat_sideband

    name = cfg.processing.window_range if window_name is None else window_name
    rc = RangeCorrelation(LOProfile.from_config(cfg), cfg.tau_s())
    sb = beat_sideband(cfg, rc)
    frame, _ = beat_frame(cfg, chirp, noise=False, phase_noise=True, quantise=False, seed=seed, n_chirps=n_chirps,
                          rc=rc if chirp is None else None)
    spec = range_fft(frame, name, 1, cfg.n_blank)
    p = np.mean(np.abs(spec) ** 2, axis=0)
    n = cfg.n_samples
    df = cfg.rx.adc_fs_hz / n
    enbw = enbw_bins(range_window(name, n, cfg.n_blank)) * df
    peak = int(np.argmax(p))
    # the tone's power read on a 16x padded grid: its peak bin on the plain
    # grid sits up to half a bin off and loses up to 1 dB of scalloping the
    # noise bins do not (a 5 m target's beat lands 0.43 bins off: +0.75 dB)
    tone = float(np.max(np.mean(np.abs(range_fft(frame, name, 16, cfg.n_blank)) ** 2, axis=0)))
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

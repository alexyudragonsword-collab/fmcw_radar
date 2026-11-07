# Vendored from array_tx@e897c159e5fc5b2e26af6336cf9f6164461ff7f5: src/arraytx/beam.py
# Adapted-copy policy: see src/fmcw_radar/vendor/__init__.py
"""Beam steering and far-field synthesis (invariant 4: the squint is
computed, not corrected for).

Far field
---------
E(theta, f) = g(theta) / n * sum_k R_k(f) * exp(+j 2 pi (f0 + f) tau_k(theta))

with tau_k(theta) = x_k sin(theta) / c0 (see ``geometry.ArrayGeometry``) and f
the BASEBAND frequency of the FFT bin.  Every baseband frequency gets its own
phase, so a phase-shifter-steered array points each subcarrier somewhere
slightly different, which is the squint; a true-time-delay array does not.
The 1/n keeps the beam-direction gain at 1 so EVM / ACLR do not depend on n
(``normalize=False`` returns the coherent sum, 20 log10(n) dB up).

Steering
--------
``phase``: w_k = exp(-j 2 pi f0 tau_k(theta0)) — a complex weight, flat over
frequency (aligned at the carrier only).
``ttd``:   W_k(f) = exp(-j 2 pi (f0 + f) tau_k(theta0)) — a delay of
tau_k(theta0) plus the carrier phase, applied in the frequency domain.
Both go through ``steer``; with theta0 = 0 both are the identity and the
drive is returned unchanged (the 1-element anchor relies on that).

Bit-exactness notes: when every tau is exactly 0.0 (broadside, or n = 1)
the synthesis is a plain sum without an FFT round trip, so a single element
at broadside returns its own output bit for bit.
"""
from __future__ import annotations

import numpy as np

from .geometry import C0, ArrayGeometry

TWO_PI = 2.0 * np.pi


def _bb_freqs(n_samples: int, fs: float) -> np.ndarray:
    return np.fft.fftfreq(n_samples, 1.0 / fs)


def steering_phase_weights(geom: ArrayGeometry, theta0_deg: float) -> np.ndarray:
    """Phase-shifter weights (complex, per element), aligned at f0."""
    tau = geom.delays_s(theta0_deg)
    return np.exp(-1j * TWO_PI * geom.f0_hz * tau)


def steer(x: np.ndarray, geom: ArrayGeometry, theta0_deg: float, fs: float,
          mode: str) -> list[np.ndarray]:
    """Per-element drives for the common signal ``x`` steered to theta0."""
    if mode not in ("phase", "ttd"):
        raise ValueError(f"steering must be phase or ttd, got {mode!r}")
    tau = geom.delays_s(theta0_deg)
    if np.all(tau == 0.0):
        return [x for _ in range(geom.n)]        # identity: same array, bit for bit
    if mode == "phase":
        w = np.exp(-1j * TWO_PI * geom.f0_hz * tau)
        return [x * wk for wk in w]
    X = np.fft.fft(x)
    f = _bb_freqs(x.size, fs)
    return [np.fft.ifft(X * np.exp(-1j * TWO_PI * (geom.f0_hz + f) * tk)) for tk in tau]


def far_field(ys, geom: ArrayGeometry, theta_deg: float, fs: float,
              *, normalize: bool = True) -> np.ndarray:
    """Far-field signal in direction ``theta_deg`` from the radiated element
    signals ``ys`` (list or (n, N) array), as a complex baseband burst."""
    ys = np.asarray(ys)
    if ys.ndim != 2 or ys.shape[0] != geom.n:
        raise ValueError(f"ys must be (n={geom.n}, N), got {ys.shape}")
    g = geom.element_gain(theta_deg)
    tau = geom.delays_s(theta_deg)
    scale = (g / geom.n) if normalize else g
    if np.all(tau == 0.0):
        e = ys[0] if geom.n == 1 else ys.sum(axis=0)
        return e if scale == 1.0 else e * scale
    Y = np.fft.fft(ys, axis=1)
    f = _bb_freqs(ys.shape[1], fs)
    ph = np.exp(1j * TWO_PI * np.outer(tau, geom.f0_hz + f))    # (n, N)
    return np.fft.ifft((Y * ph).sum(axis=0)) * scale


def far_field_many(ys, geom: ArrayGeometry, thetas_deg, fs: float,
                   *, normalize: bool = True) -> np.ndarray:
    """``far_field`` for many directions with the element FFTs done once.
    Returns (len(thetas), N)."""
    ys = np.asarray(ys)
    Y = np.fft.fft(ys, axis=1)
    f = _bb_freqs(ys.shape[1], fs)
    out = np.empty((len(thetas_deg), ys.shape[1]), dtype=complex)
    for i, th in enumerate(thetas_deg):
        tau = geom.delays_s(th)
        g = geom.element_gain(th)
        scale = (g / geom.n) if normalize else g
        ph = np.exp(1j * TWO_PI * np.outer(tau, geom.f0_hz + f))
        out[i] = np.fft.ifft((Y * ph).sum(axis=0)) * scale
    return out


# ------------------------------------------------------------ CW analysis
def array_factor_cw(geom: ArrayGeometry, theta0_deg: float, f_offset_hz: float,
                    thetas_deg, mode: str) -> np.ndarray:
    """|AF(theta)| (normalised to 1 at a perfectly coherent sum) for a CW tone
    at f0 + f_offset after steering to theta0 — the same phase model
    ``steer`` + ``far_field`` apply to a waveform, evaluated in closed form."""
    thetas = np.atleast_1d(np.asarray(thetas_deg, dtype=float))
    tau0 = geom.delays_s(theta0_deg)
    f_rf = geom.f0_hz + f_offset_hz
    if mode == "phase":
        w = np.exp(-1j * TWO_PI * geom.f0_hz * tau0)
    elif mode == "ttd":
        w = np.exp(-1j * TWO_PI * f_rf * tau0)
    else:
        raise ValueError(mode)
    af = np.empty(thetas.size)
    for i, th in enumerate(thetas):
        tau = geom.delays_s(th)
        af[i] = abs(np.sum(w * np.exp(1j * TWO_PI * f_rf * tau))) / geom.n * geom.element_gain(th)
    return af


def peak_direction_cw(geom: ArrayGeometry, theta0_deg: float, f_offset_hz: float,
                      mode: str, *, search_deg: float = 15.0, step_deg: float = 0.01) -> float:
    """Direction of the main-lobe peak for a CW tone at f0 + f_offset, by a
    fine grid around theta0 plus a parabolic refinement."""
    th = np.arange(theta0_deg - search_deg, theta0_deg + search_deg + step_deg / 2, step_deg)
    th = th[(th > -90.0) & (th < 90.0)]
    af = array_factor_cw(geom, theta0_deg, f_offset_hz, th, mode)
    i = int(np.argmax(af))
    if 0 < i < th.size - 1:
        y0, y1, y2 = af[i - 1], af[i], af[i + 1]
        denom = (y0 - 2 * y1 + y2)
        if denom != 0.0:
            return float(th[i] + 0.5 * (y0 - y2) / denom * step_deg)
    return float(th[i])


def squint_analytic_deg(theta0_deg: float, f0_hz: float, f_offset_hz: float) -> float:
    """Phase-shifter squint: the beam aligned at f0 points, at f0 + df, where
    sin(theta) = sin(theta0) * f0 / (f0 + df); for small df this is
    d theta ~ -(df / f0) tan(theta0)."""
    s = np.sin(np.deg2rad(theta0_deg)) * f0_hz / (f0_hz + f_offset_hz)
    return float(np.degrees(np.arcsin(np.clip(s, -1.0, 1.0))) - theta0_deg)


def highest_sidelobe_direction(geom: ArrayGeometry, theta0_deg: float, mode: str,
                               *, step_deg: float = 0.1) -> float | None:
    """Direction of the highest sidelobe of |AF| at f0 for the beam steered to
    theta0, or None when the pattern has no sidelobe (n = 1)."""
    if geom.n < 2:
        return None
    th = np.arange(-89.9, 89.9 + step_deg / 2, step_deg)
    af = array_factor_cw(geom, theta0_deg, 0.0, th, mode)
    # local maxima
    peaks = [i for i in range(1, th.size - 1) if af[i] >= af[i - 1] and af[i] > af[i + 1]]
    if not peaks:
        return None
    main = min(peaks, key=lambda i: abs(th[i] - theta0_deg))
    side = [i for i in peaks if i != main]
    if not side:
        return None
    best = max(side, key=lambda i: af[i])
    return float(th[best])


# ------------------------------------------------- squint as a beam EVM
def tone_frequencies_hz(wf) -> np.ndarray:
    """Baseband frequency of every active subcarrier of an OFDM waveform, in
    the order ``tx_symbols`` uses (``tone_indices`` x subcarrier spacing)."""
    ref = wf.require_ofdm_ref()
    c = ref.config
    scs = wf.fs / (c.fft_size * c.oversampling)
    return np.asarray(ref.tone_indices, dtype=float) * scs


def beam_response(geom: ArrayGeometry, theta0_deg: float, f_bb_hz, mode: str) -> np.ndarray:
    """The frequency response the far field in the BEAM direction sees after
    steering to theta0 with an ideal, identical element behind every port:

        H(f) = (1/n) sum_k W_k(f) exp(+j 2 pi (f0 + f) tau_k(theta0))

    For ``ttd`` this is 1 at every f; for ``phase`` it is the Dirichlet
    kernel (1/n) sum_k exp(j 2 pi f tau_k(theta0)) -- real for a centred
    array, 1 at f = 0, drooping towards the band edges.  This is the squint
    seen from the beam: a LINEAR, deterministic response, not noise."""
    f = np.atleast_1d(np.asarray(f_bb_hz, dtype=float))
    tau = geom.delays_s(theta0_deg)
    if mode == "ttd":
        return np.ones(f.shape, dtype=complex)
    if mode != "phase":
        raise ValueError(mode)
    return np.exp(1j * TWO_PI * np.outer(f, tau)).sum(axis=1) / geom.n


def squint_evm_closed_form_db(geom: ArrayGeometry, theta0_deg: float, f_tones_hz,
                              equalize: str = "scalar") -> float:
    """EVM (dB) the phase-steering squint alone costs at the beam, on tones of
    equal power: the residual of ``beam_response`` after the equaliser the
    EVM convention allows.  ``scalar`` (one complex gain, polar_tx's
    default) leaves the droop: EVM^2 = mean |H(f)/g - 1|^2 with g = mean H.
    ``per_tone`` removes a per-tone linear response entirely: -inf."""
    if equalize == "per_tone":
        return -np.inf
    if equalize != "scalar":
        raise ValueError(equalize)
    h = beam_response(geom, theta0_deg, f_tones_hz, "phase")
    g = h.mean()
    err = h / g - 1.0
    rms = float(np.sqrt(np.mean(np.abs(err) ** 2)))
    return -np.inf if rms == 0.0 else float(20.0 * np.log10(rms))


def _af_vectorised(geom: ArrayGeometry, theta0_deg: float, f_offset_hz: float,
                   thetas_deg: np.ndarray, mode: str) -> np.ndarray:
    """|AF| as ``array_factor_cw`` computes it, vectorised over theta (used
    for the fine beamwidth grids; ``array_factor_cw`` is kept as is so the
    squint / sidelobe numbers it produced do not move)."""
    tau0 = geom.delays_s(theta0_deg)
    f_rf = geom.f0_hz + f_offset_hz
    w = np.exp(-1j * TWO_PI * (geom.f0_hz if mode == "phase" else f_rf) * tau0)
    s = np.sin(np.deg2rad(thetas_deg))
    tau = np.outer(s, geom.plane_m) / C0                         # (T, n): positions along the scan plane
    af = np.abs(np.exp(1j * TWO_PI * f_rf * tau) @ w) / geom.n
    g = np.array([geom.element_gain(t) for t in thetas_deg])
    return af * g


def beamwidth_3db_deg(geom: ArrayGeometry, theta0_deg: float, mode: str = "phase",
                      f_offset_hz: float = 0.0) -> float:
    """Half-power width of the main lobe (degrees) at f0 + f_offset: the
    contiguous run around the peak where |AF| >= peak / sqrt(2), on a grid
    fine enough for the lobe (about 4000 points across 1.5x the textbook
    width 0.886 lambda / (n d cos theta0), at least 0.5 deg of search)."""
    if geom.n < 2:
        return 180.0
    c = max(np.cos(np.deg2rad(theta0_deg)), 1e-3)
    guess = np.degrees(0.886 * geom.wavelength_m / (geom.aperture_m * c))
    half = max(1.5 * guess, 0.5)
    th = np.linspace(theta0_deg - half, theta0_deg + half, 4001)
    th = th[(th > -90.0) & (th < 90.0)]
    af = _af_vectorised(geom, theta0_deg, f_offset_hz, th, mode)
    i = int(np.argmax(af))
    lvl = af[i] / np.sqrt(2.0)
    lo = i
    while lo > 0 and af[lo - 1] >= lvl:
        lo -= 1
    hi = i
    while hi < th.size - 1 and af[hi + 1] >= lvl:
        hi += 1
    return float(th[hi] - th[lo])

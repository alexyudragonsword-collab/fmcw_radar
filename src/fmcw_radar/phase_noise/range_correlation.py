"""Range correlation: what the beat signal sees of the shared LO's phase noise (invariant #2).

The transmit and receive mixers run on the same LO, so the beat phase carries
the *difference* of one phase-noise sequence and its copy delayed by the
round trip::

    phi_beat(t) = phi(t) - phi(t - tau),          tau = 2 R / c
    S_res(f)    = |1 - e^{-j 2 pi f tau}|^2 S_phi(f) = 2 (1 - cos 2 pi f tau) S_phi(f)

Three things this says, each a test (tests/test_range_correlation.py):

* tau = 0 -> nothing: the residual is zero, bit for bit (:meth:`residual`
  returns the input minus *itself*, not a delayed copy that happens to
  match);
* tau -> inf -> the two copies are uncorrelated and the residual is twice
  the single-sided PSD (the cosine averages out);
* in between the closed form, which the time-domain synthesis
  (:meth:`synthesize_residual`) reproduces band-averaged to a tenth of a dB.

This is the same equation d2d_link's forwarded clock uses for its tree delay
(``|1 - e^{-j 2 pi f tau}|^2`` on the Tx PLL's timing PSD): a forwarded
clock tracking its transmitter's PLL and a radar receiver mixing with its
own transmit LO are one mechanism.  The shortcut that treats the receive LO
as an independent oscillator would double the in-band noise instead of
cancelling it; tests/test_invariants.py keeps it out.

What the range FFT then sees: a noise sideband at offset ``df`` from the
target's beat tone, ``S_res(df) / 2`` per Hz single-sideband relative to the
tone, integrated over the window's equivalent noise bandwidth --
:meth:`sidelobe_dbc`.  Spurs (deterministic phase tones of peak ``a``) go
through the same difference as sinusoids of peak ``2 a |sin(pi f tau)|``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config.schema import C0, RadarConfig
from ..lo import LOProfile
from ..vendor.polartx.vendor.pllsim.core.colored import synth_from_psd

TWOPI = 2.0 * np.pi


def correlation_factor(f, tau_s: float) -> np.ndarray:
    """``2 (1 - cos 2 pi f tau)``: the residual's PSD over the LO's."""
    return 2.0 * (1.0 - np.cos(TWOPI * np.asarray(f, dtype=float) * tau_s))


def delayed(x: np.ndarray, tau_s: float, fs: float) -> np.ndarray:
    """``x`` delayed by ``tau_s`` (circular, in the FFT domain: exact for a
    band-limited stationary block).  ``tau_s == 0`` returns ``x`` itself."""
    if tau_s == 0.0:
        return x
    n = x.size
    f = np.fft.rfftfreq(n, d=1.0 / fs)
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-1j * TWOPI * f * tau_s), n=n)


@dataclass
class RangeCorrelation:
    """The residual LO phase noise at one round-trip delay."""

    profile: LOProfile
    tau_s: float

    @classmethod
    def from_config(cls, cfg: RadarConfig, range_m: float | None = None) -> "RangeCorrelation":
        return cls(LOProfile.from_config(cfg), cfg.tau_s(range_m))

    @property
    def range_m(self) -> float:
        return 0.5 * C0 * self.tau_s

    # ------------------------------------------------------------ closed form
    def residual_psd(self, f) -> np.ndarray:
        """S_res(f) [rad^2/Hz, DSB] = 2 (1 - cos 2 pi f tau) S_phi(f)."""
        return correlation_factor(f, self.tau_s) * self.profile.psd(f)

    def residual_l_dbc(self, f) -> np.ndarray:
        """The residual as a single-sideband level relative to the beat tone [dBc/Hz]."""
        return 10.0 * np.log10(np.maximum(self.residual_psd(f), 1e-300) / 2.0)

    def suppression_db(self, f) -> np.ndarray:
        """10 log of the factor: negative inside 1 / (6 tau), up to +6 dB beyond."""
        return 10.0 * np.log10(np.maximum(correlation_factor(f, self.tau_s), 1e-300))

    def sidelobe_dbc(self, offset_hz, enbw_hz: float) -> np.ndarray:
        """The phase-noise sidelobe a range FFT of equivalent noise bandwidth
        ``enbw_hz`` (per bin) shows at ``offset_hz`` from the target's tone,
        relative to the tone's peak [dBc]: ``S_res / 2 x ENBW``."""
        return self.residual_l_dbc(offset_hz) + 10.0 * np.log10(enbw_hz)

    def beat_sideband(self, f_max_hz: float, n: int = 1 << 16, f_far_hz: float | None = None) -> "BeatSideband":
        """The beat tone's spectrum under the residual phase noise, exactly for
        Gaussian phase: the autocorrelation of ``exp(j phi)`` is ``exp(R(t) -
        R(0))`` (R the residual's autocorrelation), so the carrier keeps
        ``exp(-sigma^2)`` of its power and the rest is the Fourier transform of
        ``exp(R(t) - R(0)) - exp(-R(0))``, every order of the noise included.
        To first order that is the ``S_res / 2`` sideband ``sidelobe_dbc``
        uses; at a residual of 0.3 rad RMS (a 100 m target on the default LO)
        the second order -- the in-band noise beating with itself -- lays a
        floor 20 dB above it near the tone (cairn/range-correlation.md).

        Evaluated on an FFT grid of ``n`` points spanning ``+-f_max_hz``;
        the residual beyond the grid (to ``f_far_hz``, the waveform's
        Nyquist) only takes power from the carrier (its own intermodulation
        is far below anything in band) and enters as ``sigma_far^2``."""
        fs = 2.0 * f_max_hz
        f = np.fft.fftfreq(n, d=1.0 / fs)
        s_two = 0.5 * self.residual_psd(np.abs(f))          # two-sided PSD of the real phase [rad^2/Hz]
        s_two[0] = 0.0
        r = np.fft.ifft(s_two).real * fs                    # R(t) on the grid, R[0] = sigma^2 in band
        sigma2_far = 0.0
        if f_far_hz is not None and f_far_hz > f_max_hz:
            sigma2_far = self.rms_residual_rad(f_max_hz, f_far_hz, 4000) ** 2
        sigma2 = float(r[0]) + sigma2_far
        c = np.exp(r - r[0] - sigma2_far)                   # autocorrelation of exp(j phi)
        carrier = math.exp(-sigma2)
        p_noise = np.fft.fft(c - carrier).real / fs         # two-sided PSD of the noise part [1/Hz]
        return BeatSideband(f, np.maximum(p_noise, 0.0), carrier, sigma2, fs)

    def spur_terms(self) -> list[tuple[float, float]]:
        """``(offset_hz, residual peak phase [rad])`` of the profile's spurs."""
        out = [(f0, 2.0 * a * abs(math.sin(math.pi * f0 * self.tau_s))) for f0, a in self.profile.spurs]
        return [(f0, a) for f0, a in out if a > 0.0]

    def rms_residual_rad(self, f1: float, f2: float, n: int = 4000) -> float:
        f = np.geomspace(f1, f2, n)
        trap = getattr(np, "trapezoid", None) or np.trapz
        return float(np.sqrt(trap(self.residual_psd(f), f)))

    # -------------------------------------------------------------- synthesis
    def synthesize_lo(self, n: int, fs: float, rng: np.random.Generator) -> np.ndarray:
        """One block of the LO's phase noise [rad] at ``fs``."""
        return synth_from_psd(self.profile.psd, fs, n, rng)

    def residual(self, phi: np.ndarray, fs: float) -> np.ndarray:
        """``phi(t) - phi(t - tau)`` of a synthesised block (circular delay).
        At tau = 0 this is ``phi - phi``: zero, bit for bit."""
        return phi - delayed(phi, self.tau_s, fs)

    def synthesize_residual(self, n: int, fs: float, rng: np.random.Generator) -> np.ndarray:
        return self.residual(self.synthesize_lo(n, fs, rng), fs)

    def measured_residual_psd(self, n: int, fs: float, rng: np.random.Generator, blocks: int = 8):
        """``(f, S_res)`` from ``blocks`` synthesised blocks (one-sided
        periodogram averaged; a DSB phase PSD, like the closed form)."""
        acc = None
        for _ in range(blocks):
            r = self.synthesize_residual(n, fs, rng)
            spec = np.fft.rfft(r)
            p = 2.0 * np.abs(spec) ** 2 / (fs * n)
            acc = p if acc is None else acc + p
        f = np.fft.rfftfreq(n, d=1.0 / fs)
        return f[1:], acc[1:] / blocks


@dataclass
class BeatSideband:
    """``exp(j phi)``'s spectrum: ``psd`` [1/Hz] of the noise part on the
    (unshifted FFT) grid ``f``, the carrier's remaining power ``carrier``
    (``exp(-sigma^2)``), the residual's total ``sigma2`` [rad^2]."""

    f: np.ndarray
    psd: np.ndarray
    carrier: float
    sigma2: float
    fs: float

    def sidelobe_dbc(self, offset_hz, enbw_hz: float) -> np.ndarray:
        """The sideband a range FFT of noise bandwidth ``enbw_hz`` shows at
        ``offset_hz`` from the tone, relative to the tone's peak [dBc]."""
        offs = np.asarray(offset_hz, dtype=float)
        order = np.argsort(self.f)
        p = np.interp(offs, self.f[order], self.psd[order])
        return 10.0 * np.log10(np.maximum(p * enbw_hz / self.carrier, 1e-300))

    @property
    def carrier_loss_db(self) -> float:
        return 10.0 * math.log10(self.carrier)


def residual_vs_range(cfg: RadarConfig, ranges_m, offsets_hz) -> np.ndarray:
    """Closed-form residual L(f) [dBc/Hz] on a (range, offset) grid."""
    prof = LOProfile.from_config(cfg)
    out = np.empty((len(ranges_m), len(offsets_hz)))
    for i, r in enumerate(ranges_m):
        out[i] = RangeCorrelation(prof, cfg.tau_s(r)).residual_l_dbc(offsets_hz)
    return out


__all__ = ["RangeCorrelation", "BeatSideband", "correlation_factor", "delayed", "residual_vs_range"]

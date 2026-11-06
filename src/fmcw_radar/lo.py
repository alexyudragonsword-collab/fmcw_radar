"""The one LO: the vendored ADPLL at ``center / mult`` behind an ideal multiplier.

Two things come out of here and nothing else makes them:

* :func:`build_adpll` -- the vendored pll_simulator ADPLL (TDC mode, PI loop
  synthesised for the config's bandwidth and phase margin) that the chirp
  engine (``fmcw_radar.chirp``) modulates and the response engine
  linearises.  One object, built from the config alone.
* :class:`LOProfile` -- the LO's phase-noise PSD at the *carrier*
  (``band.center_hz``), ``S_phi(f)`` in rad^2/Hz double-sideband: the
  ADPLL's own small-signal budget (``analyze()``, the pll_simulator linear
  model) times ``mult^2``, or a pll_simulator clock-profile YAML scaled the
  same way.  The transmit and receive mixers share it; the beat signal sees
  it only through range correlation (``fmcw_radar.phase_noise``, invariant
  #2).  There is no receive-side LO object anywhere (tests/test_invariants.py).

The multiplier is ideal: phase x N, phase noise +20 log N, no floor of its
own (source: assumed, like every front-end placeholder).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config.schema import RadarConfig
from .vendor.polartx.vendor.pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from .vendor.polartx.vendor.pllsim.blocks.oscillator import OscConfig
from .vendor.polartx.vendor.pllsim.blocks.tdc import TDCConfig
from .vendor.polartx.vendor.pllsim.synth import design_adpll_dlf

TWOPI = 2.0 * np.pi
PACKAGE_DIR = Path(__file__).resolve().parent


def resolve_data_file(path: str, repo_root: Path | None = None) -> Path:
    """A data path as a config writes it, made absolute: absolute as it is;
    else the bundled copy inside the package, the checkout root, then the
    working directory (d2d_link's rule)."""
    p = Path(path)
    if p.is_absolute():
        return p
    root = repo_root or PACKAGE_DIR.parents[1]
    for cand in (PACKAGE_DIR / p, root / p, Path.cwd() / p):
        if cand.exists():
            return cand
    return p


def build_adpll(cfg: RadarConfig) -> ADPLL:
    """The vendored ADPLL of the config: DCO at ``center / mult`` with the
    config's (or the placeholder's) noise figures, a TDC of the given
    resolution, a PI loop synthesised against the exact z-domain model for
    ``loop_bw_hz`` / ``phase_margin_deg`` (polar_tx's ``ble_adpll`` recipe)."""
    lo = cfg.lo
    fout = cfg.dco_center_hz
    alpha, rho = design_adpll_dlf(lo.fref_hz, lo.loop_bw_hz, lo.phase_margin_deg)
    pn, _ = cfg.lo_value("dco_pn_dbchz")
    floor, _ = cfg.lo_value("dco_pn_floor_dbchz")
    tres, _ = cfg.lo_value("tdc_res_s")
    osc = OscConfig(f0=fout, gain=lo.kdco_hz, pn_dbchz=pn, pn_foffset=lo.dco_pn_offset_hz,
                    pn_f1f3=lo.dco_pn_f1f3_hz, pn_floor_dbchz=floor)
    return ADPLL(ADPLLConfig(fref=lo.fref_hz, fout=fout, osc=osc, dlf=DLFConfig(alpha=alpha, rho=rho),
                             mode="tdc", tdc=TDCConfig(t_res=tres), ref_pn_dbchz=lo.ref_pn_dbchz,
                             int_band=(1e3, lo.fref_hz / 2.0)))


@dataclass
class LOProfile:
    """S_phi(f) of the LO at the carrier, interpolated in (log f, dB) between
    the grid points, the first value held below the grid and the last held
    flat above it (the DCO floor runs to the waveform's Nyquist: d2d_link's
    ``profile_above: floor`` reading).  ``spurs`` are ``(offset_hz, peak
    phase [rad])`` at the carrier -- none for the ADPLL's own analysis of an
    integer-N loop, the file's table otherwise."""

    f_hz: np.ndarray
    s_phi: np.ndarray                   # rad^2/Hz, double-sideband, at the carrier
    carrier_hz: float
    mult: int
    source: str
    spurs: tuple[tuple[float, float], ...] = ()

    @classmethod
    def from_config(cls, cfg: RadarConfig) -> "LOProfile":
        n = cfg.lo_mult
        if cfg.lo.profile is None:
            pll = build_adpll(cfg)
            ana = pll.analyze()
            # the sampled loop's response is periodic in fref: above fref / 2
            # the linear model repeats its images (the quantisation noise
            # folds back) and means nothing there (polar_tx integrates to
            # fref / 2).  Beyond it the loop does nothing to the DCO (its
            # error function is 1), so the LO is the DCO alone: Leeson's
            # 1/f^2 down to the DCO's floor, out to the waveform's Nyquist.
            f = np.asarray(ana.f, dtype=float)
            keep = f <= 0.5 * cfg.lo.fref_hz
            far = np.geomspace(0.5 * cfg.lo.fref_hz * 1.0001, 100.0 * cfg.band.sweep_hz, 120)
            s_far = np.asarray(pll.cfg.osc.leeson("dco").psd(far), dtype=float)
            s = np.concatenate([np.asarray(ana.pn_breakdown["total"], dtype=float)[keep], s_far]) * n * n
            return cls(np.concatenate([f[keep], far]), s, cfg.band.center_hz, n,
                       f"vendored ADPLL analyze() at {cfg.dco_center_hz / 1e9:.4g} GHz x{n}, the DCO alone above "
                       f"fref/2 (source: assumed)")
        import yaml

        p = resolve_data_file(cfg.lo.profile)
        with open(p, encoding="utf-8") as fh:
            d = yaml.safe_load(fh) or {}
        for key in ("f0_hz", "f_hz", "l_dbc_hz"):
            if key not in d:
                raise ValueError(f"{p}: clock profile is missing {key!r}")
        f = np.asarray(d["f_hz"], dtype=float)
        l_dbc = np.asarray(d["l_dbc_hz"], dtype=float) + cfg.lo.profile_shift_db
        if f.ndim != 1 or f.size < 2 or np.any(np.diff(f) <= 0.0) or np.any(f <= 0.0):
            raise ValueError(f"{p}: f_hz must be positive and strictly ascending")
        # the file describes its own carrier f0; the DCO runs at center / mult,
        # an ideal divider / multiplier scales phase by the frequency ratio
        scale = (cfg.dco_center_hz / float(d["f0_hz"])) ** 2 * n * n
        s = 2.0 * 10.0 ** (l_dbc / 10.0) * scale
        amp = np.sqrt(scale)
        spurs = tuple((float(r["f_hz"]), 2.0 * 10.0 ** ((float(r["dbc"]) + cfg.lo.profile_shift_db) / 20.0) * amp)
                      for r in (d.get("spurs") or []))
        return cls(f, s, cfg.band.center_hz, n, f"{p.name}: {d.get('source', '')} x{n}", spurs)

    def psd(self, f) -> np.ndarray:
        """S_phi(f) [rad^2/Hz, DSB] at the carrier on any grid."""
        f = np.asarray(f, dtype=float)
        lf = np.log10(np.maximum(f, self.f_hz[0]))
        ls = np.interp(lf, np.log10(self.f_hz), np.log10(np.maximum(self.s_phi, 1e-300)))
        return 10.0 ** ls

    def l_dbc(self, f) -> np.ndarray:
        """Single-sideband L(f) [dBc/Hz] at the carrier."""
        return 10.0 * np.log10(np.maximum(self.psd(f), 1e-300) / 2.0)

    def rms_phase_rad(self, f1: float, f2: float, n: int = 2000) -> float:
        """Integrated phase [rad RMS] over [f1, f2] (trapezoid in log f)."""
        f = np.geomspace(f1, f2, n)
        trap = getattr(np, "trapezoid", None) or np.trapz
        return float(np.sqrt(trap(self.psd(f), f)))


__all__ = ["build_adpll", "LOProfile", "resolve_data_file"]

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
from .vendor.polartx.vendor.pllsim.core.boundaries import tdc_dead_zone
from .vendor.polartx.vendor.pllsim.core.tdcspurs import code_span
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
    tjit, _ = cfg.lo_value("tdc_jitter_s")
    osc = OscConfig(f0=fout, gain=lo.kdco_hz, pn_dbchz=pn, pn_foffset=lo.dco_pn_offset_hz,
                    pn_f1f3=lo.dco_pn_f1f3_hz, pn_floor_dbchz=floor)
    tdc = TDCConfig(t_res=tres, jitter_rms_s=tjit)
    span = code_span(tdc, fout)                  # one DCO period over the TDC's range
    if span > 1.0:
        # polar_tx's finding behind its B1 (polar_tx#19): the counter reads whole DCO cycles and the TDC the
        # fraction, so a TDC shorter than a period saturates every cycle.  A broken loop, not a noisy one, and
        # the linear analysis would describe a TDC that works: refused for every engine.
        raise ValueError(f"lo.tdc_res_s = {tres * 1e12:g} ps: the {tdc.n_bits}-bit TDC covers {1.0 / span:.2f} of the "
                         f"{1e12 / fout:.1f} ps DCO period and would saturate every cycle; it must span one period")
    return ADPLL(ADPLLConfig(fref=lo.fref_hz, fout=fout, osc=osc, dlf=DLFConfig(alpha=alpha, rho=rho),
                             mode="tdc", tdc=tdc, ref_pn_dbchz=lo.ref_pn_dbchz,
                             int_band=(1e3, lo.fref_hz / 2.0)))


def parked_lo(cfg: RadarConfig) -> dict:
    """The LO while it is *not* ramping, which the linear profile does not
    vouch for (ROADMAP P1 #1(c)).

    An integer-N TDC loop with less than half a TDC bin of RMS dither at
    the TDC's input parks inside one bin: the loop cannot see the DCO drift
    there, and the cycle-accurate engine reads more in-band phase noise
    than ``analyze()`` -- pllsim's ``tdc_dead_zone`` (pll_simulator #77),
    measured on the default loop through the vendored copy, mean over 30 /
    100 / 300 kHz: on the 12.2 ps TDC (0.2.12) +18.8 dB with no TDC jitter,
    +14.9 dB at the 1 ps placeholder (0.09 bin), +4.2 at 3 ps, +0.9 at 5 ps
    (0.41 bin: flagged, nearly harmless), +1.1 at 6.5 ps (0.53 bin: not
    flagged); on the 5 ps placeholder before it, +15.8 dB at 30 kHz with no
    jitter, +5.5 dB at 1 ps (0.22 bin), +0.1 dB at 2 ps (0.41 bin).
    A frequency ramp sweeps the fraction of a cycle the TDC reads across
    its bins every reference cycle, which is a dither: on the ramp the
    engine and the profile agree within 0.6 dB (tests/test_lo_noise_split.py),
    so the radar's own use of the LO is covered.  What is not: the LO
    parked at the carrier (CW), and the ``chirp.idle_s`` it spends at the
    ramp's start frequency between ramps.  Each is in the dead zone only if
    *that* frequency is an integer multiple of the reference.

    Returns ``known`` (False for a profile read from a file: its loop is
    not ours to analyse), ``dither_bins``, ``fcw_center`` / ``fcw_idle``,
    ``dead_zone_center`` / ``dead_zone_idle``, ``idle_s`` and the share of
    the PRI spent idle."""
    out = {"known": cfg.lo.profile is None, "idle_s": cfg.chirp.idle_s, "idle_fraction": cfg.chirp.idle_s / cfg.chirp.pri_s,
           "dither_bins": None, "fcw_center": None, "fcw_idle": None, "dead_zone_center": None, "dead_zone_idle": None}
    if not out["known"]:
        return out
    pll = build_adpll(cfg)
    t_res = float(pll.cfg.tdc.t_res)
    dither = float(pll.tdc_dither_rms_s())
    fcw_c = cfg.dco_center_hz / cfg.lo.fref_hz
    fcw_i = (cfg.dco_center_hz - 0.5 * cfg.dco_sweep_hz) / cfg.lo.fref_hz
    out.update(dither_bins=dither / t_res, fcw_center=fcw_c, fcw_idle=fcw_i,
               dead_zone_center=bool(tdc_dead_zone(fcw_c, t_res, dither)), dead_zone_idle=bool(tdc_dead_zone(fcw_i, t_res, dither)))
    return out


@dataclass
class LOProfile:
    """S_phi(f) of the LO at the carrier, interpolated in (log f, dB) between
    the grid points, the first value held below the grid and the last held
    flat above it (the DCO floor runs to the waveform's Nyquist: d2d_link's
    ``profile_above: floor`` reading).  ``spurs`` are ``(offset_hz, peak
    phase [rad])`` at the carrier -- none for the ADPLL's own analysis of an
    integer-N loop, the file's table otherwise.

    ``components`` is the same PSD by source on the same grid (the ADPLL's
    own breakdown: ``ref``, ``dco``, ``tdc_quant``, ``dco_quant``,
    ``tdc_jitter``).  A profile read from a file has the file's own breakdown
    if it carries one; a file without one read under the event chirp engine
    is ``file`` plus the chirp generator's two quantisation terms, which the
    file does not know of and the chirp curve carries; otherwise None.  It is what lets the time engine split the
    LO's noise with the chirp engine without counting anything twice: the
    cycle-accurate error curve already *is* the TDC's and the DCO's
    quantisation (``without("tdc_quant", "dco_quant")`` is what is left to
    synthesise), and with the loop's noise sources on it is everything the
    loop does up to fref / 2 (``above(fref / 2)`` is what is left)."""

    f_hz: np.ndarray
    s_phi: np.ndarray                   # rad^2/Hz, double-sideband, at the carrier
    carrier_hz: float
    mult: int
    source: str
    spurs: tuple[tuple[float, float], ...] = ()
    components: dict | None = None      # name -> rad^2/Hz on f_hz, summing to s_phi
    notes: tuple[str, ...] = ()         # the loop's own analysis notes, verbatim (none for a profile read from a file)

    def without(self, *names: str) -> "LOProfile":
        """The profile less the named sources (those it does not have are
        ignored; a profile with no breakdown is returned as it is)."""
        if not self.components:
            return self
        drop = [k for k in names if k in self.components]
        if not drop:
            return self
        s = np.maximum(self.s_phi - sum(self.components[k] for k in drop), 1e-300)
        rest = {k: v for k, v in self.components.items() if k not in drop}
        return LOProfile(self.f_hz, s, self.carrier_hz, self.mult, f"{self.source}; less {', '.join(drop)}", self.spurs, rest, self.notes)

    def above(self, f_split_hz: float) -> "LOProfile":
        """The profile above ``f_split_hz`` only (nothing below it)."""
        keep = self.f_hz > f_split_hz
        if not np.any(keep):
            raise ValueError(f"the profile has nothing above {f_split_hz:g} Hz")
        f = np.concatenate([[f_split_hz * (1.0 - 1e-9), f_split_hz], self.f_hz[keep]])
        edge = float(self.psd(np.array([f_split_hz * (1.0 + 1e-9)]))[0])
        s = np.concatenate([[1e-300, edge], self.s_phi[keep]])
        comp = None
        if self.components:
            comp = {k: np.concatenate([[0.0, float(np.interp(f_split_hz, self.f_hz, v))], v[keep]]) for k, v in self.components.items()}
        return LOProfile(f, s, self.carrier_hz, self.mult, f"{self.source}; above {f_split_hz / 1e6:g} MHz only",
                         tuple(sp for sp in self.spurs if sp[0] > f_split_hz), comp)

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
            comp = {k: np.concatenate([np.asarray(v, dtype=float)[keep], s_far if k == "dco" else np.zeros(far.size)]) * n * n
                    for k, v in ana.pn_breakdown.items() if k != "total"}
            return cls(np.concatenate([f[keep], far]), s, cfg.band.center_hz, n,
                       f"vendored ADPLL analyze() at {cfg.dco_center_hz / 1e9:.4g} GHz x{n}, the DCO alone above "
                       f"fref/2 (source: assumed)", components=comp, notes=tuple(str(x) for x in ana.notes))
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
        source = f"{p.name}: {d.get('source', '')} x{n}"
        comp, notes = None, ()
        if d.get("components"):
            # a file that says what its total is made of (tools/export_lo_profile.py writes it): the same
            # split as the live analysis, nothing to add
            comp = {str(k): 2.0 * 10.0 ** ((np.asarray(v, dtype=float) + cfg.lo.profile_shift_db) / 10.0) * scale
                    for k, v in d["components"].items()}
            if any(v.shape != f.shape for v in comp.values()):
                raise ValueError(f"{p}: every component must be on the f_hz grid")
            if not np.allclose(sum(comp.values()), s, rtol=1e-6):
                raise ValueError(f"{p}: the components do not sum to l_dbc_hz")
        elif cfg.lo.engine == "event":
            # another synthesiser's noise under this library's chirp generator.  The cycle-accurate chirp
            # curve carries the generator's TDC and DCO quantisation whatever noise file is named, and the
            # file knows nothing of it: it is added here once, as the same two terms the live analysis has,
            # so both engines count it and neither counts it twice (the time engine takes it back out of
            # what it synthesises, because the curve already is it)
            pll = build_adpll(cfg)
            below = f <= 0.5 * cfg.lo.fref_hz
            bd = pll.analyze(f[below]).pn_breakdown
            comp = {"file": s}
            for name in ("tdc_quant", "dco_quant"):
                if name in bd:
                    q = np.zeros_like(s)
                    q[below] = np.asarray(bd[name], dtype=float) * n * n
                    comp[name] = q
            s = sum(comp.values())
            source += "; plus the chirp generator's TDC and DCO quantisation (the vendored ADPLL's analyze())"
            notes = ("The noise is a file's, the chirp is this library's two-point ADPLL's: the generator's TDC and DCO "
                     "quantisation is added to the file's profile (the cycle-accurate chirp curve carries it, the file does not).",)
        return cls(f, s, cfg.band.center_hz, n, source, spurs, comp, notes)

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


__all__ = ["build_adpll", "LOProfile", "parked_lo", "resolve_data_file"]

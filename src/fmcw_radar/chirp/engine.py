"""The chirp generator: a frequency ramp through the vendored two-point ADPLL (invariant #4).

A linear FM chirp is the two-point modulator fed a ramp.  The ramp at the DCO
sweeps ``sweep / mult`` around ``center / mult``; ``mult`` restores the
carrier.  The chirp's frequency error -- what makes a point target's range
response wider than ``c / 2B`` and puts sidelobes on it -- comes from the
loop's own response to that ramp, and from nothing else:

``engine: event``
    polar_tx's cycle-accurate ADPLL (``ADPLL.simulate(mod_freq=...)``, one
    step per reference cycle): the loop settling after each flyback (a
    frequency step of ``-B/N`` through the direct point, ``eps B/N`` of it
    left for the loop when the two-point gains mismatch by ``eps``), the
    TDC's and the DCO's quantisation through the loop, and with
    ``noise=True`` the phase noise.  Its ``freq_out`` *is* the instantaneous
    frequency error curve.  The only engine a spur or quantisation claim may
    come from (invariant #6).
``engine: response``
    polar_tx's linearised z-domain composite ``H_tp = h + g (1 - h)`` on the
    commanded phase: the mismatch transient alone, no quantisation.  The
    reference the event engine is checked against, and a fast path.
``engine: ideal``
    no error: the reference the resolution acceptance is measured against.

Validity.  polar_tx declares the event engine valid only while the phase
advances much less than one UI per reference cycle (its ``ui_per_ref_cycle``
metric, the DCO-cycle deviation per reference cycle): a GFSK trajectory is a
sub-cycle phase excursion the TDC must resolve.  A chirp is a different
object: a deviation of ``B / 2N`` reads 5 UI per cycle on the 60 GHz
default (495 %, measured), but the counter-assisted ADPLL counts whole DCO
cycles and the TDC only the fraction, so a ramp is the loop's native
operation (a fractional FCW is one).  The chirp engine therefore measures
the metric, reports it in :attr:`ChirpResult.ui_per_ref_cycle_p99`, and
checks the event engine against the linearised one on the mismatch
transient (tests/test_chirp.py: step and decay agree cycle by cycle); the
warning polar_tx raises inside ``ADPLLTwoPoint`` event mode is not
triggered because the engine drives ``ADPLL.simulate`` directly.  What the
metric does flag -- a sub-cycle trajectory -- a chirp does not have.
cairn/chirp-engine.md records the measurement.

The analytic quadratic (``quadratic_reference``) is a *reference group*
only: a frequency error of the same RMS shaped ``a (t/T - 1/2)^2``, for
example 02 to show what an assumed term misses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..config.schema import RadarConfig
from ..lo import build_adpll
from ..vendor.polartx.phasemod import ADPLLTwoPoint
from .dp_cal import ChirpSignSignCal, offline_dp_gain

TWOPI = 2.0 * np.pi


@dataclass
class ChirpResult:
    """The chirp train as the LO made it, on the reference-cycle grid."""

    engine: str                         # event | response | ideal
    fref_hz: float
    n_chirps: int
    n_ramp: int                         # reference cycles per ramp
    n_idle: int                         # reference cycles of flyback between ramps
    mult: int
    f_cmd_dco_hz: np.ndarray            # commanded DCO deviation from its centre [Hz], whole train
    f_err_dco_hz: np.ndarray            # instantaneous DCO frequency error [Hz], whole train
    dp_gain_used: float                 # direct-path gain the engine ran with (after calibration)
    dp_cal_trace: np.ndarray | None = None
    dp_cal_passes: list[dict] = field(default_factory=list)
    ui_per_ref_cycle_p99: float = 0.0   # polar_tx's event-validity metric on this ramp
    cpu_s: float = 0.0
    vouches_for_spurs: bool = False     # invariant #6: only the cycle-accurate engine does
    note: str = ""

    # ---------------------------------------------------------------- views
    @property
    def pri_cycles(self) -> int:
        return self.n_ramp + self.n_idle

    def ramp(self, k: int) -> np.ndarray:
        """The frequency error [Hz] at the DCO over ramp ``k``."""
        i0 = k * self.pri_cycles
        return self.f_err_dco_hz[i0:i0 + self.n_ramp]

    def ramp_carrier(self, k: int) -> np.ndarray:
        """The same at the carrier (x mult)."""
        return self.mult * self.ramp(k)

    @property
    def t_ramp_s(self) -> np.ndarray:
        return np.arange(self.n_ramp) / self.fref_hz

    def phase_err_carrier_rad(self) -> np.ndarray:
        """The carrier phase error [rad] along the whole train (cumulative sum
        of the frequency error, one reference period per cycle), the quantity
        the time engine interpolates at ``t`` and ``t - tau``."""
        return TWOPI * self.mult * np.cumsum(self.f_err_dco_hz) / self.fref_hz

    def metrics(self, k: int | None = None) -> dict:
        """Peak / RMS frequency error at the carrier and the settling time of
        ramp ``k`` (the last one by default): the time after which the error
        stays within a band of 2 % of the flyback step or five times the
        floor's RMS (the last fifth of the ramp), whichever is wider."""
        k = self.n_chirps - 1 if k is None else k
        e = self.ramp_carrier(k)
        n = e.size
        tail = e[-max(n // 5, 2):]
        floor = float(np.std(tail))
        step = self.mult * (self.f_cmd_dco_hz[k * self.pri_cycles] - self.f_cmd_dco_hz[k * self.pri_cycles - 1]
                            if k > 0 else self.f_cmd_dco_hz[0])
        initial = float(abs(e[0] - np.mean(tail)))       # what the loop has to settle out
        band = max(0.02 * initial, 5.0 * floor, 1e-9)
        out = np.where(np.abs(e - np.mean(tail)) > band)[0]
        settle = (out.max() + 1) / self.fref_hz if out.size else 0.0
        return {"peak_hz": float(np.max(np.abs(e))), "rms_hz": float(np.std(e)), "mean_hz": float(np.mean(e)),
                "floor_rms_hz": floor, "initial_error_hz": initial, "settle_s": float(settle),
                "settle_band_hz": float(band), "flyback_step_hz": float(step)}


def command_train(cfg: RadarConfig) -> tuple[np.ndarray, int, int]:
    """The DCO frequency command of the whole frame on the reference grid:
    ``n_chirps`` sawtooth ramps of ``n_ramp`` cycles from ``-B/2N`` to
    ``+B/2N`` with ``n_idle`` cycles at the start frequency between them."""
    n_ramp, n_idle = cfg.n_ref_cycles, cfg.n_idle_cycles
    dev = cfg.dco_sweep_hz
    ramp = -0.5 * dev + dev * np.arange(n_ramp) / n_ramp
    one = np.concatenate([ramp, np.full(n_idle, -0.5 * dev)])
    return np.tile(one, cfg.chirp.n_chirps), n_ramp, n_idle


def ui_per_ref_cycle_p99(f_cmd_dco: np.ndarray, fref: float) -> float:
    """polar_tx's event-validity metric: DCO deviation per reference cycle [UI]."""
    ui = np.abs(f_cmd_dco) / fref
    return float(np.percentile(ui, 99)) if ui.size else 0.0


def quadratic_reference(cfg: RadarConfig, rms_hz: float, n_chirps: int | None = None) -> ChirpResult:
    """A *reference group* (invariant #4 forbids it as a model): the frequency
    error ``a (t/T - 1/2)^2`` with its mean removed, scaled to ``rms_hz`` at
    the DCO, repeated on every ramp."""
    f_cmd, n_ramp, n_idle = command_train(cfg)
    nc = cfg.chirp.n_chirps if n_chirps is None else n_chirps
    x = (np.arange(n_ramp) + 0.5) / n_ramp - 0.5
    q = x * x - np.mean(x * x)
    q = q / np.std(q) * rms_hz
    one = np.concatenate([q, np.zeros(n_idle)])
    err = np.tile(one, nc)
    return ChirpResult("quadratic", cfg.lo.fref_hz, nc, n_ramp, n_idle, cfg.lo_mult, f_cmd[:err.size], err,
                       cfg.lo.dp_gain, note="analytic quadratic reference group: not a loop result")


class ChirpEngine:
    """Build the chirp train of a config with the engine it names."""

    def __init__(self, cfg: RadarConfig):
        self.cfg = cfg
        self.pll = build_adpll(cfg)

    def run(self, *, noise: bool = False, seed: int | None = None, n_chirps: int | None = None) -> ChirpResult:
        cfg = self.cfg
        seed = cfg.sim.seed if seed is None else seed
        nc = cfg.chirp.n_chirps if n_chirps is None else n_chirps
        f_cmd, n_ramp, n_idle = command_train(cfg)
        f_cmd = f_cmd[:nc * (n_ramp + n_idle)]
        ui99 = ui_per_ref_cycle_p99(f_cmd, cfg.lo.fref_hz)
        t0 = time.time()
        if cfg.lo.engine == "ideal":
            res = ChirpResult("ideal", cfg.lo.fref_hz, nc, n_ramp, n_idle, cfg.lo_mult, f_cmd, np.zeros_like(f_cmd),
                              cfg.lo.dp_gain, ui_per_ref_cycle_p99=ui99, note="no frequency error (reference)")
        elif cfg.lo.engine == "response":
            res = self._response(f_cmd, nc, n_ramp, n_idle, noise, seed, ui99)
        else:
            res = self._event(f_cmd, nc, n_ramp, n_idle, noise, seed, ui99)
        res.cpu_s = time.time() - t0
        return res

    # ------------------------------------------------------------ response
    def _modulator(self, dp_gain: float, mode: str) -> ADPLLTwoPoint:
        return ADPLLTwoPoint(self.pll, dp_gain=dp_gain, mode=mode, settle_cycles=self.cfg.lo.settle_cycles)

    def _response(self, f_cmd, nc, n_ramp, n_idle, noise, seed, ui99) -> ChirpResult:
        cfg = self.cfg
        fref = cfg.lo.fref_hz
        dp_gain, passes = self._calibrate_offline(f_cmd[:n_ramp + n_idle], "response")
        pm = self._modulator(dp_gain, "response")
        phase_cmd = TWOPI * np.cumsum(f_cmd) / fref
        out = pm.modulate(phase_cmd, fref, noise=noise, seed=seed).phase_out
        f_err = np.diff(out - phase_cmd, prepend=0.0) * fref / TWOPI
        return ChirpResult("response", fref, nc, n_ramp, n_idle, cfg.lo_mult, f_cmd, f_err, dp_gain,
                           dp_cal_passes=passes, ui_per_ref_cycle_p99=ui99,
                           note="linearised engine: cannot vouch for spurs or quantisation")

    # --------------------------------------------------------------- event
    def _simulate(self, f_cmd, dp_gain, noise, seed, dp_cal=None):
        settle = self.cfg.lo.settle_cycles
        seq = np.concatenate([np.zeros(settle), f_cmd, np.zeros(2)])
        sim = self.pll.simulate(seq.size, noise=noise, seed=seed, mod_freq=seq, mod_dp_gain=dp_gain, dp_cal=dp_cal)
        f_err = sim.freq_out[settle:settle + f_cmd.size] - (self.pll.cfg.fout + f_cmd)
        return f_err, sim

    def _calibrate_offline(self, one_pri: np.ndarray, mode: str) -> tuple[float, list[dict]]:
        """``lo.dp_cal: offline``: ``dp_cal_iterations`` least-squares passes
        on the engine that will be used, starting from the gain as built;
        returns the corrected gain and the passes.  Each pass simulates three
        chirps and estimates on the last two: the first ramp starts from the
        locked loop (a half-size flyback) and would bias the estimate, which
        models a train of full flybacks (its highpass regressor wraps the
        segment's end to its start)."""
        cfg = self.cfg
        dp_gain = cfg.lo.dp_gain
        passes: list[dict] = []
        if cfg.lo.dp_cal != "offline":
            return dp_gain, passes
        fref = cfg.lo.fref_hz
        n_pri = one_pri.size
        train = np.tile(one_pri, 3)
        phase_cmd = TWOPI * np.cumsum(train) / fref
        for _ in range(cfg.lo.dp_cal_iterations):
            pm = self._modulator(dp_gain, "response")
            if mode == "response":
                out = pm.modulate(phase_cmd, fref, noise=False, seed=0).phase_out
            else:
                f_err, _ = self._simulate(train, dp_gain, False, 0)
                out = phase_cmd + TWOPI * np.cumsum(f_err) / fref
            est = offline_dp_gain(pm, phase_cmd[n_pri:], out[n_pri:], fref)
            est["dp_gain_before"] = dp_gain
            dp_gain = est["dp_gain_next"]
            passes.append(est)
        return dp_gain, passes

    def _event(self, f_cmd, nc, n_ramp, n_idle, noise, seed, ui99) -> ChirpResult:
        cfg = self.cfg
        dp_gain, passes = self._calibrate_offline(f_cmd[:n_ramp + n_idle], "event")
        cal = ChirpSignSignCal(dp_gain, cfg.lo.dp_cal_mu) if cfg.lo.dp_cal == "online" else None
        f_err, sim = self._simulate(f_cmd, dp_gain, noise, seed, cal)
        trace = None
        if cal is not None:
            settle = cfg.lo.settle_cycles
            trace = np.asarray(sim.cal_traces["dp_gain"])[settle:settle + f_cmd.size]
            dp_gain = float(trace[-1])
        return ChirpResult("event", cfg.lo.fref_hz, nc, n_ramp, n_idle, cfg.lo_mult, f_cmd, f_err, dp_gain,
                           dp_cal_trace=trace, dp_cal_passes=passes, ui_per_ref_cycle_p99=ui99,
                           vouches_for_spurs=True, note="cycle-accurate engine (loop, TDC, DCO quantisation)")


__all__ = ["ChirpEngine", "ChirpResult", "command_train", "quadratic_reference", "ui_per_ref_cycle_p99"]

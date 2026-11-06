"""Two-point gain calibration on a sawtooth chirp: the chirp linearity calibration.

A direct-path gain mismatch ``eps`` leaves ``eps x highpass(phase)`` on the
modulator output (polar_tx); on a frequency ramp the highpass of a parabola
is a *constant* phase lag in steady state -- unobservable -- and all the
information about ``eps`` sits in the flyback transient, where the DCO is
pushed by ``(1 + eps) B/N`` and the loop sees ``eps B/N`` to settle out.

Two calibrators, both running on the vendored engines without touching them:

* :func:`offline_dp_gain` -- polar_tx's least-squares estimator
  (``cal/twopoint.estimate_dp_gain_error``) run on one simulated chirp:
  the phase error correlated against the loop's exact highpass of the
  command, dividing ``dp_gain`` by ``1 + eps_hat``; one pass takes a 5 %
  mismatch to ~0.5 % on the event engine (cairn/chirp-engine.md), two
  passes to the quantisation floor.  The default (``lo.dp_cal: offline``).
* :class:`ChirpSignSignCal` -- an online sign-sign LMS with polar_tx's
  ``dp_cal`` contract (``.step(err, reg)`` per reference cycle, ``.value``
  read by the engine).  The vendored ``SignSignLMS`` correlates the phase
  error with the EMA-centred modulation; on a sawtooth the centred ramp's
  sign and the error's sign are uncorrelated and it walks the wrong way
  (1.05 -> 1.066 in 20 chirps, measured).  This one correlates the
  *differences*: the per-cycle frequency error against the per-cycle
  frequency step, which have the sign relation ``d(err) = -eps d(mod)
  T_ref`` at every step, flyback included.  It converges, slowly (1.05 ->
  1.006 in 20 chirps at mu = 1e-4); ROADMAP lists the gear shift.
"""

from __future__ import annotations

import numpy as np


class ChirpSignSignCal:
    """value += mu sign(d err) sign(d mod), one update per reference cycle."""

    def __init__(self, init: float, mu: float):
        self.value = float(init)
        self.mu = float(mu)
        self.trace: list[float] = []
        self._err = None
        self._reg = None

    def step(self, err: float, reg: float) -> float:
        if self._err is not None:
            de, dr = err - self._err, reg - self._reg
            if dr != 0.0 and de != 0.0:
                # the DCO runs fast on a positive step (err falling) when the gain is high
                self.value += self.mu * float(np.sign(de)) * float(np.sign(dr))
        self._err, self._reg = float(err), float(reg)
        self.trace.append(self.value)
        return self.value


def offline_dp_gain(pm, phase_cmd: np.ndarray, phase_out: np.ndarray, fs: float) -> dict:
    """One least-squares pass of polar_tx's estimator: the corrected direct-path
    gain ``pm.dp_gain / (1 + eps_hat)`` and the estimate itself."""
    from ..vendor.polartx.cal import estimate_dp_gain_error

    est = estimate_dp_gain_error(pm, phase_cmd, phase_out, fs)
    return {"eps_hat": float(est["eps_hat"]), "dp_gain_corr": float(est["dp_gain_corr"]),
            "dp_gain_next": float(pm.dp_gain * est["dp_gain_corr"])}


__all__ = ["ChirpSignSignCal", "offline_dp_gain"]

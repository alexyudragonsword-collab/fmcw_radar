"""Two-point gain calibration on a sawtooth chirp: the chirp linearity calibration.

A direct-path gain mismatch ``eps`` leaves ``eps x highpass(phase)`` on the
modulator output (polar_tx); on a frequency ramp the highpass of a parabola
is a *constant* phase lag in steady state -- unobservable -- and all the
information about ``eps`` sits in the flyback transient, where the DCO is
pushed by ``(1 + eps) B/N`` and the loop sees ``eps B/N`` to settle out.
Measured on the default loop (cairn/chirp-engine.md): the per-cycle phase
error difference carries ``+0.47 UI`` of mismatch signal on the first cycle
after a 5 % flyback, decaying to the quantisation floor (0.03 UI RMS) by
cycle ~25; cycles 50-200 are the loop's overshoot with the opposite sign;
beyond that the ramp carries nothing.

Two calibrators, both running on the vendored engines without touching them:

* :func:`offline_dp_gain` -- polar_tx's least-squares estimator
  (``cal/twopoint.estimate_dp_gain_error``) run on simulated chirps: the
  phase error correlated against the loop's exact highpass of the command,
  dividing ``dp_gain`` by ``1 + eps_hat``; one pass takes a 5 % mismatch to
  1e-4 on the event engine.  The default (``lo.dp_cal: offline``).
* :class:`ChirpFlybackLMS` -- an online LMS with polar_tx's ``dp_cal``
  contract.  Since polar_tx b007e60 that is a step kernel run inside the
  ADPLL's per-cycle loop (``kernel_view`` hands over ``flyback_dp_step``
  and its state, ``kernel_done`` takes the state and the trace back); the
  object's own ``.step(err, reg)`` calls the same kernel, so there is one
  update rule.  It updates only in a window of ``window_cycles`` after each
  flyback (a regressor step larger than ``step_threshold``), by the
  magnitude of the phase-error difference times the flyback's sign.  The
  vendored ``SignSignLMS`` walks the wrong way on a sawtooth (1.05 ->
  1.066 in 20 chirps: the EMA-centred ramp is uncorrelated with the
  steady-state error), a sign-sign rule over every cycle converges slowly
  (1.05 -> 1.006 in 20 chirps: 20 informative cycles against 10 000 of
  quantisation noise), and a sign-sign rule inside the window settles 0.5 %
  low (the TDC sawtooth's sign asymmetry).  This one, magnitude-weighted,
  takes 1.05 or 0.96 to within 0.05 % of 1 in four chirps at mu = 1e-2
  with the loop's noise on, from either side, with no bias.
"""

from __future__ import annotations

import numpy as np

from ..vendor.polartx.vendor.pllsim.core.jit import kernel


@kernel
def flyback_dp_step(st: np.ndarray, pr: np.ndarray, err: float, reg: float,
                    rec: np.ndarray, n: int) -> float:
    """:class:`ChirpFlybackLMS` as the ADPLL kernel's dp_cal step.  ``st`` is
    (value, previous err, previous reg, cycles left in the window, flyback
    sign, seen a cycle, flybacks); ``pr`` is (mu, window_cycles, step_threshold)."""
    if st[5] != 0.0:
        de = err - st[1]
        dr = reg - st[2]
        if abs(dr) > pr[2]:
            st[3] = pr[1]
            st[4] = 1.0 if dr > 0.0 else -1.0
            st[6] += 1.0
        elif st[3] > 0.0:
            # the gain too high: the DCO undershoots a negative step and the
            # phase error (reference minus DCO) rises -- de > 0, sign < 0
            st[0] += pr[0] * de * st[4]
            st[3] -= 1.0
    st[1] = err
    st[2] = reg
    st[5] = 1.0
    rec[n, 0] = st[0]
    return st[0]


class ChirpFlybackLMS:
    """value += mu x d(err) x sign(flyback step), on the ``window_cycles`` after each flyback."""

    def __init__(self, init: float, mu: float, window_cycles: int, step_threshold: float):
        self.mu = float(mu)
        self.window_cycles = int(window_cycles)
        self.step_threshold = float(step_threshold)
        self.trace: list[float] = []
        self._st = np.array([float(init), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self._pr = np.array([self.mu, float(self.window_cycles), self.step_threshold])
        self._rec = np.empty((1, 1))

    @property
    def value(self) -> float:
        return float(self._st[0])

    @property
    def flybacks(self) -> int:
        return int(self._st[6])

    def step(self, err: float, reg: float) -> float:
        v = float(flyback_dp_step(self._st, self._pr, float(err), float(reg), self._rec, 0))
        self.trace.append(v)
        return v

    def kernel_view(self, n_cycles: int):
        """(step, state, params, record) for the ADPLL kernel: one value per cycle in the record."""
        return flyback_dp_step, self._st, self._pr, np.empty((n_cycles, 1))

    def kernel_done(self, st: np.ndarray, rec: np.ndarray, n_steps: int) -> None:
        """Take the state and the per-cycle values back after a run."""
        self._st = st
        self.trace.extend(rec[:n_steps, 0].tolist())


def offline_dp_gain(pm, phase_cmd: np.ndarray, phase_out: np.ndarray, fs: float) -> dict:
    """One least-squares pass of polar_tx's estimator: the corrected direct-path
    gain ``pm.dp_gain / (1 + eps_hat)`` and the estimate itself."""
    from ..vendor.polartx.cal import estimate_dp_gain_error

    est = estimate_dp_gain_error(pm, phase_cmd, phase_out, fs)
    return {"eps_hat": float(est["eps_hat"]), "dp_gain_corr": float(est["dp_gain_corr"]),
            "dp_gain_next": float(pm.dp_gain * est["dp_gain_corr"])}


__all__ = ["ChirpFlybackLMS", "offline_dp_gain"]

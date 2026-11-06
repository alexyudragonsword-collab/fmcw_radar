"""Invariant #4: the chirp's frequency error comes from the vendored ADPLL loop, not from an assumed term.

Acceptance: the curve has numbers (peak, RMS, settling time); a two-point
mismatch eps leaves eps x B/N at the flyback and the loop settles it; the
cycle-accurate and the linearised engines agree on that transient; the
offline calibration takes the mismatch out; the online one moves the right
way; the ideal engine has no error; the quadratic is a reference, not an engine.
"""

import numpy as np
import pytest

from fmcw_radar.chirp import ChirpEngine, ChirpSignSignCal, command_train, quadratic_reference, ui_per_ref_cycle_p99
from fmcw_radar.config import RadarConfig, apply_overrides


def _cfg(**ov):
    return apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, **ov})


def test_command_train_is_a_sawtooth_of_b_over_n(cfg60):
    f, n_ramp, n_idle = command_train(cfg60)
    assert n_ramp == cfg60.n_ref_cycles and n_idle == 0 and f.size == 64 * n_ramp
    assert f[0] == pytest.approx(-0.5e9) and f[n_ramp - 1] == pytest.approx(0.5e9 - 1e9 / n_ramp)
    assert f[n_ramp] == pytest.approx(-0.5e9)                      # flyback
    c = apply_overrides(cfg60, {"chirp.idle_s": 10e-6})
    f2, _, n_idle2 = command_train(c)
    assert n_idle2 == 1000 and np.all(f2[n_ramp:n_ramp + 1000] == -0.5e9)


def test_validity_metric_is_measured_and_far_outside_polar_tx_domain(cfg60):
    """polar_tx's event domain is < 10 % UI per reference cycle; a 1 GHz ramp
    at 100 MHz fref reads 495 % -- measured, reported, and not what decides
    (see the engine docstring and cairn/chirp-engine.md)."""
    f, _, _ = command_train(cfg60)
    assert ui_per_ref_cycle_p99(f, cfg60.lo.fref_hz) == pytest.approx(4.95, abs=0.01)
    r = ChirpEngine(_cfg(**{"lo.engine": "ideal"})).run()
    assert r.ui_per_ref_cycle_p99 == pytest.approx(4.95, abs=0.01)


def test_ideal_engine_has_no_error():
    r = ChirpEngine(_cfg(**{"lo.engine": "ideal"})).run()
    assert r.engine == "ideal" and np.all(r.f_err_dco_hz == 0.0) and not r.vouches_for_spurs


def test_mismatch_leaves_eps_times_the_step_and_the_loop_settles_it():
    eps = 0.05
    r = ChirpEngine(_cfg(**{"lo.dp_gain": 1 + eps, "lo.dp_cal": "none"})).run()
    assert r.engine == "event" and r.vouches_for_spurs
    e = r.ramp_carrier(2)
    step = eps * 4e9                                     # eps x B at the carrier
    assert abs(e[0]) == pytest.approx(step, rel=0.01)
    m = r.metrics(2)
    assert m["initial_error_hz"] == pytest.approx(step, rel=0.01)
    assert 0.3e-6 < m["settle_s"] < 3e-6                 # a 1 MHz loop settles in microseconds
    assert m["peak_hz"] == pytest.approx(step, rel=0.01)
    assert np.abs(e[-2000:]).max() < 0.05 * step         # gone by the end of the ramp
    # the error is the loop's: halving eps halves the transient
    r2 = ChirpEngine(_cfg(**{"lo.dp_gain": 1 + eps / 2, "lo.dp_cal": "none"})).run()
    assert r2.ramp_carrier(2)[0] == pytest.approx(e[0] / 2, rel=0.02)


def test_event_and_response_engines_agree_on_the_transient():
    """Cycle by cycle on the first 40 cycles after the flyback (5 % mismatch):
    the quantisation floor apart, the two engines are one loop."""
    ce = ChirpEngine(_cfg(**{"lo.dp_gain": 1.05, "lo.dp_cal": "none"})).run().ramp_carrier(2)
    cr = ChirpEngine(_cfg(**{"lo.dp_gain": 1.05, "lo.dp_cal": "none", "lo.engine": "response"})).run().ramp_carrier(2)
    k = np.arange(0, 40)
    assert np.allclose(ce[k], cr[k], rtol=0.03, atol=1.5e6)
    assert np.std(ce[-2000:]) > 1e5 and np.std(cr[-2000:]) < 1.0      # event: TDC / DCO quantisation; response: none


def test_matched_loop_error_is_the_quantisation_floor():
    """With matched gains the only error is TDC and DCO quantisation through
    the loop: ~0.5 MHz RMS at the carrier for a 5 ps TDC on a 15 GHz DCO x4,
    and it does not depend on the ramp (same on every ramp)."""
    r = ChirpEngine(_cfg(**{"lo.dp_cal": "none"})).run()
    rms = [np.std(r.ramp_carrier(k)) for k in (1, 2)]
    assert 0.2e6 < rms[0] < 1.5e6 and rms[1] == pytest.approx(rms[0], rel=0.2)
    assert abs(r.metrics(2)["mean_hz"]) < 5e4
    # finer TDC -> smaller floor
    fine = ChirpEngine(_cfg(**{"lo.dp_cal": "none", "lo.tdc_res_s": 1e-12})).run()
    assert np.std(fine.ramp_carrier(2)) < 0.5 * rms[0]


def test_offline_calibration_removes_the_mismatch():
    r = ChirpEngine(_cfg(**{"lo.dp_gain": 1.05, "lo.dp_cal": "offline", "lo.dp_cal_iterations": 2})).run()
    eps = [p["eps_hat"] for p in r.dp_cal_passes]
    assert eps[0] == pytest.approx(0.05, rel=0.05) and abs(eps[1]) < 0.002
    assert r.dp_gain_used == pytest.approx(1.0, abs=0.002)
    assert r.metrics(2)["initial_error_hz"] < 0.01 * 0.05 * 4e9
    # the response engine's estimator is exact to the linear model
    rr = ChirpEngine(_cfg(**{"lo.dp_gain": 1.05, "lo.dp_cal": "offline", "lo.engine": "response"})).run()
    assert rr.dp_cal_passes[0]["eps_hat"] == pytest.approx(0.05, rel=0.01)


def test_online_calibration_moves_the_right_way_from_both_sides():
    for g in (1.05, 0.96):
        r = ChirpEngine(_cfg(**{"lo.dp_gain": g, "lo.dp_cal": "online", "lo.dp_cal_mu": 1e-4, "chirp.n_chirps": 6})).run()
        assert r.dp_cal_trace is not None and r.dp_cal_trace.size == 6 * r.n_ramp
        assert abs(r.dp_gain_used - 1.0) < abs(g - 1.0)


def test_sign_sign_cal_contract():
    cal = ChirpSignSignCal(1.0, 1e-3)
    cal.step(0.0, 0.0)
    cal.step(-1.0, 1.0)      # error falls on a positive step: the gain is high
    assert cal.value == pytest.approx(1.0 - 1e-3) and len(cal.trace) == 2
    cal.step(-1.0, 1.0)      # no change in either: no update
    assert cal.value == pytest.approx(1.0 - 1e-3)


def test_quadratic_reference_is_labelled_and_scaled():
    q = quadratic_reference(RadarConfig(), 1e5, 2)
    assert q.engine == "quadratic" and not q.vouches_for_spurs and "reference" in q.note
    assert np.std(q.ramp(1)) == pytest.approx(1e5, rel=1e-9) and abs(np.mean(q.ramp(1))) < 1e-3


def test_carrier_phase_is_the_integral_of_the_error_times_n():
    r = ChirpEngine(_cfg(**{"lo.dp_gain": 1.02, "lo.dp_cal": "none"})).run()
    phi = r.phase_err_carrier_rad()
    assert phi.size == r.f_err_dco_hz.size
    assert phi[10] == pytest.approx(2 * np.pi * 4 * np.sum(r.f_err_dco_hz[:11]) / r.fref_hz)

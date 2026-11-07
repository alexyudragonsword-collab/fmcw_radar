"""Milestone 2: the TDM-MIMO virtual array and the angle estimate.

Acceptance: 1 TX x 1 RX is milestone 1 (no angle, same frames); the virtual
positions are the sum of the two arrays' and a filled line at the default
TX pitch; the DBF estimate reads the configured angle on the ideal
snapshot; the TDM Doppler phase biases it uncompensated and not compensated;
the coupling biases it uncalibrated and not calibrated; the CRLB and the
beamwidth follow the aperture; the time engine's error sits at the bound.
"""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.mimo import VirtualArray


def _mimo(**ov):
    return apply_overrides(RadarConfig(), {"mimo.n_tx": 2, "mimo.n_rx": 4, "target.angle_deg": 20.0, "chirp.n_chirps": 8, **ov})


def test_single_channel_has_no_angle_and_is_milestone_one(cfg60):
    st = run_statistical(apply_overrides(cfg60, {"chirp.n_chirps": 3}))
    assert st.angle == {} and len(st.targets) == 1
    tm = run_time(apply_overrides(cfg60, {"chirp.n_chirps": 2}))
    assert tm.frame.ndim == 2 and "angle_deg" not in tm.extras


def test_virtual_positions_are_the_sum_and_a_filled_line():
    va = VirtualArray(_mimo())
    d = va.rx.spacing_m
    assert va.n == 8 and va.filled
    assert np.allclose(np.diff(va.x_v), d)
    assert abs(va.x_v.mean()) < 1e-15 and va.aperture_m == pytest.approx(8 * d)
    sparse = VirtualArray(_mimo(**{"mimo.tx_spacing_lambda": 1.0}))
    assert not sparse.filled and sparse.n == 8 and len(set(np.round(sparse.x_v, 9))) == 6   # overlapping elements


def test_dbf_reads_the_configured_angle_on_the_ideal_snapshot():
    for th in (-40.0, 0.0, 20.0, 55.0):
        cfg = _mimo(**{"target.angle_deg": th, "target.velocity_mps": 0.0})
        va = VirtualArray(cfg)
        est = va.estimate(va.snapshot(th), 0.0)
        assert est["theta_deg"] == pytest.approx(th, abs=0.05)
        assert est["peak_sidelobe_db"] < -30.0                      # Hann across 8 elements


def test_tdm_doppler_phase_biases_the_estimate_unless_compensated():
    cfg = _mimo()
    va = VirtualArray(cfg)
    fd = cfg.doppler_hz()
    assert abs(va.tdm_bias_deg(20.0, fd)) > 1.0
    est = va.estimate(va.snapshot(20.0, fd), fd)
    assert est["theta_deg"] == pytest.approx(20.0, abs=0.05)
    assert cfg.max_velocity_mps == pytest.approx(RadarConfig().max_velocity_mps / 2)   # TDM halves it


def test_coupling_biases_the_estimate_and_calibration_removes_it():
    for src in ("analytic", "survey"):
        cfg = _mimo(**{"mimo.coupling.source": src})
        va = VirtualArray(cfg)
        assert va.coupling is not None and va.coupling.max_offdiag_db() == pytest.approx(-16.0)
        assert 0.05 < abs(va.coupling_bias_deg(20.0)) < 2.0
        cal = VirtualArray(apply_overrides(cfg, {"mimo.coupling.calibrated": True}))
        assert abs(cal.coupling_bias_deg(20.0)) < 0.01
    assert VirtualArray(_mimo()).coupling_bias_deg(20.0) == 0.0


def test_touchstone_coupling_reads_back_the_analytic_matrix(tmp_path):
    from fmcw_radar.vendor.arraytx.coupling import write_matrix_touchstone

    cfg = _mimo(**{"mimo.coupling.source": "analytic"})
    va = VirtualArray(cfg)
    path = tmp_path / "rx4.s4p"
    write_matrix_touchstone(str(path), va.coupling)
    ts = VirtualArray(apply_overrides(cfg, {"mimo.coupling.source": "touchstone", "mimo.coupling.touchstone": str(path)}))
    assert np.allclose(ts.c_rx, va.c_rx)
    with pytest.raises(ValueError, match="ports"):
        VirtualArray(apply_overrides(cfg, {"mimo.coupling.source": "touchstone", "mimo.coupling.touchstone": str(path),
                                           "mimo.n_rx": 3, "chirp.n_chirps": 8}))


def test_beamwidth_and_crlb_follow_the_aperture():
    a = VirtualArray(_mimo())
    b = VirtualArray(_mimo(**{"mimo.n_rx": 8}))                     # twice the aperture
    assert a.beamwidth_deg(0.0) == pytest.approx(math.degrees(0.886 * a.wavelength_m / a.aperture_m), rel=0.05)
    assert a.beamwidth_deg(0.0) / b.beamwidth_deg(0.0) == pytest.approx(2.0, rel=0.1)
    # CRLB: 1 / sqrt(SNR), and N(N^2-1) with the element count
    assert a.crlb_sigma_deg(20.0, 0.0) / a.crlb_sigma_deg(30.0, 0.0) == pytest.approx(math.sqrt(10.0), rel=1e-6)
    assert a.crlb_sigma_deg(20.0, 0.0) / b.crlb_sigma_deg(20.0, 0.0) == pytest.approx(math.sqrt(16 * 255 / (8 * 63)), rel=1e-6)
    assert a.crlb_sigma_deg(20.0, 60.0) == pytest.approx(a.crlb_sigma_deg(20.0, 0.0) / math.cos(math.radians(60.0)), rel=1e-6)


def test_sweep_squint_numbers():
    sq = VirtualArray(_mimo()).sweep_squint(30.0)
    # a 60 GHz beam over +-2 GHz squints ten times FR2's +-200 MHz at 28 GHz
    assert abs(sq["tx_beam_squint_deg"][1]) / abs(sq["fr2_400mhz_squint_deg"][1]) == pytest.approx(4.0 / 28 * 60 / 2, rel=0.3)
    assert sq["edge_shift_bins"] < 0.1 and sq["edge_taper_db"] > -0.1


def test_time_engine_angle_error_sits_at_the_bound():
    cfg = _mimo(**{"chirp.n_chirps": 8})
    bound = run_statistical(cfg).angle["crlb_sigma_deg"]
    errs = [run_time(cfg, seed=s).extras["angle_deg"] - 20.0 for s in (1, 2, 3)]
    assert np.sqrt(np.mean(np.square(errs))) < 3.0 * bound + 0.02
    off = run_time(apply_overrides(cfg, {"mimo.tdm_doppler_compensation": False}), seed=1).extras["angle_deg"] - 20.0
    assert abs(off) > 1.0                                             # the Doppler phase, uncompensated


def test_mimo_cube_shape_and_snr_per_tx():
    cfg = _mimo()
    tm = run_time(cfg)
    assert tm.frame.shape == (8, 4, cfg.n_samples) and tm.extras["n_virtual"] == 8
    st = run_statistical(cfg)
    assert st.extras["snr_cell_per_tx_db"] == pytest.approx(st.snr_cell_db - 10 * math.log10(2))
    assert tm.peak_range_m == pytest.approx(5.0, abs=cfg.range_resolution_m)


def test_config_refuses_a_frame_that_does_not_split_into_tdm_blocks():
    with pytest.raises(ValueError, match="multiple of mimo.n_tx"):
        apply_overrides(RadarConfig(), {"mimo.n_tx": 3, "chirp.n_chirps": 64})
    with pytest.raises(ValueError, match="whole number of RX pitches"):
        apply_overrides(RadarConfig(), {"mimo.n_rx": 4, "mimo.tx_spacing_lambda": 0.7})

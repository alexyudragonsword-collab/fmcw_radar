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


def _snapshot_mc(cfg, snr_chirp_db: float, trials: int, seed: int = 0) -> float:
    """RMS angle error [deg] of the engine's own estimator on synthetic
    range-bin samples: per-TX Doppler FFT, the peak bin, ``doppler_fine_hz``,
    ``VirtualArray.estimate`` -- everything the time engine does after the
    range FFT, with white noise at ``snr_chirp_db`` per sample."""
    from fmcw_radar.engine.timedomain import doppler_fine_hz
    from fmcw_radar.processing.rd import doppler_fft

    va = VirtualArray(cfg)
    n_tx, n_rx, p = cfg.mimo.n_tx, cfg.mimo.n_rx, cfg.processing
    m_tx = cfg.chirp.n_chirps // n_tx
    th, fd, t_tx = cfg.target.angle_deg, cfg.doppler_hz(), cfg.chirp.pri_s * n_tx
    rng = np.random.default_rng(seed)
    z0 = (va.snapshot(th, fd).reshape(n_tx, n_rx)[:, None, :]
          * np.exp(2j * np.pi * fd * t_tx * np.arange(m_tx))[None, :, None])           # (n_tx, m_tx, n_rx)
    sig = 10.0 ** (-snr_chirp_db / 20.0) / math.sqrt(2.0)
    fgrid = np.fft.fftshift(np.fft.fftfreq(m_tx * p.doppler_pad, d=t_tx))
    errs = []
    for _ in range(trials):
        z = z0 + sig * (rng.standard_normal(z0.shape) + 1j * rng.standard_normal(z0.shape))
        maps = np.stack([doppler_fft(z[i], p.window_doppler, p.doppler_pad) for i in range(n_tx)])
        i_pk = int(np.argmax(np.sum(np.abs(maps) ** 2, axis=(0, 2))))
        f_hat = doppler_fine_hz(z, t_tx, float(fgrid[i_pk]))
        errs.append(va.estimate(maps[:, i_pk, :].ravel(), f_hat)["theta_deg"] - th)
    return float(np.sqrt(np.mean(np.square(errs))))


def test_error_budget_factors_are_the_closed_forms():
    """Uniform weights on the Doppler bin with a known Doppler is the bound;
    the Hann taper across 8 elements costs sum w^2 x^2 sum x^2 / (sum w x^2)^2
    in variance; half a Doppler bin off costs the window's scalloping; an
    isotropic element costs nothing and a cos one 1 / cos(theta)."""
    from fmcw_radar.processing.windows import coherent_gain_db, window

    cfg = _mimo(**{"target.velocity_mps": 0.0})
    va = VirtualArray(cfg)
    b = va.angle_error_budget(35.0, 20.0, 0.0)
    cg = coherent_gain_db(window("hann", 4))                                   # 4 chirps per TX
    assert b["sigma_crlb_deg"] == pytest.approx(va.crlb_sigma_deg(35.0 + cg, 20.0), rel=1e-9)
    assert b["factor_element_pattern"] == 1.0 and b["factor_scalloping"] == pytest.approx(1.0, abs=1e-12)
    w = window("hann", 8)
    x = np.arange(8) - 3.5
    xw = np.sum(w * x) / np.sum(w)
    f_w = np.sum(w ** 2 * (x - xw) ** 2) * np.sum(x ** 2) / np.sum(w * (x - xw) ** 2) ** 2
    assert b["factor_angle_window"] == pytest.approx(math.sqrt(f_w), rel=1e-9) and 1.5 < b["factor_angle_window"] < 1.55
    assert 1.0 < b["factor_doppler_estimate"] < 1.03                          # the pulse-pair estimate: a percent
    assert b["sigma_expected_deg"] == pytest.approx(b["sigma_crlb_deg"] * b["factor_angle_window"] * b["factor_doppler_estimate"], rel=1e-9)
    rect = VirtualArray(_mimo(**{"mimo.angle_window": "rect", "target.velocity_mps": 0.0})).angle_error_budget(35.0, 20.0, 0.0)
    assert rect["factor_angle_window"] == pytest.approx(1.0, abs=1e-12)
    moving = VirtualArray(_mimo()).angle_error_budget(35.0, 20.0, _mimo().doppler_hz())
    d = window("hann", 4) / window("hann", 4).sum()
    off = moving["doppler_bin_offset"]
    scal = abs(np.sum(d * np.exp(2j * np.pi * off * np.arange(4) / 4)))
    assert moving["factor_scalloping"] == pytest.approx(1.0 / scal, rel=1e-9) and abs(off) == pytest.approx(0.36, abs=0.01)
    cos = VirtualArray(_mimo(**{"mimo.element_pattern": "cos"})).angle_error_budget(35.0, 20.0, 0.0)
    assert cos["factor_element_pattern"] == pytest.approx(1.0 / math.cos(math.radians(20.0)), rel=1e-9)
    assert VirtualArray(_mimo(**{"mimo.tdm_doppler_compensation": False})).angle_error_budget(35.0, 20.0, 0.0)["factor_doppler_estimate"] == 1.0
    assert VirtualArray(RadarConfig()).angle_error_budget(35.0, 0.0) == {}


@pytest.mark.parametrize("ov", [
    {},                                                                        # Hann, 2 m/s: 0.36 Doppler bins off
    {"mimo.angle_window": "rect", "mimo.element_pattern": "cos"},
    {"mimo.n_tx": 3, "chirp.n_chirps": 12, "target.angle_deg": -40.0, "mimo.angle_window": "blackman", "target.velocity_mps": -3.0},
], ids=["hann", "rect-cos", "3x4-blackman"])
def test_error_budget_is_what_the_estimator_scatters_by(ov):
    """The closed form against the estimator itself on 2000 noisy snapshots:
    within 6 % (the RMS of 2000 trials is good to 1.6 %)."""
    cfg = _mimo(**ov)
    b = VirtualArray(cfg).angle_error_budget(35.0, cfg.target.angle_deg, cfg.doppler_hz())
    assert _snapshot_mc(cfg, 35.0, 2000) == pytest.approx(b["sigma_expected_deg"], rel=0.06)


def test_statistical_engine_carries_the_error_budget():
    cfg = _mimo()
    st = run_statistical(cfg)
    a = st.angle
    assert a["sigma_crlb_deg"] == pytest.approx(a["crlb_sigma_deg"], rel=1e-9)   # the same bound, two derivations
    assert a["sigma_expected_deg"] == pytest.approx(a["crlb_sigma_deg"] * a["factor_element_pattern"] * a["factor_scalloping"]
                                                    * a["factor_angle_window"] * a["factor_doppler_estimate"], rel=1e-9)
    assert a["sigma_expected_deg"] / a["crlb_sigma_deg"] == pytest.approx(1.67, abs=0.03)     # not at the bound: the Hann taper
    assert a["snr_element_cell_db"] < a["snr_element_db"]


def test_time_engine_angle_error_is_the_estimators_expected_scatter():
    """Three seeds only say 'the right order': their RMS within 2.5x the
    expected sigma (a 3-sample RMS exceeds that 3 times in 10^4) and not a
    bias -- the 128-seed comparison is example 07's and the LOG's."""
    cfg = _mimo(**{"chirp.n_chirps": 8})
    expected = run_statistical(cfg).angle["sigma_expected_deg"]
    errs = [run_time(cfg, seed=s).extras["angle_deg"] - 20.0 for s in (1, 2, 3)]
    assert np.sqrt(np.mean(np.square(errs))) < 2.5 * expected
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


# ---------------------------------------------------------------- 0.2.30: what the coupling does to the echo's power on an element

def _clean_mimo(**ov):
    from fmcw_radar.config import load_config
    from conftest import REPO

    return apply_overrides(load_config(REPO / "configs" / "radar_60g_mimo.yaml"),
                           {"leakage.enabled": False, "extra_targets": [], "lo.engine": "response", **ov})


def test_the_coupling_changes_the_echos_power_on_an_element_with_its_direction():
    """``received_k = a_k + sum_j S_kj a_j``: with the neighbours in
    anti-phase (the placeholder's 180 degrees) a broadside wave arrives
    3.3 dB weaker on an element and a wave from 40 degrees 1.3 dB stronger.
    The statistical engine's SNR of one look of the map carries it; without
    coupling the factor is exactly one."""
    from fmcw_radar.mimo import VirtualArray

    va = VirtualArray(_clean_mimo())
    assert VirtualArray(_clean_mimo(**{"mimo.coupling.source": "none"})).coupling_power(17.0) == 1.0
    got = {th: 10.0 * math.log10(va.coupling_power(th)) for th in (0.0, 10.0, 20.0, 40.0)}
    assert got[0.0] == pytest.approx(-3.26, abs=0.02) and got[20.0] == pytest.approx(-0.51, abs=0.02) and got[40.0] == pytest.approx(1.25, abs=0.02)
    assert got[0.0] < got[10.0] < got[20.0] < got[40.0]
    # it is the mean over the elements of |(I + S_offdiag) a|^2, a the plane wave on the receive elements
    a = np.exp(2j * np.pi * va.f0_hz * va.rx.x_m * math.sin(math.radians(10.0)) / 299_792_458.0)
    assert va.coupling_power(10.0) == pytest.approx(float(np.mean(np.abs(va.c_rx @ a) ** 2)), rel=1e-12)
    st = run_statistical(_clean_mimo(**{"target.angle_deg": 0.0}))
    g = st.angle
    assert g["coupling_power_db"] == pytest.approx(got[0.0], abs=1e-9)
    assert g["snr_look_db"] == pytest.approx(g["snr_element_cell_db"] + g["coupling_power_db"], abs=1e-12)
    assert st.cfar["snr_look_db"] == g["snr_look_db"]                           # the map's CFAR sees the looks as they are


@pytest.mark.parametrize("angle_deg", [0.0, 20.0, 40.0])
def test_both_engines_agree_on_the_snr_of_one_look_under_coupling(angle_deg):
    """Until 0.2.30 they parted by -3.6 dB at broadside and +0.9 dB at 40
    degrees: the statistical engine did not have the coupling's effect on
    the echo, and the time engine put the receivers' noise through the
    coupling matrix as well."""
    c = _clean_mimo(**{"target.angle_deg": angle_deg})
    t, s = run_time(c), run_statistical(c)
    assert t.extras["peak_is_target"] is True
    assert t.snr_cell_local_db == pytest.approx(s.angle["snr_look_db"], abs=0.5)
    assert abs(s.angle["coupling_power_db"]) > 0.4                              # and the coupling is not a small thing here


def test_the_receivers_noise_does_not_go_through_the_coupling():
    """Each receiver's noise is its own: it enters after the antenna.  With
    no echo to speak of, neighbouring channels of the cube are uncorrelated
    -- through the matrix (-16 dB neighbours in anti-phase) they would be
    correlated by about -0.3."""
    c = _clean_mimo(**{"target.rcs_dbsm": -150.0, "chirp.n_chirps": 4})
    cube = run_time(c, phase_noise=False).frame                                 # (chirps, rx, samples)
    x = cube.reshape(cube.shape[0], cube.shape[1], -1)
    rho = [abs(np.vdot(x[:, k], x[:, k + 1]) / math.sqrt(np.vdot(x[:, k], x[:, k]).real * np.vdot(x[:, k + 1], x[:, k + 1]).real))
           for k in range(x.shape[1] - 1)]
    assert max(rho) < 0.05

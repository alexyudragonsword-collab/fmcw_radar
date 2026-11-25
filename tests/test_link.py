"""The radar equation and the noise at the ADC: scaling laws, not snapshots."""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar import report as rpt
from fmcw_radar.config import load_config
from fmcw_radar.link import adc_amplitudes, compliance_check, detection_range_m, link_budget, snr_vs_range
from fmcw_radar.processing.detection import snr_for_pd


def test_r_to_the_fourth():
    a, b = link_budget(RadarConfig(), 5.0), link_budget(RadarConfig(), 10.0)
    alpha, _ = RadarConfig().oxygen_db_per_km()
    assert alpha == 14.651
    assert a.pr_dbm - b.pr_dbm == pytest.approx(40 * math.log10(2) + alpha * 2 * 5 / 1000, abs=1e-9)
    assert a.snr_cell_db - b.snr_cell_db == pytest.approx(a.pr_dbm - b.pr_dbm, abs=1e-9)


def test_eirp_rcs_and_losses_are_linear_in_db():
    base = link_budget(RadarConfig())
    pt = base.inputs["tx_power_dbm"][0]
    up = link_budget(apply_overrides(RadarConfig(), {"frontend.tx_power_dbm": pt + 3.0, "target.rcs_dbsm": -7.0,
                                                     "channel.extra_loss_db": 2.0}))
    assert up.pr_dbm - base.pr_dbm == pytest.approx(3.0 + 3.0 - 2.0, abs=1e-9)
    assert up.inputs["tx_power_dbm"] == (pt + 3.0, "config") and base.inputs["tx_power_dbm"] == (12.0, "spec")
    assert base.inputs["tx_gain_dbi"][1] == "assumed"                              # the antennas are still placeholders


def test_free_space_term_is_the_textbook_one():
    b = link_budget(RadarConfig(), 1.0)
    lam = RadarConfig().band.wavelength_m
    assert b.path_loss_db == pytest.approx(10 * math.log10((4 * math.pi) ** 3 / lam ** 2), abs=1e-9)


def test_noise_figure_moves_the_floor_one_for_one():
    a = link_budget(RadarConfig())
    nf = a.inputs["nf_db"][0]
    b = link_budget(apply_overrides(RadarConfig(), {"frontend.nf_db": nf + 3.0}))
    assert b.n0_thermal_dbm_hz - a.n0_thermal_dbm_hz == pytest.approx(3.0, abs=1e-9)
    assert a.n0_thermal_dbm_hz == pytest.approx(10 * math.log10(1.380649e-23 * 290) + 30 + nf, abs=1e-9)
    # the echo is in band: its margin is to the in-band compression point at this gain
    assert a.p1db_margin_db == pytest.approx(a.inputs["p1db_inband_dbm"][0] - a.pr_dbm, abs=1e-9)
    assert a.inputs["p1db_inband_dbm"] == (-34.0, "spec")


def test_matched_filter_snr_and_window_loss():
    cfg = apply_overrides(RadarConfig(), {"processing.window_range": "rect", "processing.window_doppler": "rect"})
    b = link_budget(cfg)
    assert b.snr_cell_db == pytest.approx(b.cn0_dbhz + 10 * math.log10(100e-6 * 64), abs=1e-9)
    assert b.window_loss_db == pytest.approx(0.0, abs=1e-9)
    h = link_budget(RadarConfig())
    # Hann: 1.76 dB per dimension against white noise
    assert h.window_loss_db == pytest.approx(2 * 10 * math.log10(1.5), abs=0.02)
    assert h.snr_cell_rect_db == b.snr_cell_db


def test_adc_quantisation_adds_in_power():
    coarse = link_budget(apply_overrides(RadarConfig(), {"rx.adc_bits": 6}))
    fine = link_budget(apply_overrides(RadarConfig(), {"rx.adc_bits": 16}))
    assert coarse.n0_quant_adc_dbm_hz - fine.n0_quant_adc_dbm_hz == pytest.approx(60.2, abs=0.01)
    assert fine.quant_share_db < 0.01 and coarse.quant_share_db > 10.0
    assert coarse.n0_total_adc_dbm_hz > coarse.n0_thermal_adc_dbm_hz


def test_snr_vs_range_falls_monotonically():
    s = snr_vs_range(RadarConfig(), [1.0, 2.0, 5.0, 10.0, 15.0])
    assert np.all(np.diff(s) < 0)


def test_adc_amplitudes_are_consistent_with_the_powers():
    cfg = RadarConfig()
    b = link_budget(cfg)
    a_s, a_fs, n0_50 = adc_amplitudes(cfg, b)
    assert 10 * math.log10(a_s ** 2 / 50) + 30 == pytest.approx(b.ps_adc_dbm, abs=1e-9)
    assert 10 * math.log10(a_fs ** 2 / 50) + 30 == pytest.approx(cfg.rx.adc_fullscale_dbm, abs=1e-9)
    assert 10 * math.log10(n0_50 / 50) + 30 == pytest.approx(b.n0_thermal_adc_dbm_hz, abs=1e-9)


# ---------------------------------------------------------------- 0.2.33 (fmcw_radar#42): how far at a given Pd

def test_the_detection_range_is_where_the_budget_meets_the_requirement():
    """A bisection on ``link_budget`` with the target moved out.  The
    default radar (a human, 14 dBm EIRP): 28.78 m against the 12.24 dB its
    CA-CFAR needs for Pd 0.9, 29.56 m against the 11.75 dB of a known noise
    level (the number jcas60 extrapolated from the report by hand).  Held to
    a lower EIRP it is nearer by the fourth root; a target too weak at the
    nearest range asked has none."""
    cfg = RadarConfig()
    r = detection_range_m(cfg, 12.24)
    assert r == pytest.approx(28.78, abs=0.01) and link_budget(cfg, range_m=r).snr_cell_db == pytest.approx(12.24, abs=1e-6)
    assert detection_range_m(cfg, snr_for_pd(0.9, 1e-4)) == pytest.approx(29.56, abs=0.01)
    assert detection_range_m(cfg, 12.24) < detection_range_m(cfg, 6.24) < detection_range_m(cfg, 0.24)
    cap = compliance_check(cfg).eirp_cap_dbm - 6.0
    near = detection_range_m(cfg, 12.24, eirp_cap_dbm=cap)
    assert link_budget(cfg, range_m=near, eirp_cap_dbm=cap).snr_cell_db == pytest.approx(12.24, abs=1e-6)
    assert 10.0 ** (-6.0 / 40.0) < near / r < 10.0 ** (-6.0 / 40.0) * 1.03                           # R^4, and a little less oxygen on the way
    weak = apply_overrides(cfg, {"target.kind": "custom", "target.rcs_dbsm": -30.0, "frontend.tx_backoff_db": 70.0})
    assert link_budget(weak, range_m=0.5).snr_cell_db < 12.24 and detection_range_m(weak, 12.24) == 0.0


def test_where_the_transmitters_take_turns_a_look_has_a_share_of_the_chirps():
    """The requirement is per look.  With two transmitters in turn each
    virtual channel's Doppler FFT has half the chirps: the look is 3 dB
    under the budget's cell, and the range is where *that* meets it --
    36.3 m on the bundled MIMO config, not the 43.2 m the cell's SNR gives."""
    cfg = load_config("configs/radar_60g_mimo.yaml")
    assert cfg.mimo.n_tx == 2
    need = rpt.build(cfg)["detection"]["range_at_pd"]["snr_required_db"]
    r = detection_range_m(cfg, need)
    assert link_budget(cfg, range_m=r).snr_cell_db - 10.0 * math.log10(2.0) == pytest.approx(need, abs=1e-6)
    assert r == pytest.approx(36.3, abs=0.1) and r * 10.0 ** (10.0 * math.log10(2.0) / 40.0) == pytest.approx(43.2, abs=0.2)


def test_the_report_says_how_far_and_what_stops_it():
    """``detection.range_at_pd``: the SNR-limited range, the IF band's, the
    nearer of the two and its name.  The default radar is stopped by its IF
    band at 14.99 m with SNR to spare out to 28.78 m; a weak target is
    stopped by the SNR."""
    rep = rpt.build(apply_overrides(RadarConfig(), {"lo.engine": "response"}))
    rp = rep["detection"]["range_at_pd"]
    assert (rp["pd"], rp["n_looks"], rp["limited_by"]) == (0.9, 1, "if_band") and rp["pfa"] == rep["detection"]["pfa"]
    assert rp["snr_required_db"] == rep["cfar"]["snr_pd90_db"] == pytest.approx(12.24, abs=0.01)
    assert rp["snr_limited_range_m"] == detection_range_m(RadarConfig(), rp["snr_required_db"]) == pytest.approx(28.78, abs=0.01)
    assert rp["if_band_range_m"] == RadarConfig().max_range_m == pytest.approx(14.99, abs=0.01) and rp["range_m"] == rp["if_band_range_m"]
    assert "CA-CFAR" in rp["criterion"] and "the LO's noise floor" in rp["not_included"]
    md = rpt.to_markdown(rep)
    assert "How far at Pd 0.9" in md and "reaches **14.99 m**, limited by the IF band" in md
    weak = rpt.build(apply_overrides(RadarConfig(), {"lo.engine": "response", "target.kind": "custom", "target.rcs_dbsm": -30.0}))
    wp = weak["detection"]["range_at_pd"]
    assert wp["limited_by"] == "snr" and wp["range_m"] == wp["snr_limited_range_m"] == pytest.approx(9.40, abs=0.01)
    assert "reaches **9.40 m**, limited by the SNR" in rpt.to_markdown(weak)

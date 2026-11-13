"""The radar equation and the noise at the ADC: scaling laws, not snapshots."""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.link import adc_amplitudes, link_budget, snr_vs_range


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

"""The IF high-pass in both engines (0.2.25).

Until then the statistical budget knew the filter only inside the leakage
budget, and the time engine ran a Butterworth designed at the ADC's rate --
not the analog filter the closed form describes.  Now the budget takes the
filter's attenuation at the target's beat off the echo and off the thermal
noise (the ADC's quantisation noise, which comes after the filter, keeps its
level), and the time engine filters on the waveform grid, where the same
Butterworth is the closed form to a few hundredths of a dB."""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.engine.statistical import hpf_floor_tilt
from fmcw_radar.link import link_budget, snr_vs_range

FAST = {"lo.engine": "response", "chirp.n_chirps": 16}


def _cfg(corner_hz=0.0, order=1, **ov):
    return apply_overrides(RadarConfig(), {**FAST, "rx.hpf_corner_hz": corner_hz, "rx.hpf_order": order, **ov})


def _lin(db):
    return 10.0 ** (db / 10.0)


def test_without_the_filter_the_budget_has_no_line_for_it():
    b = link_budget(_cfg())
    assert b.hpf_db == 0.0 and not any("high-pass" in row[0] for row in b.as_rows())
    st = run_statistical(_cfg())
    assert hpf_floor_tilt(_cfg(), st.budget) == 1.0 and st.extras["hpf_floor_tilt_db"] == 0.0
    assert st.extras["snr_cell_local_db"] == st.extras["snr_cell_expected_db"]


@pytest.mark.parametrize("order", [1, 2, 3, 4])
def test_a_butterworth_takes_3_dB_at_its_corner_whatever_its_order(order):
    cfg = _cfg()
    at_corner = link_budget(_cfg(cfg.beat_hz(), order))
    assert at_corner.hpf_db == pytest.approx(10.0 * math.log10(2.0), abs=1e-9)
    # an octave above the corner: 1 / (1 + 2^-2n) of the power
    octave = link_budget(_cfg(cfg.beat_hz() / 2.0, order))
    assert octave.hpf_db == pytest.approx(10.0 * math.log10(1.0 + 2.0 ** (-2 * order)), abs=1e-9)


@pytest.mark.parametrize("corner_hz, order", [(0.2e6, 2), (1.0e6, 1), (1.0e6, 2), (2.0e6, 2), (3.0e6, 4)])
def test_the_filter_comes_off_the_echo_and_the_thermal_noise_not_off_the_adcs_noise(corner_hz, order):
    off, on = link_budget(_cfg()), link_budget(_cfg(corner_hz, order))
    a = on.hpf_db
    assert a > 0.0 and ("IF high-pass at the target's beat (echo and thermal noise)", a, "dB") in on.as_rows()
    assert on.pr_dbm == off.pr_dbm and on.n0_thermal_dbm_hz == off.n0_thermal_dbm_hz              # nothing ahead of the filter moves
    assert on.ps_adc_dbm == pytest.approx(off.ps_adc_dbm - a, abs=1e-12)
    assert on.n0_thermal_adc_dbm_hz == pytest.approx(off.n0_thermal_adc_dbm_hz - a, abs=1e-12)
    assert on.n0_quant_adc_dbm_hz == off.n0_quant_adc_dbm_hz
    # so the SNR loses only what the quantisation noise gains on the thermal floor, worked out here from the two densities
    h = _lin(-a)
    th, q = _lin(off.n0_thermal_adc_dbm_hz), _lin(off.n0_quant_adc_dbm_hz)
    loss = 10.0 * math.log10((th * h + q) / (h * (th + q)))
    assert off.snr_cell_db - on.snr_cell_db == pytest.approx(loss, abs=1e-9)
    assert (loss < 0.05) == (a < 3.0)                     # the default ADC is 18 dB under the thermal floor: a shallow filter costs nothing
    if a > 20.0:
        assert loss > 3.0                                 # a deep one sinks the thermal floor under the quantisation noise


def test_a_nearer_target_pays_more():
    """The filter is there to take the leakage out at the bottom of the band:
    what it takes off an echo grows as the target comes closer, on top of R^-4."""
    ranges = [0.5, 1.0, 2.0, 5.0, 10.0]
    off, on = snr_vs_range(_cfg(), ranges), snr_vs_range(_cfg(500e3, 2), ranges)
    cost = off - on
    assert np.all(np.diff(cost) < 0.0) and cost[-1] < 0.01
    # at 1 m the beat is 267 kHz, under the 500 kHz corner: the echo is 11 dB down, and with the quantisation
    # noise 18 dB under the thermal floor that costs the SNR a few tenths of a dB only -- noise and echo went down together
    one = link_budget(_cfg(500e3, 2), range_m=1.0)
    assert one.hpf_db == pytest.approx(11.2, abs=0.1) and cost[1] == pytest.approx(one.quant_share_db - link_budget(_cfg(), range_m=1.0).quant_share_db, abs=1e-9)


@pytest.mark.parametrize("corner_hz, order", [(0.2e6, 2), (1.0e6, 1), (1.0e6, 2), (1.0e6, 4), (2.0e6, 2), (3.0e6, 2)])
def test_both_engines_read_the_same_filter(corner_hz, order):
    """The time engine's peak drops by the budget's attenuation, its
    map-wide floor by what the budget expects of a floor that is no longer
    flat, and its SNR reads the statistical engine's expected one.  (With the
    filter at the ADC's rate the peak was 5.4 dB lower than the closed form
    for a 3 MHz corner; the engines disagreed by up to 15 dB on the SNR.)"""
    c0, c1 = _cfg(), _cfg(corner_hz, order)
    t0, t1 = run_time(c0), run_time(c1)
    s0, s1 = run_statistical(c0), run_statistical(c1)
    peak = 10.0 * math.log10(t1.extras["peak_power"] / t0.extras["peak_power"])
    floor = 10.0 * math.log10(t1.extras["noise_floor"] / t0.extras["noise_floor"])
    assert peak == pytest.approx(-s1.budget.hpf_db, abs=0.1)
    expected_floor = s1.extras["hpf_floor_tilt_db"] - s1.budget.hpf_db + (s1.budget.quant_share_db - s0.budget.quant_share_db)
    assert floor == pytest.approx(expected_floor, abs=0.3)
    assert t1.snr_cell_db == pytest.approx(s1.extras["snr_cell_expected_db"], abs=0.5)
    assert abs(t0.snr_cell_db - s0.extras["snr_cell_expected_db"]) < 0.5        # as before, without the filter


def test_a_map_wide_floor_is_not_the_floor_where_the_target_is():
    """A corner above the beat: the target sits on the filter's skirt, 7.8 dB
    down, while most of the band above it is hardly touched.  A map-wide
    noise estimate then reads 4.7 dB less SNR than the target has against its
    own neighbourhood -- which is what the CFAR compares it with."""
    c = _cfg(2.0e6, 2)
    st, ref = run_statistical(c), run_statistical(_cfg())
    assert st.budget.hpf_db == pytest.approx(7.82, abs=0.01)
    # (not to the last hundredth: the LO's residual noise in the cell is not tilted)
    assert st.extras["hpf_floor_tilt_db"] == pytest.approx(st.extras["snr_cell_local_db"] - st.extras["snr_cell_expected_db"], abs=0.05)
    assert st.extras["hpf_floor_tilt_db"] == pytest.approx(4.7, abs=0.1)
    # the local SNR lost only the quantisation share; the detection probability is taken there
    assert ref.snr_cell_db - st.snr_cell_db == pytest.approx(st.budget.quant_share_db - ref.budget.quant_share_db, abs=1e-9) and ref.snr_cell_db - st.snr_cell_db < 0.5
    assert st.cfar["snr_look_db"] == st.extras["snr_cell_local_db"]
    # the tilt is the band's mean of |H|^2 against |H|^2 at the beat, the columns the time engine averages
    n_r = c.n_samples * c.processing.range_pad
    df = c.rx.adc_fs_hz / n_r
    cols = np.arange(int(c.rx.if_bw_hz * c.chirp.duration_s * c.processing.range_pad))
    keep = np.abs(cols - round(c.beat_hz() / df)) > max(8, (n_r // 2) // 16)
    r = (cols[keep] * df / 2.0e6) ** 4
    th, q = _lin(ref.budget.n0_thermal_adc_dbm_hz), _lin(ref.budget.n0_quant_adc_dbm_hz)
    mean = th * np.mean(r / (1.0 + r)) + q
    assert hpf_floor_tilt(c, st.budget) == pytest.approx(mean / (th * _lin(-st.budget.hpf_db) + q), rel=1e-9)


def test_with_the_leakage_on_the_filter_is_counted_once():
    """The leakage budget used to subtract the filter from the target's
    level itself; the link budget now carries it."""
    c = _cfg(200e3, 2, **{"leakage.enabled": True})
    st = run_statistical(c)
    assert st.leakage.hpf_atten_at_target_db == st.budget.hpf_db > 0.0
    assert st.leakage.target_level_adc_dbm == pytest.approx(st.budget.ps_adc_dbm, abs=1e-9)
    assert any("high-pass" in row[0] for row in st.budget.as_rows())
    # every target of a scene has its own beat, and its own share of the filter
    two = apply_overrides(c, {"extra_targets": [{"range_m": 1.0, "velocity_mps": 0.0, "kind": "human"}]})
    rows = run_statistical(two).targets
    assert rows[1]["hpf_db"] > rows[0]["hpf_db"] > 0.0 and rows[1]["range_m"] == 1.0

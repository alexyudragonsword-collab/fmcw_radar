"""Windows, FFTs, CFAR and the detection curve: closed forms and known tables."""

import math

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig
from fmcw_radar.processing import (ca_cfar_1d, ca_cfar_2d, coherent_gain_db, enbw_bins, mainlobe_width_bins,
                                   pd_swerling0, peak_sidelobe_db, range_axis_m, range_doppler_map, range_fft,
                                   read_peak, snr_for_pd, threshold_factor, velocity_axis_mps, window)
from fmcw_radar.sources import number


@pytest.mark.parametrize("name", ["rect", "hann", "hamming", "blackman"])
def test_mainlobe_width_matches_harris_within_5_percent(name):
    """The window's own spectrum against Harris 1978 Table I (source: spec, two digits)."""
    assert mainlobe_width_bins(name) == pytest.approx(number(f"window.{name}_3db_bins").value, rel=0.05)


def test_rectangular_window_is_one_bin_at_the_rayleigh_level():
    assert mainlobe_width_bins("rect", level_db=20 * math.log10(2 / math.pi)) == pytest.approx(1.0, rel=0.01)


def test_enbw_and_coherent_gain():
    assert enbw_bins(window("rect", 256)) == pytest.approx(1.0)
    assert enbw_bins(window("hann", 256)) == pytest.approx(1.5, rel=1e-6)
    assert coherent_gain_db(window("rect", 256)) == pytest.approx(10 * math.log10(256))
    assert coherent_gain_db(window("hann", 256)) == pytest.approx(10 * math.log10(256 / 1.5), rel=1e-6)


def test_window_sidelobes_are_the_known_ones():
    assert peak_sidelobe_db("rect") == pytest.approx(-13.3, abs=0.2)
    assert peak_sidelobe_db("hann") == pytest.approx(-31.5, abs=0.3)
    assert peak_sidelobe_db("hamming") < -40.0 and peak_sidelobe_db("blackman") < -55.0


def test_range_fft_reads_a_tone_at_its_amplitude_and_bin():
    cfg = RadarConfig()
    n, fs = cfg.n_samples, cfg.rx.adc_fs_hz
    t = np.arange(n) / fs
    f0 = 37 * fs / n
    x = 0.7 * np.exp(2j * np.pi * f0 * t)
    for name in ("rect", "hann"):
        s = range_fft(x, name, 1)
        assert abs(s[37]) == pytest.approx(0.7, rel=1e-9)
    axis = range_axis_m(cfg, n)
    assert axis[37] == pytest.approx(37 * fs / n * 299_792_458.0 / (2 * cfg.slope_hz_per_s))


def test_range_doppler_map_puts_a_moving_target_where_the_config_says():
    cfg = RadarConfig()
    n, fs, m = cfg.n_samples, cfg.rx.adc_fs_hz, cfg.chirp.n_chirps
    t = np.arange(n) / fs
    k = np.arange(m)[:, None]
    fb, fd = cfg.beat_hz(), cfg.doppler_hz()
    frame = np.exp(2j * np.pi * (fb * t[None, :] + fd * cfg.chirp.pri_s * k))
    rd = range_doppler_map(frame, cfg)
    i, j = np.unravel_index(np.argmax(np.abs(rd)), rd.shape)
    assert range_axis_m(cfg, rd.shape[1])[j] == pytest.approx(cfg.target.range_m, abs=cfg.range_resolution_m / 2)
    assert velocity_axis_mps(cfg, rd.shape[0])[i] == pytest.approx(cfg.target.velocity_mps, abs=cfg.velocity_resolution_mps)


def test_read_peak_interpolates_between_bins():
    x = np.linspace(-5, 5, 101)
    y = -3.0 * (x - 0.17) ** 2
    rp = read_peak(x, y)
    assert rp["peak_pos"] == pytest.approx(0.17, abs=1e-6)
    assert rp["width_3db"] == pytest.approx(2 * math.sqrt(1.0), rel=0.02)


def test_cfar_threshold_factor_and_false_alarm_rate():
    """On exponential cell powers the CA-CFAR's Pfa is the asked-for one, to a few percent at 1e-3."""
    n = 16
    assert threshold_factor(n, 1e-3) == pytest.approx(n * (1e-3 ** (-1 / n) - 1))
    rng = np.random.default_rng(0)
    p = rng.exponential(1.0, 400_000)
    _, det = ca_cfar_1d(p, guard=2, train=8, pfa=1e-3)
    assert det.mean() == pytest.approx(1e-3, rel=0.15)
    p2 = rng.exponential(1.0, (200, 2000))
    _, det2 = ca_cfar_2d(p2, guard=1, train=3, pfa=1e-3)
    assert det2.mean() == pytest.approx(1e-3, rel=0.15)


def test_cfar_finds_a_strong_cell_only():
    p = np.random.default_rng(1).exponential(1.0, 512)
    p[200] = 1e4
    _, det = ca_cfar_1d(p, guard=2, train=8, pfa=1e-6)
    assert det[200] and det.sum() == 1


def test_detection_probability_is_marcum_q():
    """Pd = 1 - Pfa at zero SNR... no: at SNR -> -inf Pd -> Pfa; at 13 dB and 1e-6, 0.9 (the textbook point)."""
    assert float(pd_swerling0(-40.0, 1e-6)) == pytest.approx(1e-6, rel=0.05)
    assert float(pd_swerling0(13.2, 1e-6)) == pytest.approx(0.9, abs=0.03)
    assert float(pd_swerling0(30.0, 1e-6)) == pytest.approx(1.0, abs=1e-9)
    assert snr_for_pd(0.9, 1e-6) == pytest.approx(13.2, abs=0.3)

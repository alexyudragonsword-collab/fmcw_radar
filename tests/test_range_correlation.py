"""Invariant #2: TX and RX share one LO; the beat sees 2 (1 - cos 2 pi f tau) S_phi(f).

Acceptance: tau = 0 -> zero residual bit for bit; tau -> inf -> twice the
single-sided PSD; in between the closed form within 0.1 dB of synthesised
sequences (band-averaged); the same equation as d2d_link's tree-delay leak.
"""

import numpy as np
import pytest
from conftest import trapz

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.lo import LOProfile
from fmcw_radar.phase_noise import RangeCorrelation, correlation_factor, delayed


@pytest.fixture(scope="module")
def prof():
    return LOProfile.from_config(RadarConfig())


def test_tau_zero_leaves_nothing_bit_for_bit(prof):
    rc = RangeCorrelation(prof, 0.0)
    rng = np.random.default_rng(0)
    phi = rc.synthesize_lo(1 << 14, 10e6, rng)
    assert np.std(phi) > 0.01                       # the LO is far from clean
    r = rc.residual(phi, 10e6)
    assert np.array_equal(r, np.zeros_like(r))      # and none of it reaches the beat
    assert float(np.max(rc.residual_psd(np.geomspace(1e3, 5e6, 100)))) == 0.0


def test_delay_is_the_identity_object_at_zero_and_a_pure_phase_otherwise():
    x = np.random.default_rng(1).standard_normal(4096)
    assert delayed(x, 0.0, 1e6) is x
    y = delayed(x, 3.3e-6, 1e6)
    assert np.mean(y * y) == pytest.approx(np.mean(x * x), rel=1e-4)   # a delay moves no power (the Nyquist bin apart)


def test_large_tau_tends_to_twice_the_single_sided(prof):
    f = np.linspace(1e4, 4e6, 2_000_001)            # 2 Hz steps: the cosine's 1 kHz period is resolved
    s = prof.psd(f)
    for tau in (1e-3, 1e-2):
        ratio = trapz(RangeCorrelation(prof, tau).residual_psd(f), f) / trapz(s, f)
        assert ratio == pytest.approx(2.0, rel=0.01)
    assert np.mean(correlation_factor(np.linspace(1e4, 4e6, 100_001), 1e-2)) == pytest.approx(2.0, rel=1e-3)


def test_small_tau_is_a_differentiator(prof):
    """Below 1 / (6 tau): 2 (1 - cos x) ~ x^2, a 20 dB/decade slope."""
    tau = 2 * 1.0 / 299_792_458.0
    rc = RangeCorrelation(prof, tau)
    f = np.array([1e4, 1e5])
    assert rc.suppression_db(f)[1] - rc.suppression_db(f)[0] == pytest.approx(20.0, abs=0.05)
    assert float(rc.suppression_db(1e5)) == pytest.approx(20 * np.log10(2 * np.pi * 1e5 * tau), abs=0.05)


@pytest.mark.parametrize("range_m", [1.0, 10.0, 100.0])
def test_closed_form_matches_synthesis_within_a_tenth_of_a_db(prof, range_m):
    cfg = RadarConfig()
    rc = RangeCorrelation(prof, cfg.tau_s(range_m))
    fs, n = cfg.rx.adc_fs_hz, 1 << 16
    f, meas = rc.measured_residual_psd(n, fs, np.random.default_rng(3), blocks=32)
    closed = rc.residual_psd(f)
    edges = np.geomspace(2e4, 4e6, 9)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (f >= lo) & (f < hi)
        d = 10.0 * np.log10(meas[m].mean() / closed[m].mean())
        assert abs(d) < 0.1, (range_m, lo, d)


def test_sidelobe_is_the_residual_times_the_bin_bandwidth(prof):
    rc = RangeCorrelation(prof, 30e-9)
    f = 2.5e5
    assert float(rc.sidelobe_dbc(f, 1e4)) == pytest.approx(float(rc.residual_l_dbc(f)) + 40.0, abs=1e-9)
    assert float(rc.residual_l_dbc(f)) == pytest.approx(10 * np.log10(rc.residual_psd(f) / 2), abs=1e-9)


def test_residual_rms_grows_with_range_then_saturates(prof):
    cfg = RadarConfig()
    rms = [RangeCorrelation(prof, cfg.tau_s(r)).rms_residual_rad(1e4, 4e6) for r in (0.1, 1.0, 10.0, 100.0, 1000.0)]
    assert rms[0] < rms[1] < rms[2] < rms[3]
    assert rms[4] == pytest.approx(np.sqrt(2.0) * prof.rms_phase_rad(1e4, 4e6), rel=0.03)


def test_profile_spurs_pass_through_the_same_difference(tmp_path):
    """A file profile's spur of peak a becomes 2 a |sin(pi f tau)|."""
    import yaml

    p = tmp_path / "prof.yaml"
    yaml.safe_dump({"f0_hz": 15e9, "f_hz": [1e3, 1e6, 5e7], "l_dbc_hz": [-80.0, -100.0, -130.0],
                    "spurs": [{"f_hz": 1e6, "dbc": -40.0}], "source": "test"}, p.open("w"))
    cfg = apply_overrides(RadarConfig(), {"lo.profile": str(p)})
    prof = LOProfile.from_config(cfg)
    a = 2 * 10 ** (-40 / 20) * 4                    # x4 multiplier scales the phase
    assert prof.spurs == ((1e6, pytest.approx(a)),)
    tau = 0.25e-6
    rc = RangeCorrelation(prof, tau)
    assert rc.spur_terms()[0][1] == pytest.approx(2 * a * abs(np.sin(np.pi * 1e6 * tau)))
    assert RangeCorrelation(prof, 0.0).spur_terms() == []


def test_exact_sideband_is_first_order_when_small_and_above_it_when_not(prof):
    """At 5 m (0.08 rad residual on the 12.2 ps TDC; 0.05 on 0.2.11's 5 ps) the Gaussian-phase spectrum is the S_res / 2
    sideband; at 100 m (0.3 rad) the in-band noise beating with itself lays a
    floor near the tone that the first order does not have."""
    cfg = RadarConfig()
    near = RangeCorrelation(prof, cfg.tau_s(5.0))
    sb = near.beat_sideband(16e6, 1 << 16, 2.5e9)
    f = np.array([2e5, 5e5, 1e6, 2e6])
    assert np.allclose(sb.sidelobe_dbc(f, 1e4), near.sidelobe_dbc(f, 1e4), atol=1.0)   # second order: +0.8 dB at 200 kHz (+0.5 on 5 ps)
    assert sb.carrier_loss_db == pytest.approx(10 * np.log10(np.exp(-sb.sigma2)), abs=1e-9)
    assert -0.3 < sb.carrier_loss_db < 0.0
    far = RangeCorrelation(prof, cfg.tau_s(100.0))
    sbf = far.beat_sideband(16e6, 1 << 16, 1.25e9 / 2)
    assert sbf.sigma2 > 0.05
    assert float(sbf.sidelobe_dbc(13e3, 1.7e3)) > float(far.sidelobe_dbc(13e3, 1.7e3)) + 15.0
    # where the first order is largest (2 (1 - cos) at its maximum, f = 1 / 2 tau) the two agree; the exact
    # spectrum is never below the first order (the nulls of the cosine are filled in)
    f_peak = 0.5 / far.tau_s
    assert float(sbf.sidelobe_dbc(f_peak, 1.7e3)) == pytest.approx(float(far.sidelobe_dbc(f_peak, 1.7e3)), abs=1.5)
    fg = np.linspace(1e4, 3e6, 300)
    assert np.all(sbf.sidelobe_dbc(fg, 1.7e3) > far.sidelobe_dbc(fg, 1.7e3) - 0.2)

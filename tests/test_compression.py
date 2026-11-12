"""The receiver's compression (link/compression.py): two Rapp stages, the closed form against synthesis,
and the statistical engine against the time engine on the same frame."""

import numpy as np
import pytest

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine.statistical import run_statistical
from fmcw_radar.engine.timedomain import run_time
from fmcw_radar.link import leakage_budget, link_budget
from fmcw_radar.link.compression import rapp, rapp_saturation, small_signal


def test_rapp_has_its_1db_point_where_it_is_told():
    for p in (1.0, 2.0, 3.0):
        a1 = 0.7
        assert abs(rapp(np.array([a1 + 0j]), a1, p)[0]) / a1 == pytest.approx(10.0 ** (-1.0 / 20.0), rel=1e-12)
        assert abs(rapp(np.array([1e4 * a1 + 0j]), a1, p)[0]) == pytest.approx(rapp_saturation(a1, p), rel=1e-6)
        x = np.array([1e-6 * np.exp(0.4j)])
        assert np.allclose(rapp(x, a1, p), x, rtol=1e-12)                       # unit small-signal gain, phase kept


@pytest.mark.parametrize("blocker_db", [-10.0, 0.0, 4.0, 10.0])
def test_small_signal_closed_form_is_the_limiter_on_synthesised_samples(blocker_db):
    """A weak tone and white noise beside a strong tone through the limiter:
    the weak tone keeps (F' + F/B)/2 of its amplitude, its mirror about the
    strong tone gets (F' - F/B)/2, the noise (F'^2 + (F/B)^2)/2 of its power,
    the strong tone mean(F^2)/mean(B^2)."""
    rng = np.random.default_rng(1)
    n = 1 << 15
    t = np.arange(n)
    kb, ks = 37, 5011
    big = 10.0 ** (blocker_db / 20.0)
    blk = big * np.exp(2j * np.pi * kb * t / n)
    s = 1e-3 * np.exp(2j * np.pi * ks * t / n + 0.3j)
    noise = 1e-3 * (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)
    y = np.fft.fft(rapp(blk + s, 1.0, 2.0) - rapp(blk, 1.0, 2.0)) / n
    yn = np.abs(np.fft.fft(rapp(blk + noise, 1.0, 2.0) - rapp(blk, 1.0, 2.0)) / np.sqrt(n)) ** 2
    keep = np.ones(n, bool)
    keep[[kb, (2 * kb) % n]] = False
    ss = small_signal(np.full(16, big), 1.0, 2.0)
    assert 20 * np.log10(abs(y[ks]) / 1e-3) == pytest.approx(ss["signal"], abs=1e-3)
    assert 20 * np.log10(abs(y[(2 * kb - ks) % n]) / 1e-3) == pytest.approx(ss["image"], abs=1e-3)
    assert 10 * np.log10(yn[keep].mean() / 1e-6) == pytest.approx(ss["noise"], abs=0.1)
    strong = 20 * np.log10(abs(np.fft.fft(rapp(blk, 1.0, 2.0))[kb] / n) / big)
    assert strong == pytest.approx(ss["strong"], abs=1e-6)
    assert ss["snr"] <= 0.0 and ss["snr"] >= -3.0 - 1e-9                        # a hard limiter's 3 dB is the floor


def _leak(**ov):
    return apply_overrides(RadarConfig(), {"leakage.enabled": True, "leakage.reflector_range_m": 0.02, "chirp.n_chirps": 16,
                                           "rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2, **ov})


def _cell_and_floor(tm, cfg):
    p = 10.0 ** (tm.rd_db / 10.0)
    r, v = tm.range_axis_m, tm.velocity_axis_mps
    jt, it = int(np.argmin(np.abs(r - cfg.target.range_m))), int(np.argmin(np.abs(v - cfg.target.velocity_mps)))
    cell = float(p[max(it - 1, 0):it + 2, max(jt - 3, 0):jt + 4].max())
    floor = float(np.mean(p[:, (r > 6.5) & (r < 12.0)]))
    return 10.0 * np.log10(cell), 10.0 * np.log10(floor)


@pytest.mark.parametrize("ov, echo, noise", [({}, -10.65, -8.35), ({"frontend.rx_rapp_p": 1.0}, -5.89, -5.39),
                                             ({"frontend.tx_power_dbm": 10.0, "leakage.isolation_db": 25.0}, -2.18, -2.06)])
def test_budget_and_time_engine_agree_on_what_the_leakage_does_to_the_echo(ov, echo, noise):
    """The sourced leakage (-8 dBm at the receiver, 4 dB over the out-of-band
    point) through the default receiver: the echo loses 10.7 dB and the
    thermal noise 8.4 dB of power, so the SNR 2.3 dB.  The time engine, the
    same frame with the stages on and off: the target's cell and the floor
    6.5-12 m out move by as much (the floor a little less: the ADC's
    quantisation comes after the stages)."""
    cfg = _leak(**ov)
    lb = leakage_budget(cfg)
    assert lb.compression_signal_db == pytest.approx(echo, abs=0.02) and lb.compression_noise_db == pytest.approx(noise, abs=0.02)
    cb = apply_overrides(cfg, {"rx.blank_s": lb.blank_recommended_s})
    on, off = _cell_and_floor(run_time(cb, seed=4), cb), _cell_and_floor(run_time(cb, seed=4, compress=False), cb)
    assert on[0] - off[0] == pytest.approx(lb.compression_signal_db, abs=0.15)
    assert on[1] - off[1] == pytest.approx(lb.compression_noise_db, abs=0.5)
    # the statistical engine carries the loss into every SNR it reports: between the echo-less-noise figure
    # and the echo's (the ADC's quantisation noise loses nothing), and as the time engine's cell over its floor
    st = run_statistical(cfg)
    lin = run_statistical(apply_overrides(cfg, {"frontend.compression": False}))
    d_snr = st.snr_cell_db - lin.snr_cell_db
    assert lb.compression_signal_db <= d_snr <= lb.compression_signal_db - lb.compression_noise_db + 1e-9
    assert d_snr == pytest.approx((on[0] - off[0]) - (on[1] - off[1]), abs=0.35)
    assert st.budget.compression_signal_db == lb.compression_signal_db
    assert st.targets[0]["snr_cell_db"] == pytest.approx(st.snr_cell_db, abs=1e-9)


def test_the_front_stage_holds_the_leakage_down_and_the_echo_pays():
    """What 0.2.8 called a first-order high-pass that cannot cope (the leakage
    at the ADC's full scale, 78 % of the samples clipped) is, with the stage
    ahead of the filter saturating, 5.2 dB less leakage and room at the ADC
    -- and an echo 10.9 dB down.  The linear receiver keeps the old picture."""
    one = leakage_budget(_leak(**{"rx.hpf_order": 1}))
    assert one.leakage_compression_db == pytest.approx(-5.24, abs=0.02)
    assert one.adc_headroom_db == pytest.approx(5.3, abs=0.1) and not one.steady_clipping and one.blank_recommended_s > 0.0
    assert one.compression_signal_db == pytest.approx(-10.9, abs=0.1)
    assert one.compression_image_dbc == pytest.approx(-1.5, abs=0.1)              # the echo's mirror about the leakage beat
    linear = leakage_budget(_leak(**{"rx.hpf_order": 1, "frontend.compression": False}))
    assert linear.steady_clipping and linear.adc_headroom_db == pytest.approx(0.0, abs=0.1) and linear.compression_signal_db == 0.0
    # no high-pass: the IF stage saturates at 1.2 dB over its 1 dB point, still over the ADC's full scale
    raw = leakage_budget(_leak(**{"rx.hpf_corner_hz": 0.0}))
    assert raw.adc_headroom_db == pytest.approx(raw.adc_headroom_no_hpf_db) and -4.0 < raw.adc_headroom_db < 0.0
    assert raw.required_hpf_atten_db > 20.0                                         # read at the filter's output, not the saturated stage's


def test_without_a_strong_signal_the_stages_change_nothing():
    """No leakage: the frame is bit for bit the linear receiver's (the gains
    differ from 1 below the ADC's step) and the budget takes nothing off."""
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 4})
    assert np.array_equal(run_time(cfg, seed=2).frame, run_time(cfg, seed=2, compress=False).frame)
    st = run_statistical(cfg)
    assert st.leakage is None and st.budget.compression_signal_db == 0.0 and st.snr_cell_db == link_budget(cfg).snr_cell_db

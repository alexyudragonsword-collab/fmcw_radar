"""Milestone 2: TX-RX leakage, the IF high-pass, several targets, the CFAR curves."""

import math

import numpy as np
import pytest

from conftest import REPO

from fmcw_radar import report as rpt
from fmcw_radar.config import RadarConfig, apply_overrides, config_to_dict, load_config
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.link import isolation_for_snr_loss, leakage_budget, leakage_need, leakage_snr_loss_db, link_budget
from fmcw_radar.processing import apply_hpf, cfar_pd_monte_carlo, cfar_pd_swerling1, hpf_attenuation_db, pd_swerling0
from fmcw_radar.processing.windows import coherent_gain_db, mainlobe_width_bins, peak_sidelobe_db, range_window


def _leak(**ov):
    """The transmitter at its full power (no backoff): the levels these tests
    were built on.  The default's 8 dB of backoff (0.2.20) is
    test_backed_off_default_keeps_the_leakage_under_the_out_of_band_point's."""
    return apply_overrides(RadarConfig(), {"leakage.enabled": True, "leakage.reflector_range_m": 0.02, "chirp.n_chirps": 4,
                                           "frontend.tx_backoff_db": 0.0, **ov})


def test_backed_off_default_keeps_the_leakage_under_the_out_of_band_point():
    """0.2.20: the default transmitter runs 8 dB backed off (4 dBm, the
    regulatory limit through a 10 dBi antenna).  The direct leakage is then
    -16 dBm at the receiver, 4 dB under the -12 dBm out-of-band point where
    the full-power one is 4 dB over; behind the second-order high-pass the
    echo loses 1.5 dB to the stages instead of 10.7."""
    hp = {"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2}
    full, backed = leakage_budget(_leak(**hp)), leakage_budget(_leak(**hp, **{"frontend.tx_backoff_db": None}))
    assert backed.terms[0].level_rx_dbm == pytest.approx(-16.0) and full.terms[0].level_rx_dbm == pytest.approx(-8.0)
    assert backed.p1db_kind == "out of band" and backed.p1db_margin_db == pytest.approx(+4.0) and full.p1db_margin_db == pytest.approx(-4.0)
    assert backed.compression_signal_db == pytest.approx(-1.49, abs=0.02) and full.compression_signal_db == pytest.approx(-10.65, abs=0.02)
    assert backed.adc_headroom_db > full.adc_headroom_db > 20.0


def test_leakage_budget_levels_and_flags():
    cfg = _leak()
    lb = leakage_budget(cfg)
    assert lb.isolation_source == "spec" and lb.isolation_db == 20.0             # a board array without an isolation structure
    direct, refl = lb.terms
    assert direct.level_rx_dbm == pytest.approx(12.0 - 20.0) and refl.level_rx_dbm == pytest.approx(direct.level_rx_dbm - 10.0)
    assert direct.beat_hz == pytest.approx(cfg.slope_hz_per_s * 0.2e-9)
    # no high-pass: the leakage is an in-band signal and meets the in-band point (-34 dBm at 40 dB of gain)
    assert lb.p1db_kind == "in band" and lb.p1db_margin_db == pytest.approx(-34.0 - (-8.0))
    assert lb.adc_headroom_no_hpf_db < 0.0                                         # and clips
    assert lb.adc_headroom_db == lb.adc_headroom_no_hpf_db                         # no high-pass configured
    assert lb.required_hpf_atten_db > 20.0
    with_hpf = leakage_budget(_leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2}))
    assert with_hpf.adc_headroom_db > 20.0 and with_hpf.required_hpf_atten_db == 0.0
    assert with_hpf.hpf_atten_at_target_db < 0.01                                 # the 1.33 MHz beat is untouched
    # behind a high-pass the 8 kHz beat only loads the stages ahead of it: the out-of-band point, -12 dBm.
    # With the sourced figures (12 dBm out, 20 dB of isolation) the leakage is still 4 dB above it.
    assert with_hpf.p1db_kind == "out of band" and with_hpf.p1db_margin_db == pytest.approx(-12.0 - (-8.0))
    ebg = leakage_budget(_leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2, "leakage.isolation_db": 40.0}))
    assert ebg.p1db_margin_db == pytest.approx(16.0)                               # with the paper's isolation structure
    # a reflector far enough to beat above the corner is an in-band signal again
    far = leakage_budget(_leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2, "leakage.reflector_range_m": 1.0,
                                  "leakage.isolation_db": 60.0}))
    assert far.terms[1].beat_hz > 200e3 and far.p1db_kind == "in band"
    assert far.p1db_margin_db == pytest.approx(-34.0 - far.terms[1].level_rx_dbm)
    assert leakage_budget(RadarConfig()) is None


def test_hpf_attenuation_closed_form_and_filter_agree():
    fs, fc = 10e6, 200e3
    for order in (1, 2, 3):
        assert hpf_attenuation_db(fc, fc, order) == pytest.approx(3.0103, abs=0.01)
        assert hpf_attenuation_db(fc / 10, fc, order) == pytest.approx(20.0 * order, abs=0.05)
        t = np.arange(20000) / fs
        for f in (20e3, 2e6):
            y = apply_hpf(np.exp(2j * np.pi * f * t), fs, fc, order)
            got = -20.0 * math.log10(float(np.mean(np.abs(y[10000:]))))
            assert got == pytest.approx(hpf_attenuation_db(f, fc, order), abs=0.2)
    x = np.ones(10, dtype=complex)
    assert apply_hpf(x, fs, 0.0, 1) is x


def test_time_engine_clips_without_the_high_pass_and_recovers_with_it():
    without = run_time(_leak(), phase_noise=False)
    assert without.extras["clipped_fraction"] > 0.9
    cfg = _leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2})
    with_ = run_time(cfg, phase_noise=False)
    assert with_.extras["clipped_fraction"] < 0.1
    # the leakage after the high-pass still tops the target (the budget says by
    # 16 dB): the map's peak is the leakage at ~0 m and the target is found
    # at 5 m at the level the budget gives it
    lb = leakage_budget(cfg)
    assert with_.peak_range_m < 0.1
    found = with_.extras["targets_found"][0]
    assert found is not None and found[0] == pytest.approx(5.0, abs=0.04)
    assert found[2] == pytest.approx(lb.target_level_adc_dbm - lb.terms[0].level_adc_hpf_dbm, abs=3.0)
    # the leakage shares the LO: with the leakage but no target power the map's peak is the leakage at ~0 m
    lk_only = run_time(_leak(**{"frontend.tx_power_dbm": -190.0, "leakage.isolation_db": 25.0}),
                       phase_noise=False, noise=False, quantise=False)
    assert lk_only.peak_range_m < 0.1


def test_several_targets_statistical_rows_and_time_engine_levels():
    extra = [{"kind": "car", "range_m": 5.3, "velocity_mps": 2.0}, {"kind": "human", "range_m": 9.9, "velocity_mps": -1.0}]
    cfg = apply_overrides(RadarConfig(), {"extra_targets": extra, "chirp.n_chirps": 8})
    st = run_statistical(cfg)
    assert [t["kind"] for t in st.targets] == ["human", "car", "human"]
    assert st.targets[1]["snr_cell_db"] > st.targets[0]["snr_cell_db"] + 15.0     # +20 dBsm, 30 cm farther
    assert not any(t["masked"] for t in st.targets)
    tm = run_time(cfg, phase_noise=False)
    found = tm.extras["targets_found"]
    assert all(f is not None for f in found)
    ref = max(t["ps_adc_dbm"] for t in st.targets)
    for t, f in zip(st.targets, found):
        assert f[0] == pytest.approx(t["range_m"], abs=cfg.range_resolution_m)
        assert f[2] == pytest.approx(t["ps_adc_dbm"] - ref, abs=1.5)


def test_a_weak_target_under_a_strong_ones_skirt_is_called_masked():
    cfg = apply_overrides(RadarConfig(), {"extra_targets": [{"kind": "custom", "range_m": 5.05, "velocity_mps": 2.0, "rcs_dbsm": -45.0}],
                                          "chirp.n_chirps": 4})
    st = run_statistical(cfg)
    weak = st.targets[1]
    assert weak["masked"] and weak["interferer"] == 0 and weak["interference_kind"] == "window"
    assert not st.targets[0]["masked"]


def test_cfar_curves():
    snr = np.array([6.0, 10.0, 14.0])
    pfa = 1e-4
    mc0 = cfar_pd_monte_carlo(snr, pfa, 16, 40_000, seed=1)
    ideal = pd_swerling0(snr, pfa)
    assert np.all(mc0 < ideal)                                       # the CFAR loss
    assert np.all(np.diff(mc0) > 0)
    mc1 = cfar_pd_monte_carlo(snr, pfa, 16, 40_000, seed=2, swerling=1)
    assert np.allclose(mc1, cfar_pd_swerling1(snr, pfa, 16), atol=0.02)
    assert float(cfar_pd_monte_carlo(np.array([-300.0]), pfa, 16, 400_000, seed=3)[0]) == pytest.approx(pfa, rel=0.25)


def test_report_and_fingerprint_carry_milestone_two(tmp_path):
    from fmcw_radar.report import report, to_markdown

    cfg = apply_overrides(RadarConfig(), {"mimo.n_tx": 2, "mimo.n_rx": 4, "target.angle_deg": 20.0, "chirp.n_chirps": 4,
                                          "extra_targets": [{"kind": "car", "range_m": 8.0}], "leakage.enabled": True,
                                          "rx.hpf_corner_hz": 200e3})
    md = to_markdown(report(cfg, run_statistical(cfg)))
    for word in ("## Targets (milestone 2)", "## Angle (TDM-MIMO virtual array)", "## TX-RX leakage", "Cramer-Rao"):
        assert word in md, word


def _hpf(order: int, corner_hz: float = 200e3, **ov):
    """The high-pass and blanking mechanism tests run on the pair they were
    built on -- a 10 dBm transmitter and 25 dB of isolation, -15 dBm of direct
    leakage at the receiver -- so their thresholds keep their meaning.  What
    the band's sourced figures give (12 dBm, 20 dB: -8 dBm) is
    test_sourced_leakage_level_and_what_the_high_pass_must_do's subject."""
    return _leak(**{"rx.hpf_corner_hz": corner_hz, "rx.hpf_order": order, "frontend.tx_power_dbm": 10.0,
                    "leakage.isolation_db": 25.0, "frontend.compression": False, **ov})


def test_sourced_leakage_level_and_what_the_high_pass_must_do():
    """With the radar chip's 12 dBm and a board array's 20 dB of isolation the
    direct leakage is -8 dBm at the receiver, 7 dB over the old placeholder
    pair (10 dBm, 25 dB).  A first-order 200 kHz high-pass then leaves it at
    the ADC's full scale -- it clips for good, blanked or not; a second-order
    one has 28 dB in hand and only the chirp-start transient clips, which the
    recommended blank covers.  That is the linear receiver's picture; with
    the front stage compressing the leakage (the default since 0.2.9) the
    first-order filter has room -- test_compression.py has that side."""
    sourced = lambda order: _leak(**{"rx.hpf_corner_hz": 200e3, "rx.hpf_order": order, "frontend.compression": False})  # noqa: E731
    one, two = leakage_budget(sourced(1)), leakage_budget(sourced(2))
    assert one.terms[0].level_rx_dbm == pytest.approx(-8.0)
    assert one.adc_headroom_db == pytest.approx(0.0, abs=0.1) and two.adc_headroom_db == pytest.approx(27.9, abs=0.1)
    assert one.transient_step_v == pytest.approx(7.2 * 10.0 ** (7.0 / 20.0), rel=0.01)      # the step grows with the level
    # ... so the budget names no blank for it (there is none that helps) and says why; a blank the old
    # formula would have named (the step under full scale plus a time constant, 3.8 us) leaves it clipping
    assert one.steady_clipping and one.blank_recommended_s == 0.0 and one.required_hpf_atten_db == pytest.approx(6.0, abs=0.1)
    assert any("none, the steady leakage clips" in lab for lab, _, _ in one.as_rows())
    tm1 = run_time(apply_overrides(sourced(1), {"rx.blank_s": 3.8e-6}), phase_noise=False, noise=False)
    assert tm1.extras["clipped_fraction_after_blanking"] > 0.5
    assert not two.steady_clipping and two.blank_recommended_s == pytest.approx(5.47e-6, abs=0.02e-6)
    cb = apply_overrides(sourced(2), {"rx.blank_s": two.blank_recommended_s})
    tm2 = run_time(cb, phase_noise=False, noise=False)
    a_fs, step = tm2.extras["fullscale_v"], tm2.extras["adc_step_v"]
    sat = (np.abs(tm2.frame.real) >= a_fs - step / 2) | (np.abs(tm2.frame.imag) >= a_fs - step / 2)
    assert not np.any(sat[:, cb.n_blank:-5])                 # the start transient is covered ...
    # ... and what is left is the engine's circular brick-wall ringing the next chirp's (now larger) step back
    # into the chirp's last samples: 3 of 1000 here, 1 at the old level (ROADMAP P2 #0: a causal IF filter)
    assert 0 < tm2.extras["clipped_fraction_after_blanking"] <= 5.0 / cb.n_samples
    f = tm2.extras["targets_found"][0]
    assert f is not None and f[0] == pytest.approx(5.0, abs=0.04)


def _far_floor_db(tm) -> float:
    ax, pr = tm.range_profile_axis_m, tm.range_profile_db
    return float(np.mean(pr[(ax > 2.0) & (ax < 4.0)]))


def test_blanked_window_keeps_its_sidelobes_and_pays_the_shorter_record():
    """The window refitted to n - k samples: the same peak sidelobe, a lobe
    wider by n / (n - k), an SNR loss of 10 log10 n / (n - k) against white
    noise (coherent gain of the shorter window).  Zeroing k samples under an
    unchanged window instead leaves a step and raises the sidelobes."""
    n, k = 1000, 80
    w = range_window("hann", n, k)
    assert w.size == n and not np.any(w[:k]) and w[k] == 0.0 and w[k + 1] > 0.0
    assert np.array_equal(range_window("hann", n, 0), range_window("hann", n))
    assert peak_sidelobe_db("hann", n, 16, k) == pytest.approx(peak_sidelobe_db("hann", n, 16), abs=0.1)
    assert mainlobe_width_bins("hann", n, -3.0, 16, k) / mainlobe_width_bins("hann", n, -3.0, 16) == pytest.approx(n / (n - k), rel=0.01)
    assert coherent_gain_db(range_window("hann", n)) - coherent_gain_db(w) == pytest.approx(10 * math.log10(n / (n - k)), abs=0.01)
    zeroed = range_window("hann", n).copy()
    zeroed[:k] = 0.0
    from fmcw_radar.processing.windows import spectrum_db

    bins, s_zeroed = spectrum_db(zeroed, 16)
    _, s_refit = spectrum_db(w, 16)
    far = np.abs(bins) > 40.0                                                   # the window's far sidelobes
    assert np.mean(s_zeroed[far]) > np.mean(s_refit[far]) + 20.0
    with pytest.raises(ValueError):
        range_window("hann", 10, 10)


def test_budget_blanking_rows_follow_the_config():
    lb0 = leakage_budget(_hpf(2))
    assert lb0.blank_s == 0.0 and lb0.blank_loss_db == 0.0 and lb0.blank_recommended_s > 0.0
    # the step: every term's 2 A |sin(pi f_beat T_c)| at the ADC, before the filter
    cfg = _hpf(2)
    step = sum(2.0 * math.sqrt(10 ** ((t.level_adc_dbm - 30) / 10) * 50) * abs(math.sin(math.pi * t.beat_hz * cfg.chirp.duration_s))
               for t in lb0.terms)
    assert lb0.transient_step_v == pytest.approx(step)
    assert lb0.hpf_time_constant_s == pytest.approx(1.0 / (2 * math.pi * 200e3 * math.sin(math.pi / 4)))
    lb = leakage_budget(_hpf(2, **{"rx.blank_s": 4e-6}))
    assert lb.blank_s == 4e-6 and lb.blank_loss_db == pytest.approx(10 * math.log10(1000 / 960), abs=0.02)
    assert leakage_budget(_leak()).blank_recommended_s == 0.0                     # no filter: no transient to blank
    with pytest.raises(ValueError, match="blank_s"):
        _hpf(2, **{"rx.blank_s": 30e-6})


@pytest.mark.parametrize("order", [1, 2, 3])
def test_recommended_blank_covers_the_clipped_run_and_restores_the_floor(order):
    """With the high-pass the ADC clips a run at every chirp's start; the
    budget's recommended blank covers it (nothing clipped survives the
    blank), and the range profile's far floor comes back to the no-leakage
    reference, which the unblanked transient had raised."""
    cfg = _hpf(order)
    rec = leakage_budget(cfg).blank_recommended_s
    tm0 = run_time(cfg, phase_noise=False, noise=False)
    frame = tm0.frame
    a_fs = tm0.extras["fullscale_v"]
    step = tm0.extras["adc_step_v"]
    sat = (np.abs(frame.real) >= a_fs - step / 2) | (np.abs(frame.imag) >= a_fs - step / 2)
    run = max(int(np.flatnonzero(sat[m, :500]).max()) + 1 for m in range(frame.shape[0]))
    assert 0 < run <= rec * cfg.rx.adc_fs_hz < 2.0 * run                     # covered, and not by a silly margin
    cb = apply_overrides(cfg, {"rx.blank_s": rec})
    tm = run_time(cb, phase_noise=False, noise=False)
    # what still clips after the blank is at most the last sample of a chirp: the engine's circular
    # brick-wall IF rings the next chirp's step back into it (the window weighs it ~1e-5)
    assert tm.extras["clipped_fraction_after_blanking"] <= 1.0 / cb.n_samples < tm.extras["clipped_fraction"]
    sat_b = (np.abs(tm.frame.real) >= a_fs - step / 2) | (np.abs(tm.frame.imag) >= a_fs - step / 2)
    assert not np.any(sat_b[:, cb.n_blank:-1])
    assert not np.any(tm.frame[:, :cb.n_blank])
    ref = run_time(cb, phase_noise=False, noise=False, leakage=False)
    # the floor relative to the target's own level, blanked vs the no-leakage reference, vs unblanked
    i_t = int(np.argmin(np.abs(tm.range_profile_axis_m - 5.0)))
    rel = lambda t: _far_floor_db(t) - t.range_profile_db[i_t]                    # noqa: E731
    assert rel(tm) == pytest.approx(rel(ref), abs=3.0)      # the transient's tail under the window's rising edge: ~2 dB left
    if order >= 2:
        # 7.5 dB at order 2, 17.2 dB at order 3 (0.2.25, the filter on the waveform grid; 8.0 and 15.7 dB when it ran at the ADC's rate)
        assert rel(tm0) > rel(tm) + 6.0
    f = tm.extras["targets_found"][0]
    assert f is not None and f[0] == pytest.approx(5.0, abs=0.04)


def test_recommended_blank_counts_what_the_steady_leakage_leaves_of_the_adc_range():
    """The transient has to decay into the range the ADC has left above the
    steady leakage, not under full scale.  A first-order high-pass at 280 kHz
    leaves the sourced leakage 2.9 dB under full scale: the blank is longer
    than the step alone would ask for and still covers the clipped run; at
    240 kHz the two terms in phase reach full scale and no blank is named."""
    near = _leak(**{"rx.hpf_corner_hz": 280e3, "rx.hpf_order": 1, "frontend.compression": False})
    lb = leakage_budget(near)
    assert lb.adc_headroom_db == pytest.approx(2.9, abs=0.1) and not lb.steady_clipping
    a_fs = math.sqrt(10.0 ** ((near.rx.adc_fullscale_dbm - 30.0) / 10.0) * 50.0)
    step_only = lb.hpf_time_constant_s * (math.log(lb.transient_step_v / a_fs) + 1.0)
    assert lb.blank_recommended_s > step_only + 0.9 * lb.hpf_time_constant_s
    tm0 = run_time(near, phase_noise=False, noise=False)
    step = tm0.extras["adc_step_v"]
    sat = (np.abs(tm0.frame.real) >= a_fs - step / 2) | (np.abs(tm0.frame.imag) >= a_fs - step / 2)
    run = max(int(np.flatnonzero(sat[m, :500]).max()) + 1 for m in range(tm0.frame.shape[0]))
    assert 0 < run <= lb.blank_recommended_s * near.rx.adc_fs_hz < 2.0 * run
    lin240 = {"rx.hpf_corner_hz": 240e3, "rx.hpf_order": 1, "frontend.compression": False}
    edge = leakage_budget(_leak(**lin240))
    assert edge.adc_headroom_db > 0.0 and edge.steady_clipping and edge.blank_recommended_s == 0.0
    assert run_time(_leak(**lin240), phase_noise=False, noise=False).extras["clipped_fraction"] > 0.05


def test_blanking_zero_is_the_old_path_bit_for_bit():
    cfg = _hpf(2)
    a = run_time(cfg, phase_noise=False, seed=3)
    b = run_time(apply_overrides(cfg, {"rx.blank_s": 0.0}), phase_noise=False, seed=3)
    assert np.array_equal(a.frame, b.frame) and np.array_equal(a.rd_db, b.rd_db)
    st = run_statistical(apply_overrides(cfg, {"rx.blank_s": 4e-6}))
    assert st.range_res_m / run_statistical(cfg).range_res_m == pytest.approx(1000 / 960, rel=0.01)
    assert st.snr_cell_db == pytest.approx(run_statistical(cfg).snr_cell_db - 10 * math.log10(1000 / 960), abs=0.02)


# ---------------------------------------------------------------- 0.2.34 (fmcw_radar#44): what the leakage costs, for a reader comparing radars

HP2 = {"leakage.enabled": True, "rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2}


def _flat(d, pre=""):
    out = {}
    for k, v in d.items():
        out.update(_flat(v, pre + k + ".") if isinstance(v, dict) else {pre + k: v})
    return out


def test_the_leakage_config_is_the_default_with_the_model_and_its_filter_on():
    """``radar_60g_sensing_leakage.yaml``: three fields away from the default
    and nothing else -- the leakage model, and the second-order 200 kHz
    high-pass an FMCW radar meets it with.  What does not see the leakage is
    the default's, value for value; the SNR moves by the 0.02 dB the
    leakage costs (and the filter's 0.002 dB at the target's beat)."""
    a, b = load_config(REPO / "configs" / "radar_60g_sensing.yaml"), load_config(REPO / "configs" / "radar_60g_sensing_leakage.yaml")
    fa, fb = _flat(config_to_dict(a)), _flat(config_to_dict(b))
    assert {k: (fa[k], fb[k]) for k in fa if fa[k] != fb[k]} == {"leakage.enabled": (False, True), "rx.hpf_corner_hz": (0.0, 200e3), "rx.hpf_order": (1, 2)}
    assert set(fa) == set(fb) and a == RadarConfig() and b == apply_overrides(RadarConfig(), HP2)
    lin = {"lo.engine": "response"}
    ra, rb = rpt.build(apply_overrides(a, lin)), rpt.build(apply_overrides(b, lin))
    assert ra["leakage"] is None and rb["leakage"]["isolation_db"] == 20.0
    for key in ("radar", "inputs", "target", "chirp", "nonlinearity", "angle"):          # what does not see the leakage or the filter
        assert ra[key] == rb[key], key
    snr = ("snr_cell_capped_db", "snr_cell_configured_db")                               # the check itself; the SNRs quoted beside it move
    assert {k: v for k, v in ra["compliance"].items() if k not in snr} == {k: v for k, v in rb["compliance"].items() if k not in snr}
    assert all(0.015 < ra["compliance"][k] - rb["compliance"][k] < 0.025 for k in snr)
    # the LO's noise: the levels ahead of the filter are the default's; what the filter does to them on the map is its own column
    pa, pb = ra["phase_noise"], rb["phase_noise"]
    assert (pa["lo_rms_rad"], pa["residual_rms_rad"]) == (pb["lo_rms_rad"], pb["residual_rms_rad"])
    assert [(r["offset_m"], r["per_bin_dbc"], r["per_cell_dbc"]) for r in pa["floor"]] == [(r["offset_m"], r["per_bin_dbc"], r["per_cell_dbc"]) for r in pb["floor"]]
    assert all(r["map_shift_db"] == 0.0 for r in pa["floor"]) and all(0.0 < r["map_shift_db"] < 0.01 for r in pb["floor"])
    assert ra["detection"]["range_at_pd"]["if_band_range_m"] == rb["detection"]["range_at_pd"]["if_band_range_m"]
    assert 0.015 < ra["detection"]["snr_cell_db"] - rb["detection"]["snr_cell_db"] < 0.025
    assert rb["detection"]["range_at_pd"]["snr_limited_range_m"] == pytest.approx(ra["detection"]["range_at_pd"]["snr_limited_range_m"], abs=0.01)


def test_what_the_leakage_costs_and_the_isolation_it_would_take():
    """The default radar, 20 dB of isolation (the band's sourced figure: a
    board array without an isolation structure), -16 dBm of leakage at the
    receiver, a beat of 8 kHz.

    Behind a second-order 200 kHz high-pass the leakage is gone ahead of the
    stages that would compress on it: 0.02 dB off the SNR, 4 dB under the
    out-of-band compression point, and it would take the isolation down to
    13.6 dB to cost 1 dB.  Without the filter it is an in-band signal 18 dB
    over the in-band point: 7.2 dB off the SNR, 1 dB only from 35.6 dB of
    isolation up.  The filter is worth 22 dB of isolation -- the number a
    comparison with a waveform that cannot filter its leakage needs."""
    cfg = apply_overrides(RadarConfig(), HP2)
    bare = apply_overrides(RadarConfig(), {"leakage.enabled": True})
    assert leakage_snr_loss_db(cfg) == pytest.approx(0.018, abs=0.002) and leakage_snr_loss_db(bare) == pytest.approx(7.19, abs=0.02)
    assert leakage_snr_loss_db(RadarConfig()) == 0.0                                    # the model off: nothing
    # the loss is the budget's own: with and without the receiver's compression by the leakage
    st = run_statistical(apply_overrides(cfg, {"lo.engine": "response"}))
    off = link_budget(cfg).snr_cell_db
    assert off - st.snr_cell_db == pytest.approx(leakage_snr_loss_db(cfg), abs=1e-9)
    need, need_bare = isolation_for_snr_loss(cfg), isolation_for_snr_loss(bare)
    assert need == pytest.approx(13.58, abs=0.02) and need_bare == pytest.approx(35.58, abs=0.02)
    for c, n in ((cfg, need), (bare, need_bare)):
        at = lambda iso: leakage_snr_loss_db(apply_overrides(c, {"leakage.isolation_db": iso}))    # noqa: E731
        assert at(n) == pytest.approx(1.0, abs=1e-6) and at(n - 3.0) > 1.5 > 1.0 > at(n + 3.0)
    assert isolation_for_snr_loss(cfg, 3.0) < need < isolation_for_snr_loss(cfg, 0.1)
    d = leakage_need(cfg)
    assert (d["isolation_db"], d["isolation_source"], d["level_rx_dbm"], d["beat_hz"], d["hpf"]) == (20.0, "spec", -16.0, 8000.0, True)
    assert (d["path_delay_s"], d["path_delay_source"]) == (0.2e-9, "assumed")
    assert (d["p1db_kind"], d["without_hpf"]["p1db_kind"]) == ("out of band", "in band")
    assert d["p1db_margin_db"] == pytest.approx(4.0) and d["without_hpf"]["p1db_margin_db"] == pytest.approx(-18.0)
    assert d["isolation_needed_db"] == need and d["isolation_spare_db"] == pytest.approx(20.0 - need) and d["isolation_spare_db"] > 6.0
    assert d["without_hpf"]["isolation_needed_db"] == need_bare and d["without_hpf"]["isolation_spare_db"] == pytest.approx(20.0 - need_bare)
    assert d["without_hpf"]["isolation_needed_db"] - d["isolation_needed_db"] == pytest.approx(22.0, abs=0.1)
    assert d["snr_loss_db"] == leakage_snr_loss_db(cfg) and d["without_hpf"]["snr_loss_db"] == leakage_snr_loss_db(bare)
    assert leakage_need(RadarConfig()) is None
    # a config with no filter of its own: both sides are the same radar
    nb = leakage_need(bare)
    assert nb["hpf"] is False and {k: nb[k] for k in nb["without_hpf"]} == nb["without_hpf"]
    # at 40 dB (the isolation structure of the same paper) even the bare receiver is within 0.1 dB
    assert leakage_snr_loss_db(apply_overrides(bare, {"leakage.isolation_db": 40.0})) < 0.1


def test_the_report_says_what_the_leakage_costs_and_tags_the_path_delay():
    cfg = apply_overrides(RadarConfig(), {**HP2, "lo.engine": "response"})
    rep = rpt.build(cfg)
    lk = rep["leakage"]
    want = leakage_need(cfg)
    assert {k: lk[k] for k in want} == want and lk["p1db_kind"] == "out of band" and lk["adc_headroom_db"] > 30.0
    rows = {r["term"]: r for r in lk["rows"]}
    assert rows["direct leakage: path delay"]["value"] == pytest.approx(0.2) and rows["direct leakage: path delay"]["unit"] == "ns (source: assumed)"
    assert rows["TX-RX isolation"]["unit"] == "dB (source: spec)"
    md = rpt.to_markdown(rep)
    assert "takes **0.02 dB** off the SNR" in md and "It would cost 1 dB at 13.6 dB of isolation: 6.4 dB to spare" in md
    assert "Without the IF high-pass the same leakage is an in-band signal: 7.19 dB off the SNR" in md and "(15.6 dB short)" in md
    assert "The filter is worth 22.0 dB of isolation" in md and "path delay of 0.2 ns, source: assumed" in md
    bare = rpt.to_markdown(rpt.build(apply_overrides(RadarConfig(), {"leakage.enabled": True, "lo.engine": "response"})))
    assert "There is no IF high-pass in this configuration" in bare and "takes **7.19 dB** off the SNR" in bare
    # a reflector's delay follows its range: only the direct path's is a number of its own
    two = leakage_budget(apply_overrides(cfg, {"leakage.reflector_range_m": 0.02})).as_rows()
    assert [lab for lab, _, _ in two if "path delay" in lab] == ["direct leakage: path delay"]
    assert "leakage" in rep and rpt.build(apply_overrides(RadarConfig(), {"lo.engine": "response"}))["leakage"] is None

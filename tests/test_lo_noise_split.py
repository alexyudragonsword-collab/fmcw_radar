"""Who carries which part of the LO's noise (ROADMAP P1 #1(b)).

The cycle-accurate chirp engine and the linear LO profile describe the same
loop.  Acceptance: on a ramp, with its noise sources on, the engine's
carrier phase has the profile's spectrum; with them off, what is left is
the profile's quantisation terms as a deterministic pattern; the time
engine synthesises from the profile only what the curve does not already
carry, so the LO's noise floor on the map is the closed form's whichever
way the two share it -- and 1.5 dB above it when the curve is laid over
the whole profile, which is what the time engine did before.
"""

import numpy as np
import pytest

from fmcw_radar.chirp import ChirpEngine
from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine.timedomain import beat_frame, measured_pn_sidelobes, run_time
from fmcw_radar.lo import LOProfile
from fmcw_radar.phase_noise import RangeCorrelation

OFFSETS = np.array([1e5, 3e5, 1e6, 3e6, 1e7])


def _ramp_psd(chirp, psi, skip=300, first=2):
    """L(f) [dBc/Hz] of a carrier phase trajectory over the ramps: each ramp
    less its flyback transient, linearly detrended, Hann periodogram, averaged."""
    acc, count = 0.0, 0
    for k in range(first, chirp.n_chirps):
        x = psi[k * chirp.pri_cycles + skip:k * chirp.pri_cycles + chirp.n_ramp]
        t = np.arange(x.size)
        x = x - np.polyval(np.polyfit(t, x, 1), t)
        w = np.hanning(x.size)
        acc = acc + np.abs(np.fft.rfft(x * w)) ** 2 / (chirp.fref_hz * np.sum(w ** 2))
        count += 1
    f = np.fft.rfftfreq(x.size, d=1.0 / chirp.fref_hz)
    return np.array([10.0 * np.log10(np.mean((acc / count)[(f > q / 1.25) & (f < q * 1.25)])) for q in OFFSETS])


@pytest.fixture(scope="module")
def cfg():
    return apply_overrides(RadarConfig(), {"chirp.n_chirps": 16, "lo.dp_cal": "none"})


@pytest.fixture(scope="module")
def quiet(cfg):
    return ChirpEngine(cfg).run(noise=False)


@pytest.fixture(scope="module")
def noisy(cfg):
    return ChirpEngine(cfg).run(noise=True, seed=7)


def test_profile_breakdown_sums_to_the_total_and_can_be_split(cfg):
    prof = LOProfile.from_config(cfg)
    assert set(prof.components) == {"ref", "dco", "tdc_quant", "dco_quant", "tdc_jitter"}
    assert np.allclose(sum(prof.components.values()), prof.s_phi, rtol=1e-9)
    rest = prof.without("tdc_quant", "dco_quant")
    assert np.allclose(rest.s_phi, prof.components["ref"] + prof.components["dco"] + prof.components["tdc_jitter"], rtol=1e-6)
    assert set(rest.components) == {"ref", "dco", "tdc_jitter"}                 # the jitter is noise: it stays in the profile
    assert prof.without("nothing such") is prof
    # in band the TDC's quantisation is -85 of the -79.6 dBc/Hz at 1 MHz: 1.4 dB of it
    assert prof.l_dbc(np.array([1e6]))[0] - rest.l_dbc(np.array([1e6]))[0] == pytest.approx(1.4, abs=0.3)
    split = 0.5 * cfg.lo.fref_hz
    hi = prof.above(split)
    assert hi.psd(np.array([1e6, 0.9 * split]))[1] < 1e-200 and hi.psd(np.array([2 * split]))[0] == pytest.approx(prof.psd(np.array([2 * split]))[0])
    assert hi.rms_phase_rad(split, 2.5e9) == pytest.approx(prof.rms_phase_rad(split, 2.5e9), rel=1e-3)
    # a profile exported by tools/export_lo_profile.py carries the breakdown: the same split as the live one
    from conftest import REPO

    file_prof = LOProfile.from_config(apply_overrides(cfg, {"lo.profile": str(REPO / "src/fmcw_radar/data/clock_profiles/adpll_15g_fingerprint.yaml")}))
    assert set(file_prof.components) == set(prof.components)
    f = np.array([1e5, 1e6, 1e7])
    assert np.allclose(file_prof.without("tdc_quant", "dco_quant").l_dbc(f), rest.l_dbc(f), atol=0.05)
    # a profile with nothing to split (a foreign file under the ideal chirp engine) is returned as it is
    bare = LOProfile.from_config(apply_overrides(cfg, {"lo.profile": "vendor/mmw60/data/clock_profiles/pllsim_wu19_x10_60p48g_floor150.yaml",
                                                      "lo.engine": "ideal"}))
    assert bare.components is None and bare.without("tdc_quant") is bare


def test_foreign_noise_file_is_counted_once_by_both_engines():
    """ROADMAP P1 #1(b): with a noise file and the event chirp engine the time
    engine used to lay the curve's quantisation over the whole file and the
    statistical engine counted none of it -- the floor 1-5 m from the target
    read 10-15 dB over the closed form.  Now the closed form has the
    generator's quantisation and the time engine leaves it to the curve.
    What remains is the curve's undithered pattern (nothing dithers the TDC
    under a file: its ghosts sit at 3-5 m), a dB or two over the closed form."""
    from fmcw_radar.chirp import ChirpEngine
    from fmcw_radar.engine.timedomain import measured_pn_sidelobes

    cfg = apply_overrides(RadarConfig(), {"lo.profile": "vendor/mmw60/data/clock_profiles/pllsim_wu19_x10_60p48g_floor150.yaml"})
    quiet = ChirpEngine(cfg).run(noise=False, n_chirps=32)
    offs = (1.0, 2.0, 3.0, 5.0)
    m = measured_pn_sidelobes(cfg, offs, n_chirps=32, seed=3, window_name="blackman", half_bins=12, chirp=quiet)
    gap = [m[o]["measured_dbc"] - m[o]["closed_form_dbc"] for o in offs]
    assert all(-1.0 < g < 2.5 for g in gap) and 0.0 < float(np.mean(gap)) < 1.8, gap
    assert m[1.0]["closed_form_dbc"] > -67.0                                        # was -75.9 without the generator's terms


def test_noisy_curve_is_the_profile_on_a_ramp(cfg, noisy):
    """Cycle-accurate against linear: the engine's carrier phase over the
    ramps has the profile's L(f) within 1.5 dB from 100 kHz to 10 MHz."""
    prof = LOProfile.from_config(cfg)
    assert noisy.noise and noisy.lo_noise_in_curve == "all" and noisy.osc_phase_dco_rad is not None
    got = _ramp_psd(noisy, noisy.phase_err_carrier_rad())
    assert np.allclose(got, prof.l_dbc(OFFSETS), atol=1.5), got - prof.l_dbc(OFFSETS)


def test_tuning_word_alone_is_not_the_noisy_phase(noisy):
    """The frequency error is the tuning word's: it carries the loop's
    reaction to the DCO's noise, not the noise.  Integrated alone it reads
    tens of dB too much at low offsets -- what ``phase_err_carrier_rad`` did
    with the noise on before it added the DCO's own phase."""
    tuning_only = 2.0 * np.pi * noisy.mult * np.cumsum(noisy.f_err_dco_hz) / noisy.fref_hz
    excess = _ramp_psd(noisy, tuning_only) - _ramp_psd(noisy, noisy.phase_err_carrier_rad())
    assert excess[0] > 20.0 and excess[1] > 8.0                         # 100 kHz, 300 kHz
    assert np.all(excess[3:] < -2.0)                                    # and too little above the loop bandwidth


def test_quiet_curve_is_the_quantisation_terms(cfg, quiet):
    """Noise off, the curve on a ramp is the TDC's and the DCO's quantisation
    and nothing else: the profile's two quantisation terms as a pattern."""
    prof = LOProfile.from_config(cfg)
    assert not quiet.noise and quiet.lo_noise_in_curve == "quantisation" and quiet.osc_phase_dco_rad is None
    q = prof.components["tdc_quant"] + prof.components["dco_quant"]
    want = 10.0 * np.log10(np.interp(OFFSETS, prof.f_hz, q) / 2.0)
    got = _ramp_psd(quiet, quiet.phase_err_carrier_rad())
    assert np.allclose(got, want, atol=2.0), got - want
    assert ChirpEngine(apply_overrides(cfg, {"lo.engine": "ideal"})).run().lo_noise_in_curve == "none"
    assert ChirpEngine(apply_overrides(cfg, {"lo.engine": "response"})).run(noise=True, seed=1).lo_noise_in_curve == "unverified"


def test_time_engine_counts_the_lo_noise_once(cfg, quiet, noisy):
    """The LO's floor on the range profile, 1 to 5 m from the target, against
    the closed form of the whole profile: the profile alone, the quiet curve
    with the profile less its quantisation, the noisy curve with the profile
    above fref / 2 -- all three within 1.3 dB at every offset and 0.8 dB on
    average.  The quiet curve over the *whole* profile reads 1.5 dB high."""
    c = apply_overrides(cfg, {"processing.window_range": "blackman"})
    offs = (1.0, 2.0, 3.0, 5.0)

    def gap(**kw):
        m = measured_pn_sidelobes(c, offs, n_chirps=16, seed=3, half_bins=12, **kw)
        return np.array([m[o]["measured_dbc"] - m[o]["closed_form_dbc"] for o in offs])

    for kw in ({}, {"chirp": quiet}, {"chirp": noisy}):
        g = gap(**kw)
        assert np.all(np.abs(g) < 1.3) and abs(g.mean()) < 0.8, (kw.keys(), g)
    # the old behaviour: the caller's whole profile on top of a curve that already is its quantisation
    whole = RangeCorrelation(LOProfile.from_config(c), c.tau_s())
    frame, info = beat_frame(c, quiet, noise=False, phase_noise=True, quantise=False, seed=3, n_chirps=16, rc=whole)
    assert info["lo_noise_split"] == "profile: the caller's"
    ref, _ = beat_frame(c, quiet, noise=False, phase_noise=True, quantise=False, seed=3, n_chirps=16)
    assert "quantisation" in _["lo_noise_split"] and "everything else" in _["lo_noise_split"]

    def floor(fr):
        p = np.mean(np.abs(np.fft.fft(fr * np.blackman(fr.shape[-1]), axis=-1)) ** 2, axis=0)
        k = int(np.argmax(p))
        return 10.0 * np.log10(np.mean(p[k + 40:k + 200]) / p[k])

    assert floor(frame) - floor(ref) > 1.0


def test_time_engine_says_who_carries_what(cfg, noisy):
    small = apply_overrides(cfg, {"chirp.n_chirps": 2})
    # the default when the LO is the vendored loop: its cycle-accurate noise, the TDC's jitter dithering the quantisation
    assert run_time(small).extras["lo_noise_split"].startswith("curve: the loop to fref/2")
    assert run_time(small, chirp_noise=False).extras["lo_noise_split"].startswith("curve: TDC and DCO quantisation")
    filed = apply_overrides(small, {"lo.profile": "data/clock_profiles/adpll_15g_fingerprint.yaml"})
    # a file: the curve stays deterministic (nothing dithers the TDC) and the profile is split like the live one
    assert run_time(filed).extras["lo_noise_split"] == "curve: TDC and DCO quantisation (cycle-accurate); profile: everything else"
    foreign = apply_overrides(small, {"lo.profile": "vendor/mmw60/data/clock_profiles/pllsim_wu19_x10_60p48g_floor150.yaml"})
    assert run_time(foreign).extras["lo_noise_split"] == "curve: TDC and DCO quantisation (cycle-accurate); profile: everything else"
    assert run_time(apply_overrides(small, {"lo.engine": "ideal"})).extras["lo_noise_split"] == "profile: everything"
    assert run_time(small, phase_noise=False).extras["lo_noise_split"] == "no phase noise"
    lin = ChirpEngine(apply_overrides(small, {"lo.engine": "response"})).run(noise=True, seed=1)
    with pytest.raises(ValueError, match="cannot be split"):
        run_time(apply_overrides(small, {"lo.engine": "response"}), lin)
    # same seed, same frame: the noisy chirp is seeded like the frame
    a = run_time(small, chirp_noise=True, seed=5)
    b = run_time(small, chirp_noise=True, seed=5)
    assert np.array_equal(a.frame, b.frame)

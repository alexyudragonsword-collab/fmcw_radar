"""The subtractive TDC dither (pll_simulator#80, ``lo.tdc_dither_lsb``): off by
default, and what it does to this radar when it is on.

A known pseudo-random offset, uniform over ``tdc_dither_lsb`` TDC LSB, is
injected at the TDC (a DTC on the reference path) and taken out again
digitally.  The 12.2 ps TDC's quantisation, which a ramp sweeps across its
bins the same way every time, becomes noise: the phase-noise level stays
the linear profile's, the part that repeats ramp after ramp goes, and with
it the ghost targets a frame integrates.  The default is off because no
source says the 60 GHz ADPLL the TDC's resolution is read from has one.
"""

import numpy as np
import pytest
from test_lo_noise_split import OFFSETS, _coherent_fraction_db, _ramp_psd

from fmcw_radar.chirp import ChirpEngine
from fmcw_radar.config import RadarConfig, apply_overrides, load_config
from fmcw_radar.engine.statistical import run_statistical
from fmcw_radar.engine.timedomain import measured_pn_sidelobes, run_time
from fmcw_radar.lo import CURVE_TERMS, LOProfile, build_adpll, dither_freq_dev_rms_hz, parked_lo
from fmcw_radar.report import report, to_markdown

from conftest import REPO


@pytest.fixture(scope="module")
def cfg():
    return apply_overrides(RadarConfig(), {"chirp.n_chirps": 16, "lo.dp_cal": "none"})


@pytest.fixture(scope="module")
def dith(cfg):
    return apply_overrides(cfg, {"lo.tdc_dither_lsb": 1.0})


def test_dither_is_off_by_default_and_reaches_the_loop_when_set():
    c = RadarConfig()
    assert c.lo.tdc_dither_lsb == 0.0 and c.lo.tdc_dither_gain_error == 0.0
    tdc = build_adpll(c).cfg.tdc
    assert tdc.dither_lsb == 0.0 and tdc.dither_gain_error == 0.0
    on = build_adpll(apply_overrides(c, {"lo.tdc_dither_lsb": 2.0, "lo.tdc_dither_gain_error": 0.01})).cfg.tdc
    assert on.dither_lsb == 2.0 and on.dither_gain_error == 0.01
    for bad in ({"lo.tdc_dither_lsb": -1.0}, {"lo.tdc_dither_gain_error": 0.01}, {"lo.tdc_dither_lsb": 1.0, "lo.tdc_dither_gain_error": 1.5}):
        with pytest.raises(ValueError):
            apply_overrides(c, bad)
    assert load_config(REPO / "configs" / "radar_60g_dither.yaml").lo.tdc_dither_lsb == 1.0
    assert "tdc_dither_mod" not in LOProfile.from_config(c).components          # nothing of it in the default's profile


def test_one_lsb_of_dither_takes_the_ghost_targets_out_of_the_default_frame():
    """The default radar (12.2 ps TDC, 1 ps of jitter, 64 chirps, a human at
    5 m): 2.75 ghost detections a frame, the strongest at -37.3 dBc.  With
    1 LSB of subtractive dither 0.002, the strongest -50.9 dBc; with 3 LSB
    none over the search limit.  The undithered pattern the report quotes
    is still the loop's with the dither off (-34.1 dBc at -10.3 m), and the
    phase-noise level does not move: L(1 MHz) -75.89 dBc/Hz either way."""
    off = run_statistical(RadarConfig())
    assert off.cfar["ghost_detections_per_frame"] == pytest.approx(2.75, abs=0.02)
    assert "tdc_dither_lsb" not in off.nonlinearity
    one = run_statistical(apply_overrides(RadarConfig(), {"lo.tdc_dither_lsb": 1.0}))
    assert one.cfar["ghost_detections_per_frame"] < 0.02
    assert all(level < -48.0 for _, level in one.nonlinearity["ghosts"])
    assert one.nonlinearity["tdc_dither_lsb"] == 1.0 and one.nonlinearity["ghost_noise_on"]
    assert one.nonlinearity["ghosts_quiet"] == off.nonlinearity["ghosts_quiet"]              # the same undithered pattern
    assert one.nonlinearity["ghosts_quiet"][0][1] == pytest.approx(-34.1, abs=0.2)
    three = run_statistical(apply_overrides(RadarConfig(), {"lo.tdc_dither_lsb": 3.0}))
    assert three.nonlinearity["ghosts"] == [] and three.cfar["ghost_detections_per_frame"] == 0.0
    l_off = float(LOProfile.from_config(RadarConfig()).l_dbc(1e6))
    l_one = float(LOProfile.from_config(apply_overrides(RadarConfig(), {"lo.tdc_dither_lsb": 1.0})).l_dbc(1e6))
    assert l_off == pytest.approx(-75.89, abs=0.01) and l_one == pytest.approx(l_off, abs=0.02)
    assert one.pn_rms_rad == pytest.approx(off.pn_rms_rad, rel=2e-3)


@pytest.mark.parametrize("noise", [True, False])
def test_dithered_ramps_are_the_profiles_noise(dith, noise):
    """pll_simulator#80's acceptance on this library's loop.  With 1 LSB of
    dither the error no longer repeats ramp after ramp -- over 14 ramps the
    coherent fraction is -10 to -16 dB from 300 kHz up (random: -11.5; -1.3
    dB at 300 kHz without the dither) -- and its level is the profile's
    within 0.6 dB, on the range profile within 0.5 dB.  The dither is the
    loop's, not a noise source: all of this holds with the noise off too,
    where the curve is the quantisation terms and what the subtraction
    leaves (``lo.CURVE_TERMS``)."""
    prof = LOProfile.from_config(dith)
    n = ChirpEngine(dith).run(noise=noise, seed=7)
    assert n.tdc_dither_lsb == 1.0 and n.lo_noise_in_curve == ("all" if noise else "quantisation")
    psi = n.phase_err_carrier_rad()
    coherent, ramps = _coherent_fraction_db(n, psi)
    assert ramps == 14 and np.all(coherent[1:] < -9.0), coherent
    if noise:
        want = prof.l_dbc(OFFSETS)
    else:
        carried = sum(prof.components[k] for k in CURVE_TERMS if k in prof.components)
        want = 10.0 * np.log10(np.interp(OFFSETS, prof.f_hz, carried) / 2.0)
    level = _ramp_psd(n, psi) - want
    assert np.all(np.abs(level[1:]) < 1.0) and abs(level[0]) < 2.0, level
    offs = (1.0, 2.0, 3.0, 5.0)
    m = measured_pn_sidelobes(apply_overrides(dith, {"processing.window_range": "blackman"}), offs, n_chirps=16, seed=3,
                              half_bins=12, chirp=n)
    gap = np.array([m[o]["measured_dbc"] - m[o]["closed_form_dbc"] for o in offs])
    assert np.all(np.abs(gap) < 1.0) and abs(gap.mean()) < 0.5, gap


def test_profile_carries_what_the_subtraction_leaves(dith):
    """Two terms the dither adds to the loop's noise, both on the TDC's path.
    ``tdc_dither_mod``: the TDC reads against the nominal DCO period while
    the ramp holds the DCO off it -- without the dither a pattern every ramp
    repeats, with it noise, (dev / f_dco)^2 (1 + 1 / (t_res f_dco)^2) of the
    quantisation: -19.4 dB for the unweighted sawtooth, -25.6 dB here
    because the Hann range window weights the ramp's middle, where the
    deviation is least (141 MHz RMS, not 289).  ``tdc_dither_gain``: the
    DTC's gain error, eps^2 of the dither's own power."""
    prof = LOProfile.from_config(dith)
    assert set(prof.components) == {"ref", "dco", "tdc_quant", "dco_quant", "tdc_jitter", "tdc_dither_mod"}
    assert np.allclose(sum(prof.components.values()), prof.s_phi, rtol=1e-9)
    dev = dither_freq_dev_rms_hz(dith)
    assert dev == pytest.approx(141.4e6, rel=0.01)
    assert dither_freq_dev_rms_hz(apply_overrides(dith, {"processing.window_range": "rect"})) == pytest.approx(1e9 / np.sqrt(12.0), rel=1e-3)
    i = int(np.argmin(np.abs(prof.f_hz - 1e5)))
    ratio = prof.components["tdc_dither_mod"][i] / prof.components["tdc_quant"][i]
    f_dco, t_res = dith.dco_center_hz, dith.lo_value("tdc_res_s")[0]
    assert ratio == pytest.approx((dev / f_dco) ** 2 * (1.0 + 1.0 / (t_res * f_dco) ** 2), rel=0.02)
    assert 10.0 * np.log10(ratio) == pytest.approx(-25.6, abs=0.2)
    assert np.all(prof.components["tdc_dither_mod"][prof.f_hz > 0.5 * dith.lo.fref_hz] == 0.0)
    rest = prof.without(*CURVE_TERMS)
    assert set(rest.components) == {"ref", "dco", "tdc_jitter"}
    eps = LOProfile.from_config(apply_overrides(dith, {"lo.tdc_dither_gain_error": 0.1}))
    gain = eps.components["tdc_dither_gain"][i] / eps.components["tdc_quant"][i]
    assert gain == pytest.approx(0.1 ** 2, rel=0.05)                              # a 1 LSB dither has the quantisation's power


def test_parked_lo_wants_three_lsb():
    """The LO parked at an integer multiple of the reference (CW, the idle
    time between ramps): 1 LSB of dither brings the cycle-accurate loop from
    +14.9 dB over the linear analysis to +2.8 dB, not to it -- 12.2 ps is
    5.46 codes a DCO period, the bin at the DCO's edge is 0.46 LSB wide, and
    the subtractive dither's whiteness wants equal bins (pll_simulator
    measured the same).  3 LSB: +0.65 dB.  The loop's own test follows:
    0.30 bin of RMS dither at 1 LSB is still flagged, 0.87 at 3 LSB is not."""
    fq = np.array([3e4, 1e5, 3e5])

    def excess(lsb):
        c = apply_overrides(RadarConfig(), {"lo.tdc_dither_lsb": lsb})
        pll = build_adpll(c)
        ana = np.asarray(pll.analyze(fq).pn_breakdown["total"])
        sim = pll.simulate(200000, noise=True, seed=3)
        s = np.interp(fq, np.asarray(sim.f_psd), np.asarray(sim.s_phi_psd))
        return float(np.mean(10.0 * np.log10(s / ana))), parked_lo(c)

    off, k0 = excess(0.0)
    one, k1 = excess(1.0)
    three, k3 = excess(3.0)
    assert off > 12.0 and 1.5 < one < 4.0 and abs(three) < 1.5, (off, one, three)
    assert k0["dead_zone_center"] and k1["dead_zone_center"] and not k3["dead_zone_center"]
    assert k1["dither_bins"] == pytest.approx(0.30, abs=0.01) and k3["dither_bins"] == pytest.approx(0.87, abs=0.01)


def test_dither_works_under_a_noise_file_too():
    """ROADMAP P1 #1(b): with another LO's noise file the chirp generator
    runs with its own noise off, and nothing dithered its TDC -- the ghosts
    were the undithered pattern (-34.1 dBc, 2.96 detections a frame under
    the x10 file).  The subtractive dither is on with the noise off: the
    frame's coherent spurs are then read off the dithered ramps, 0.002 a
    frame, and the profile gains the dither's term beside the generator's
    quantisation."""
    x10 = load_config(REPO / "configs" / "radar_60g_x10lo.yaml")
    bare = run_statistical(x10)
    assert "ghost_chirps" not in bare.nonlinearity and bare.cfar["ghost_detections_per_frame"] > 2.5
    c = apply_overrides(x10, {"lo.tdc_dither_lsb": 1.0})
    st = run_statistical(c)
    assert st.nonlinearity["ghost_chirps"] == 63 and st.nonlinearity["ghost_noise_on"] is False
    assert st.cfar["ghost_detections_per_frame"] < 0.02 and all(level < -47.0 for _, level in st.nonlinearity["ghosts"])
    assert set(LOProfile.from_config(c).components) == {"file", "tdc_quant", "dco_quant", "tdc_dither_mod"}
    md = to_markdown(report(c, st))
    assert "with the loop's noise off (the LO's noise is a file's; the subtractive dither is the loop's and stays on)" in md
    small = apply_overrides(c, {"chirp.n_chirps": 2})
    assert run_time(small).extras["lo_noise_split"] == "curve: TDC and DCO quantisation (cycle-accurate); profile: everything else"


def test_the_loops_note_on_an_undithered_ramp_reaches_the_report():
    """pllsim's ``simulate()`` says when a modulated TDC loop has under half a
    bin of RMS dither: the quantisation follows the modulation and repeats
    with it.  The default (0.09 bin) and 1 LSB (0.30 bin) get the note, 2
    LSB (0.58 bin) does not; the report prints it under the chirp."""
    def notes(lsb):
        c = apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, "lo.tdc_dither_lsb": lsb})
        st = run_statistical(c)
        return [n for n in st.chirp["notes"] if n.startswith("TDC quantization follows the modulation")], to_markdown(report(c, st))

    got, md = notes(0.0)
    assert len(got) == 1 and "0.09 TDC bins of RMS dither" in got[0]
    assert "The loop's own notes on this chirp run:" in md and "> TDC quantization follows the modulation" in md
    got, md = notes(1.0)
    assert len(got) == 1 and "0.30 TDC bins" in got[0] and "1 LSB of subtractive TDC dither" in md
    got, md = notes(2.0)
    assert got == [] and "TDC quantization follows the modulation" not in md
    ideal = run_statistical(apply_overrides(RadarConfig(), {"chirp.n_chirps": 3, "lo.engine": "ideal"}))
    assert ideal.chirp is None or not ideal.chirp.get("notes")

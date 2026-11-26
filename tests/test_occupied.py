"""The chirp's occupied band, measured as 47 CFR 2.1049 defines it (0.2.35,
fmcw_radar#46).

FCC 23-35 para. 62 has a 60 GHz radar's occupied bandwidth measured as part
of its compliance measurements; this library had judged the tiers on the
commanded sweep and said the rule gave no way to measure it.  The band is
now measured from the frequency the LO actually produced and reported beside
the verdict -- which stays on the commanded sweep, because for a linear
sweep that is the wider band of the two."""

import dataclasses

import numpy as np
import pytest

from fmcw_radar import report as rpt
from fmcw_radar import sources
from fmcw_radar.chirp import ChirpEngine
from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.link import chirp_occupied_band, compliance_check, occupied_band
from fmcw_radar.link import compliance as comp
from fmcw_radar.link.occupied import occupied_band_from_spectrum

PCT = sources.number("fcc2.occupied_bandwidth.power_outside_each_limit_pct").value


def _traj(cfg, n_chirps=3):
    ch = ChirpEngine(cfg).run(noise=False, n_chirps=n_chirps)
    f = ch.mult * (np.asarray(ch.f_cmd_dco_hz) + np.asarray(ch.f_err_dco_hz))
    return ch, f[ch.pri_cycles:]                               # the start-up ramp left out


def test_the_share_outside_each_limit_is_the_rules_number():
    """Half a percent of the mean power outside each limit (47 CFR 2.202(a)
    and 2.1049, the same sentence), read from the source table and through
    it from spec_sources; the two statements about FCC 23-35 para. 62 are
    read word for word the same way."""
    e = sources.number("fcc2.occupied_bandwidth.power_outside_each_limit_pct")
    assert (e.value, e.unit, e.source) == (0.5, "%", "spec") and "0.5 percent of the total mean power" in e.quote
    assert e.upstream == "spec_sources:fcc2.occupied_bandwidth#power_outside_each_limit_pct"
    assert sources.upstream_value(e.upstream) == 0.5
    q, c = (sources.number(f"fcc15255.radar_occupied_bandwidth.{k}") for k in ("quantity", "codified"))
    assert q.value == sources.upstream_value(q.upstream) == "occupied bandwidth (47 CFR 2.1049)"
    assert c.value == sources.upstream_value(c.upstream) and "not in the rule text" in c.value


def test_a_statement_that_is_not_its_upstreams_word_for_word_fails_to_load(tmp_path):
    text = sources.SOURCES_FILE.read_text(encoding="utf-8")
    assert "the occupied-bandwidth sentence is in R&O para. 62, not in the rule text" in text
    bad = tmp_path / "sources.yaml"
    bad.write_text(text.replace("is in R&O para. 62, not in the rule text", "is in the rule text"), encoding="utf-8")
    with pytest.raises(ValueError, match="is not its upstream's"):
        sources.load_sources(bad)
    bad.write_text(text.replace("    value: 0.5\n    unit: \"%\"", "    value: 1.0\n    unit: \"%\""), encoding="utf-8")
    with pytest.raises(ValueError, match="is not its upstream's"):
        sources.load_sources(bad)


def test_a_linear_sweep_occupies_all_but_the_outer_share_of_itself():
    """The power of a linear sweep is spread evenly over it: the share
    outside each limit lies in that share of the sweep at each end.  The
    occupied band is the sweep less 2 x 0.5 % -- narrower than the commanded
    one, not wider."""
    b = 4.0e9
    f = -0.5 * b + b * (np.arange(100000) + 0.5) / 100000
    lo, hi = occupied_band(f, PCT)
    assert lo == pytest.approx(-0.5 * b + 0.005 * b, abs=b * 2e-5) and hi == pytest.approx(0.5 * b - 0.005 * b, abs=b * 2e-5)
    assert hi - lo == pytest.approx(0.99 * b, rel=1e-4)
    wide = occupied_band(f, 5.0)
    assert wide[1] - wide[0] == pytest.approx(0.90 * b, rel=1e-4)
    with pytest.raises(ValueError):
        occupied_band([], PCT)


@pytest.mark.parametrize("centre, sweep, fs", [(60.0e9, 4.0e9, 8.0e9), (61.25e9, 0.5e9, 1.6e9)])
def test_the_dwell_time_and_the_spectrum_give_the_same_limits(centre, sweep, fs):
    """Two routes to the same band on the cycle-accurate engine's own
    trajectory: the quantiles in time of its instantaneous frequency, and
    the cumulative power of the spectrum of the phase it integrates to.
    They agree to a fraction of the spectrum's own edge width, sqrt(B / T)
    (6.3 MHz on the default chirp, 2.2 MHz on a 500 MHz one)."""
    cfg = apply_overrides(RadarConfig(), {"band.center_hz": centre, "band.sweep_hz": sweep, "frontend.tx_backoff_db": 0.0, "chirp.frame_period_s": None})
    ch, f = _traj(cfg)
    edge = np.sqrt(sweep / cfg.chirp.duration_s)
    a = occupied_band(f, PCT)
    s = occupied_band_from_spectrum(f, ch.fref_hz, PCT, fs)
    assert abs(a[0] - s[0]) < 0.25 * edge and abs(a[1] - s[1]) < 0.25 * edge
    assert (a[1] - a[0]) == pytest.approx(0.99 * sweep, rel=2e-3) and (s[1] - s[0]) == pytest.approx(0.99 * sweep, rel=2e-3)
    # the power the spectrum has outside the commanded edges is far under the share the definition leaves there
    x = np.exp(2j * np.pi * np.cumsum(np.repeat(f, int(round(fs / ch.fref_hz)))) / fs)
    p = np.abs(np.fft.fftshift(np.fft.fft(x))) ** 2
    ax = np.fft.fftshift(np.fft.fftfreq(x.size, 1.0 / fs))
    assert 100.0 * p[ax < -0.5 * sweep].sum() / p.sum() < 0.2 * PCT and 100.0 * p[ax > 0.5 * sweep].sum() / p.sum() < 0.2 * PCT
    with pytest.raises(ValueError):
        occupied_band_from_spectrum(f, ch.fref_hz, PCT, 0.5 * sweep)           # a grid that does not hold the excursion


def test_the_default_radars_occupied_band_lies_inside_its_commanded_sweep():
    """58-62 GHz commanded; 58.020-61.980 GHz occupied, 3.960 GHz, each
    limit 20 MHz inside its commanded edge.  The loop's overshoot does not
    reach past an edge on this chirp.  Every tier holds the measured band
    exactly where it holds the commanded one, and the verdict is the one a
    check without any measurement gives."""
    cfg = RadarConfig()
    st_chirp = ChirpEngine(cfg).run(noise=False, n_chirps=3)
    o = chirp_occupied_band(cfg, st_chirp)
    assert o["engine"] == "event" and o["outside_each_limit_pct"] == PCT and o["source"] == "spec"
    assert (o["commanded_lo_hz"], o["commanded_hi_hz"], o["commanded_bw_hz"]) == (58.0e9, 62.0e9, 4.0e9)
    assert o["lo_hz"] == pytest.approx(58.020e9, abs=1e6) and o["hi_hz"] == pytest.approx(61.980e9, abs=1e6)
    assert o["bandwidth_hz"] == pytest.approx(3.960e9, abs=1e6) and o["inside_commanded"]
    assert o["margin_lo_hz"] == pytest.approx(20e6, abs=1e6) and o["margin_hi_hz"] == pytest.approx(20e6, abs=1e6)
    assert o["excursion_lo_hz"] == 0.0 and o["excursion_hi_hz"] == 0.0 and o["with_idle"] is None
    assert o["time_bandwidth"] == pytest.approx(4.0e5)
    plain, with_band = compliance_check(cfg), compliance_check(cfg, occupied_band_hz=(o["lo_hz"], o["hi_hz"]))
    assert with_band.occupied_ghz == (o["lo_hz"] / 1e9, o["hi_hz"] / 1e9) and plain.occupied_ghz is None
    assert all(t.in_band_measured is None and t.bandwidth_ok_measured is None for t in plain.tiers)
    assert [t.in_band_measured for t in with_band.tiers] == [t.in_band for t in with_band.tiers]
    strip = lambda d: {**{k: v for k, v in d.items() if k != "occupied_ghz"},                        # noqa: E731
                       "tiers": [{k: v for k, v in t.items() if not k.endswith("_measured")} for t in d["tiers"]]}
    assert strip(with_band.as_dict()) == strip(plain.as_dict())                 # nothing of the verdict moved
    # the linearised engine and the ideal ramp give the band to a megahertz
    for engine in ("response", "ideal"):
        c = apply_overrides(cfg, {"lo.engine": engine})
        e = chirp_occupied_band(c, None if engine == "ideal" else ChirpEngine(c).run(noise=False, n_chirps=3))
        assert e["engine"] == engine and e["lo_hz"] == pytest.approx(o["lo_hz"], abs=1e6) and e["hi_hz"] == pytest.approx(o["hi_hz"], abs=1e6)


def test_the_500_mhz_tier_on_the_commanded_and_on_the_measured_band():
    """61.0-61.5 GHz, 500 MHz or less.  A sweep commanded edge to edge
    occupies 495 MHz and overshoots each edge by 1.2-1.4 MHz for under 0.1 %
    of the time: inside by 2.4 MHz, the tier's on either reading.  A sweep
    commanded 504 MHz wide (2 MHz past each edge) still *occupies* 499 MHz
    inside the band -- the measured band would let it in.  The check does
    not: it judges on the commanded sweep, the stricter reading."""
    at = lambda sweep: apply_overrides(RadarConfig(), {"band.center_hz": 61.25e9, "band.sweep_hz": sweep, "frontend.tx_backoff_db": 0.0})     # noqa: E731

    def run(sweep):
        cfg = at(sweep)
        o = chirp_occupied_band(cfg, ChirpEngine(cfg).run(noise=False, n_chirps=3))
        t = next(t for t in compliance_check(cfg, occupied_band_hz=(o["lo_hz"], o["hi_hz"])).tiers if t.tier == "radar_61_61p5")
        return o, t

    o, t = run(0.5e9)
    assert o["bandwidth_hz"] == pytest.approx(495e6, abs=0.5e6) and o["inside_commanded"]
    assert 1.0e6 < o["excursion_lo_hz"] < 2.0e6 and 1.0e6 < o["excursion_hi_hz"] < 2.0e6 and o["time_outside_hi_pct"] < 0.2 * PCT
    assert o["margin_lo_hz"] == pytest.approx(2.5e6, abs=0.3e6)
    assert (t.in_band, t.bandwidth_ok, t.in_band_measured, t.bandwidth_ok_measured, t.usable) == (True, True, True, True, True)
    o, t = run(0.504e9)
    assert o["bandwidth_hz"] == pytest.approx(499e6, abs=0.5e6) and 61.0e9 < o["lo_hz"] < o["hi_hz"] < 61.5e9
    assert (t.in_band_measured, t.bandwidth_ok_measured) == (True, True)
    assert (t.in_band, t.bandwidth_ok, t.usable) == (False, False, False)       # the verdict: on the commanded sweep


def test_with_the_transmitter_on_through_the_idle_time_the_band_reaches_past_the_edge():
    """20 us of idle between ramps: the flyback lands there, undershoots the
    start frequency by 4 MHz for a few microseconds and the LO then sits
    at the edge.  Over the ramps alone the band is the default's.  If the
    transmitter is on through the idle time the emission's lower limit is at
    the commanded edge and a little past it -- the case the measured band
    is wider than the commanded sweep.  Whether the PA is keyed off there is
    not modelled; both are reported."""
    cfg = apply_overrides(RadarConfig(), {"chirp.idle_s": 20e-6, "chirp.frame_period_s": None})
    o = chirp_occupied_band(cfg, ChirpEngine(cfg).run(noise=False, n_chirps=3))
    w = o["with_idle"]
    assert o["inside_commanded"] and o["margin_lo_hz"] == pytest.approx(20e6, abs=1e6)
    assert w is not None and not w["inside_commanded"] and -1.0e6 < w["margin_lo_hz"] < 0.0 and w["margin_hi_hz"] > 20e6
    assert 3.0e6 < w["excursion_lo_hz"] < 6.0e6 and 1.0 < w["time_outside_lo_pct"] < 5.0
    assert chirp_occupied_band(RadarConfig(), None)["with_idle"] is None
    ideal = chirp_occupied_band(apply_overrides(cfg, {"lo.engine": "ideal"}), None)["with_idle"]
    assert ideal["margin_lo_hz"] == pytest.approx(0.0, abs=1e3) and ideal["excursion_lo_hz"] == 0.0     # parked at the edge, no transient


def test_the_band_follows_the_tables_share(monkeypatch):
    real = sources.number
    monkeypatch.setattr(sources, "number", lambda key: dataclasses.replace(real(key), value=5.0)
                        if key == "fcc2.occupied_bandwidth.power_outside_each_limit_pct" else real(key))
    o = chirp_occupied_band(apply_overrides(RadarConfig(), {"lo.engine": "ideal"}), None)
    assert o["outside_each_limit_pct"] == 5.0 and o["bandwidth_hz"] == pytest.approx(0.90 * 4.0e9, rel=1e-3)


def test_the_report_gives_the_measured_band_beside_the_verdict():
    rep = rpt.build(apply_overrides(RadarConfig(), {"lo.engine": "response"}))
    k = rep["compliance"]
    o = k["occupied_band"]
    assert o["engine"] == "response" and o["quantity"] == "occupied bandwidth (47 CFR 2.1049)" and "not in the rule text" in o["codified"]
    assert k["occupied_ghz"] == [o["lo_hz"] / 1e9, o["hi_hz"] / 1e9] and k["governing"] == "radar_57_64" and k["compliant"] is True
    assert all(t["in_band_measured"] == t["in_band"] for t in k["tiers"]) and len(k["readings"]) == len(comp.READINGS) == 6
    assert any("FCC 23-35 para. 62" in r and "stricter reading" in r for r in k["readings"])
    assert not any("does not say how it is measured" in r for r in k["readings"])
    md = rpt.to_markdown(rep)
    assert "Occupied band, measured (occupied bandwidth (47 CFR 2.1049): 0.5 % of the mean power outside each limit, source: spec)" in md
    assert "(98.99 % of the commanded 4 GHz), inside the commanded edges by 20." in md and 'no tier\'s "sweep inside" would change' in md
    assert "If the transmitter stays on through the idle time" not in md
    idle = rpt.to_markdown(rpt.build(apply_overrides(RadarConfig(), {"lo.engine": "response", "chirp.idle_s": 20e-6, "chirp.frame_period_s": None})))
    assert "If the transmitter stays on through the idle time between ramps" in idle and "Whether the PA is keyed off there is not modelled" in idle
    # the windows' names, both (jcas60, fmcw_radar#44: the Doppler window's was missing)
    assert (rep["radar"]["range_window"], rep["radar"]["doppler_window"]) == ("hann", "hann")

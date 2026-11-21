"""Levels where the map shows them, floors where things sit (0.2.31).

A level in dBc -- a ghost target's, the phase-noise floor's -- is the beat
signal's ahead of the IF high-pass.  On the map the line and the target have
each passed the filter at their own beat, so the line stands
``A(f_target) - A(f_line)`` higher against the target's peak; the thermal
noise under it moved the same way, the ADC's quantisation noise did not.
And the LO's noise under a cell is the target's sideband at that cell's
offset: next to the target the round trip has cancelled it, under a ghost a
few metres out it has not."""

import numpy as np
import pytest

from fmcw_radar import report as rpt
from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time
from fmcw_radar.engine.statistical import hpf_map_shift_db, hpf_noise_shift_db, pn_floor_local_cell
from fmcw_radar.phase_noise import RangeCorrelation
from fmcw_radar.processing.iffilter import hpf_attenuation_db
from fmcw_radar.processing.rd import LOCAL_FLOOR_BINS, local_noise_floor

FAST = {"lo.engine": "response", "chirp.n_chirps": 16}
#: a corner reflector at full power with the TDC's jitter off: every ghost in view is far over the noise
STRONG = {"chirp.n_chirps": 32, "frontend.tx_backoff_db": 0.0, "target.kind": "corner_reflector", "lo.tdc_jitter_s": 0.0}


def _cfg(corner_hz=0.0, order=2, **ov):
    return apply_overrides(RadarConfig(), {"rx.hpf_corner_hz": corner_hz, "rx.hpf_order": order, **ov})


def test_without_the_filter_a_level_is_its_level_on_the_map():
    cfg = _cfg(**FAST)
    st = run_statistical(cfg)
    assert all(hpf_map_shift_db(cfg, r) == 0.0 and hpf_noise_shift_db(cfg, st.budget, r) == 0.0 for r in (-3.0, 0.0, 0.3, 5.0, 12.0))
    assert st.cfar["ghosts"] and all(g["level_map_dbc"] == g["level_dbc"] and g["noise_shift_db"] == 0.0 for g in st.cfar["ghosts"])
    rep = rpt.report(cfg, st)
    assert all(row["map_shift_db"] == 0.0 and row["per_cell_map_dbc"] == row["per_cell_dbc"] for row in rep["phase_noise"]["floor"])
    assert "behind the IF high-pass [dBc]" not in rpt.to_markdown(rep)


@pytest.mark.parametrize("corner_hz, order", [(0.2e6, 2), (1.0e6, 1), (1.0e6, 2), (2.0e6, 2), (3.0e6, 4)])
def test_the_filter_moves_a_line_by_the_difference_of_two_attenuations(corner_hz, order):
    cfg = _cfg(corner_hz, order, **FAST)
    a = lambda r: hpf_attenuation_db(cfg.slope_hz_per_s * cfg.tau_s(r), corner_hz, order)      # noqa: E731
    for r in (0.3, 2.19, 7.81, 9.68, 15.0):
        assert hpf_map_shift_db(cfg, r) == pytest.approx(a(5.0) - a(r), abs=1e-12)
        assert hpf_map_shift_db(cfg, -r) == hpf_map_shift_db(cfg, r)                           # under zero it folds to its mirror
    assert hpf_map_shift_db(cfg, cfg.target.range_m) == 0.0
    assert hpf_map_shift_db(cfg, 9.0) > 0.0 > hpf_map_shift_db(cfg, 2.0)                       # farther out stands higher, nearer lower
    assert np.isfinite(hpf_map_shift_db(cfg, 0.0)) and hpf_map_shift_db(cfg, 0.0) == hpf_map_shift_db(cfg, 1e-4)   # one range bin from DC


def test_the_roadmaps_number_ten_metres_behind_the_target_is_1p17_db_up():
    """The line ROADMAP P2 #6 carried since 0.2.25: 1 MHz, 2nd order, the
    target at 5 m (1.33 MHz of beat), a ghost 10 m behind it (4.0 MHz)."""
    cfg = _cfg(1.0e6, 2, **FAST)
    assert cfg.slope_hz_per_s * cfg.tau_s(15.0) == pytest.approx(4.0e6, rel=2e-3)
    assert hpf_map_shift_db(cfg, 15.0) == pytest.approx(1.17, abs=0.01)


def test_under_a_near_line_the_noise_stops_at_the_adcs_own():
    """A line at 0.32 m with a 1 MHz 2nd-order filter loses 41.8 dB against
    the target at 5 m; the thermal noise there loses as much, and what is
    left under the line is the ADC's quantisation noise, 16.9 dB under the
    floor at the target.  Behind the target both move together, to within
    the quantisation noise's share."""
    cfg = _cfg(1.0e6, 2, **FAST)
    b = run_statistical(cfg).budget
    assert hpf_map_shift_db(cfg, 0.316) == pytest.approx(-41.8, abs=0.1)
    assert hpf_noise_shift_db(cfg, b, 0.316) == pytest.approx(-16.9, abs=0.2)
    assert hpf_noise_shift_db(cfg, b, 0.316) == pytest.approx(b.n0_quant_adc_dbm_hz - b.n0_total_adc_dbm_hz, abs=0.03)
    assert hpf_noise_shift_db(cfg, b, cfg.target.range_m) == pytest.approx(0.0, abs=1e-12)
    for r in (7.81, 9.68, 13.4):
        level, noise = hpf_map_shift_db(cfg, r), hpf_noise_shift_db(cfg, b, r)
        assert 0.0 < noise < level and level - noise < 0.05


def test_next_to_the_target_the_round_trip_has_cancelled_the_los_noise():
    """The floor in the 4-20 bins beside the target is 15 dB under the
    map-wide mean (-80.4 against -65.0 dBc per cell on the default): the
    residual 2(1 - cos 2 pi f tau) S_phi is small that close to the beat.
    Under a ghost 2.8 m out it is the map's level again."""
    cfg = _cfg()
    st = run_statistical(cfg)
    rc = RangeCorrelation.from_config(cfg)
    local, mean = st.extras["pn_cell_local_dbc"], st.extras["pn_cell_mean_dbc"]
    assert local == pytest.approx(-80.4, abs=0.3) and mean == pytest.approx(-65.0, abs=0.3)
    assert 10.0 * np.log10(pn_floor_local_cell(cfg, rc)) == pytest.approx(local, abs=1e-9)
    assert 10.0 * np.log10(pn_floor_local_cell(cfg, rc, 7.81)) == pytest.approx(mean, abs=1.0)
    # a human at 5 m is far from LO-limited: both floors are the thermal one and the two readings stay one number to 0.05 dB
    assert 0.0 < st.extras["snr_cell_local_db"] - st.extras["snr_cell_expected_db"] < 0.05
    assert all(g["floor_dbc"] == pytest.approx(-st.cfar["snr_look_db"], abs=0.3) for g in st.cfar["ghosts"])


def _on_map(tm, cfg, range_m):
    """(level against the target's cell, local floor against it) of the strongest cell near ``range_m`` in the target's Doppler row."""
    p = 10.0 ** (np.asarray(tm.rd_db) / 10.0)
    i0, j0 = tm.extras["local_cell"]
    near = np.flatnonzero(np.abs(np.asarray(tm.range_axis_m) - range_m) < 0.06)
    j = int(near[np.argmax(p[i0][near])])
    pad = cfg.processing.range_pad
    floor = local_noise_floor(p[:, : p.shape[1] // 2], (i0, j), 2, LOCAL_FLOOR_BINS[0] * pad, LOCAL_FLOOR_BINS[1] * pad)
    return 10.0 * np.log10(p[i0, j] / p[i0, j0]), 10.0 * np.log10(floor / p[i0, j0])


def test_both_engines_put_the_ghosts_where_the_filter_leaves_them():
    """A corner reflector at 5 m, four ghosts in view at 0.32 / 2.19 / 7.81 /
    9.68 m, 36-40 dB under it.  Without a filter the time engine's map has
    them at the listed levels to 0.4 dB.  With a 2 MHz 2nd-order high-pass
    the two behind the target stand 5.1 and 6.5 dB higher against its peak,
    the one at 2.19 m 13.6 dB lower, and the one at 0.32 m is gone (47 dB
    lower, into the quantisation noise): the listed ``level_map_dbc`` is the
    map's to 0.5 dB, where the pre-filter level would be off by all of that.

    The scene is LO-limited away from the target: under each ghost the floor
    is the target's own sideband, and the statistical floor there is within
    3 dB of the map's (1.6-2.7 dB over it, with or without the filter; see
    ROADMAP).  Next to the target the sideband is cancelled and the target's
    own SNR is the thermal one in both engines, 0.6-0.7 dB apart -- 13 dB
    apart while the local reading still carried the map-wide mean."""
    seen = {}
    for name, corner in (("off", 0.0), ("on", 2.0e6)):
        cfg = _cfg(corner, 2, **STRONG)
        st, tm = run_statistical(cfg), run_time(cfg)
        ghosts = {round(g["range_m"], 2): g for g in st.cfar["ghosts"] if g["in_view"]}
        assert sorted(ghosts) == [0.32, 2.19, 7.81, 9.68]
        seen[name] = (st, tm, ghosts, {r: _on_map(tm, cfg, g["range_m"]) for r, g in ghosts.items()})
        assert tm.snr_cell_local_db == pytest.approx(st.extras["snr_cell_local_db"], abs=1.0)
        assert st.extras["pn_cell_local_dbc"] < st.extras["pn_cell_mean_dbc"] - 12.0
        assert st.extras["snr_cell_local_db"] > st.extras["snr_cell_expected_db"] + 10.0
    (st0, tm0, g0, m0), (st1, tm1, g1, m1) = seen["off"], seen["on"]
    for r in (0.32, 2.19, 7.81, 9.68):
        assert g0[r]["level_map_dbc"] == g0[r]["level_dbc"] and m0[r][0] == pytest.approx(g0[r]["level_dbc"], abs=0.5)
    for r, shift in ((2.19, -13.6), (7.81, 5.15), (9.68, 6.5)):
        assert g1[r]["level_map_dbc"] - g1[r]["level_dbc"] == pytest.approx(shift, abs=0.1)
        assert m1[r][0] - m0[r][0] == pytest.approx(shift, abs=0.5)                              # the map moved by it
        assert m1[r][0] == pytest.approx(g1[r]["level_map_dbc"], abs=0.5)
        for g, m in ((g0[r], m0[r]), (g1[r], m1[r])):
            assert 0.0 < g["floor_dbc"] - m[1] < 3.0                                                # the floor where the ghost sits
            assert g["snr_db"] == pytest.approx(g["level_map_dbc"] - g["floor_dbc"]) and g["pd"] > 0.99
        assert g0[r]["floor_dbc"] > -st0.cfar["snr_look_db"] + 10.0                                # the LO's noise, not the target's own floor
    # the nearest one: detected without the filter, under the noise with it, in both engines
    assert g0[0.32]["pd"] > 0.99 and g1[0.32]["pd"] < 0.01 and g1[0.32]["level_map_dbc"] < g1[0.32]["level_dbc"] - 45.0
    near = lambda tm: [d for d in tm.cfar_detections if abs(d[1] - g0[0.32]["range_m"]) < 0.08]   # noqa: E731
    assert near(tm0) and not near(tm1)
    assert st0.cfar["ghost_detections_per_frame"] == pytest.approx(4.0, abs=0.01)
    assert st1.cfar["ghost_detections_per_frame"] == pytest.approx(3.0, abs=0.01)
    # the map-wide reading: the LO's floor passes the filter bin by bin, so the two engines stay as far apart as without it
    gap0, gap1 = tm0.snr_cell_db - st0.extras["snr_cell_expected_db"], tm1.snr_cell_db - st1.extras["snr_cell_expected_db"]
    assert gap0 == pytest.approx(1.9, abs=0.4) and gap1 == pytest.approx(gap0, abs=0.4)


def test_the_report_carries_both_levels():
    cfg = _cfg(1.0e6, 2, **FAST)
    rep = rpt.build(cfg)
    floor = rep["phase_noise"]["floor"]
    assert all(row["per_cell_map_dbc"] == row["per_cell_dbc"] + row["map_shift_db"] for row in floor)
    assert [round(row["map_shift_db"], 2) for row in floor] == [round(hpf_map_shift_db(cfg, 5.0 + row["offset_m"]), 2) for row in floor]
    assert 0.0 < floor[0]["map_shift_db"] < floor[-1]["map_shift_db"] == pytest.approx(1.09, abs=0.02)      # +5 m: 2.67 MHz
    md = rpt.to_markdown(rep)
    assert "on the map, behind the IF high-pass [dBc] |" in md and "| ghost at [m] | level [dBc] | on the map [dBc] | floor where it sits [dBc] |" in md
    for g in rep["cfar"]["ghosts"]:
        assert g["level_map_dbc"] == pytest.approx(g["level_dbc"] + hpf_map_shift_db(cfg, g["range_m"]))
        assert g["snr_db"] == pytest.approx(g["level_map_dbc"] - g["floor_dbc"])

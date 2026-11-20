"""The GUI's compute layer (guiutil): it orchestrates, the library computes.
What a page gets for a run is the command line's report, value for value,
with the page's extras around it."""

import json

import numpy as np
import pytest
from conftest import REPO

from fmcw_radar import guispec, guiutil
from fmcw_radar.config import RadarConfig, apply_overrides, config_to_dict, load_config
from fmcw_radar.engine.statistical import run_statistical
from fmcw_radar.link import compliance_check
from fmcw_radar.report import build, report

FAST = {"chirp.n_chirps": 8, "lo.engine": "response"}


@pytest.fixture(scope="module")
def fast():
    return guiutil.run_report(FAST)


def test_the_report_inside_is_the_command_lines(fast):
    """``run_report`` adds, it does not recompute: its ``report`` is
    ``report.report(cfg, run_statistical(cfg))`` for the same config."""
    cfg = apply_overrides(RadarConfig(), FAST)
    assert fast["ok"] and fast["report"] == guiutil.plain(build(cfg))
    json.dumps(fast)                                                     # no numpy, no NaN objects
    assert fast["values"] == guiutil.plain(guispec.values_from_config(cfg))
    for name, m in guispec.METRICS.items():
        node = fast["report"]
        for k in m["report"].split("."):
            node = node[k]
        assert fast["metrics"][name] == node, name
    assert fast["tags"] == guispec.tags(FAST) and fast["inert"] == guispec.inert(FAST) and fast["refused"] == guispec.refused_choices(FAST)
    # a sourced number edited on the page is the user's assumption from then on; the table's own number is not an edit
    edit = dict(FAST, **{"frontend.tx_power_dbm": 10.0})
    assert fast["tags"]["frontend.tx_power_dbm"] == "spec" and guiutil.run_report(edit)["tags"]["frontend.tx_power_dbm"] == "assumed"
    assert guiutil.run_report(dict(FAST, **{"frontend.tx_power_dbm": 12.0}))["tags"] == fast["tags"]
    assert fast["resolved"]["frontend.tx_power_dbm"] == {"value": 12.0, "source": "spec", "key": "60g_sensing.tx_power_dbm"}
    eng = {e["id"]: e for e in fast["engines"]}
    assert set(eng) == {"statistical", "chirp:response", "time"} and set(eng) <= set(guispec.ENGINES)
    assert eng["chirp:response"]["vouches_for_spurs"] is False and eng["time"] == {"id": "time", "state": "not_run"}
    assert eng["statistical"]["wall_s"] == fast["wall_s"] > 0


def test_the_full_power_column_is_the_same_budget_at_backoff_zero():
    """The second column of the page's budget: the config with the backoff
    at 0, compression by the leakage included -- equal to a full statistical
    run of that config, without running the chirp engine twice."""
    for cfg in (apply_overrides(RadarConfig(), FAST), apply_overrides(load_config(REPO / "configs" / "radar_60g_mimo.yaml"), FAST)):
        fp = guiutil.full_power(cfg)
        c0 = apply_overrides(cfg, {"frontend.tx_backoff_db": 0.0})
        st = run_statistical(c0)
        assert [r["value"] for r in fp["budget"]] == [v for _, v, _ in st.budget.as_rows()]
        assert fp["eirp_dbm"] == 22.0 and fp["snr_cell_db"] == st.snr_cell_db
        k = compliance_check(c0)
        assert fp["compliance"] == {"applies": True, "verdict": k.verdict, "compliant": False, "eirp_margin_db": pytest.approx(-8.0)}
    assert guiutil.full_power(apply_overrides(RadarConfig(), {"frontend.tx_backoff_db": 0.0})) is None      # nothing to compare with
    assert guiutil.run_report({**FAST, "frontend.tx_backoff_db": 0.0})["full_power"] is None


def test_plot_data_is_the_librarys_numbers(fast):
    cfg = apply_overrides(RadarConfig(), FAST)
    p = fast["plots"]
    from fmcw_radar.lo import LOProfile

    prof = LOProfile.from_config(cfg)
    assert len(p["pn"]["f_hz"]) == 90 and p["pn"]["f_hz"][0] == 1e4 and p["pn"]["f_hz"][-1] == pytest.approx(50e6)
    assert p["pn"]["l_1mhz_dbc_hz"] == float(prof.l_dbc(1e6)) and set(p["pn"]["components_l_dbc_hz"]) == set(prof.components)
    assert p["pn"]["lo_l_dbc_hz"] == np.round(prof.l_dbc(np.array(p["pn"]["f_hz"])), 2).tolist()
    assert all(r <= lo + 6.03 for r, lo in zip(p["pn"]["residual_l_dbc_hz"], p["pn"]["lo_l_dbc_hz"]))      # at most 2 (1 - cos) = 4 over the LO
    lv = {r["id"]: r for r in p["levels"]}
    rows = {r["term"]: r["value"] for r in fast["report"]["budget"]}
    assert [r["id"] for r in p["levels"]] == ["tx_power", "conducted", "eirp", "p_r", "adc"]
    assert (lv["tx_power"]["now"], lv["conducted"]["now"], lv["eirp"]["now"]) == (12.0, 4.0, 14.0)
    assert lv["p_r"]["now"] == rows["received power P_r"] and lv["adc"]["now"] == rows["signal at the ADC"]
    assert all(r["full_power"] - r["now"] == pytest.approx(8.0) for r in p["levels"][1:]) and lv["tx_power"]["full_power"] == 12.0
    k = fast["report"]["compliance"]
    assert p["timing"] == {"frame_on_s": k["frame_on_s"], "frame_period_s": k["frame_period_s"], "off_time_required_s": 0.0255,
                           "off_time_have_s": pytest.approx(0.033 - k["frame_on_s"]), "window_s": 0.033}
    nl = fast["report"]["nonlinearity"]
    assert p["ghosts"]["stems"] == [{"offset_m": g[0], "level_dbc": g[1]} for g in nl["ghosts"]] and p["ghosts"]["vouched"] is False
    assert p["ghosts"]["list"] == fast["report"]["cfar"]["ghosts"] and p["ghosts"]["limit_dbc"] == nl.get("ghost_limit_dbc")


def test_config_hash_follows_the_values_and_only_them():
    h = guiutil.config_hash(RadarConfig())
    assert len(h) == 64 and int(h, 16) >= 0 and h == guiutil.config_hash(load_config(REPO / "configs" / "radar_60g_sensing.yaml"))
    import hashlib

    blob = json.dumps(guiutil.plain(config_to_dict(RadarConfig())), sort_keys=True, separators=(",", ":")).encode()
    assert h == hashlib.sha256(blob).hexdigest()
    assert guiutil.config_hash(apply_overrides(RadarConfig(), {"target.range_m": 5.5})) != h
    # typing the source table's own number into a field is the same config: the same hash
    assert guiutil.run_report({**FAST, "frontend.tx_power_dbm": 12.0})["repro"]["config_sha256"] == guiutil.run_report(FAST)["repro"]["config_sha256"]
    names = {load_config(REPO / "configs" / f"{n}.yaml") for n in ("radar_60g_mimo", "radar_60g_x10lo", "radar_60g_dither", "radar_77g_automotive")}
    assert len({guiutil.config_hash(c) for c in names} | {h}) == 5


def test_the_reproducibility_card_reproduces(fast):
    rp = fast["repro"]
    assert rp["seed"] == 1 and rp["library"] == "fmcw_radar" and rp["edits"] == FAST
    assert rp["config_sha256"] == guiutil.config_hash(apply_overrides(RadarConfig(), FAST))
    assert {v["repo"] for v in rp["vendored"]} == {"polar_tx", "pll_simulator", "array_tx", "mmw60_trx", "spec_sources"}
    assert all(len(v["pin"]) >= 7 and int(v["pin"], 16) >= 0 for v in rp["vendored"])
    scope: dict = {}
    exec(rp["call"], scope)                                              # the equivalent call, run as written
    assert guiutil.plain(scope["rep"]) == fast["report"]
    import fmcw_radar

    assert rp["version"] == fmcw_radar.__version__ and rp["numpy"] == np.__version__


def test_what_the_config_refuses_comes_back_as_its_sentence_and_its_field():
    for values, field, part in (({"frontend.tx_backoff_db": -1.0}, "frontend.tx_backoff_db", "is a reduction"),
                                ({"mimo.n_rx": 2}, "mimo.angle_window", "2 virtual elements"),
                                ({"lo.engine": "response", "lo.dp_cal": "online"}, "lo.dp_cal", "needs lo.engine 'event'"),
                                ({"chirp.n_chirps": 512}, "chirp.frame_period_s", "shorter than the frame"),
                                ({"band.kind": "77g_automotive"}, None, "leaves the 77g_automotive window")):
        r = guiutil.run_report(values)
        assert r["ok"] is False and r["field"] == field and part in r["error"], values
        assert "report" not in r and r["inert"] == guispec.inert(values)
        f = guiutil.run_frame(values)
        assert f["ok"] is False and f["error"] == r["error"]
    assert guiutil.run_report(guispec.band_switch({**FAST}, "77g_automotive"))["report"]["compliance"]["applies"] is False


def test_cell_labels_follow_the_stated_rule():
    cfg = apply_overrides(RadarConfig(), FAST)
    dr, dv = cfg.range_resolution_m, cfg.velocity_resolution_mps
    ghosts = [{"range_m": 7.81}, {"range_m": 2.19}]
    det = [(2.0, 5.0), (2.0 + 2 * dv, 5.0 + 3 * dr), (2.0, 7.81 + dr), (2.0, 2.19), (2.0, 11.0), (-9.0, 11.0), (-12.0, 0.01), (2.0, 5.0 + 5 * dr)]
    kinds = [c["kind"] for c in guiutil.classify_cells(cfg, ghosts, det)]
    assert kinds == ["target_lobe", "target_lobe", "ghost", "ghost", "target_doppler_row", "elsewhere", "elsewhere", "target_doppler_row"]
    assert [c.get("ghost_index") for c in guiutil.classify_cells(cfg, ghosts, det)][2:4] == [0, 1]
    # with the leakage modelled, zero Doppler and the first range cells are the leakage's; a second target has its own lobe
    # (on the 64-chirp frame: with 8 chirps a velocity cell is 3.1 m/s and "zero Doppler +- 3 cells" holds both targets)
    two = apply_overrides(RadarConfig(), {"leakage.enabled": True, "extra_targets": [{"kind": "car", "range_m": 8.0, "velocity_mps": -3.0}]})
    kinds = [c["kind"] for c in guiutil.classify_cells(two, ghosts, [(0.0, 9.0), (5.0, 0.05), (-3.0, 8.0), (-3.0, 12.0), (2.0, 5.0)])]
    assert kinds == ["leakage", "leakage", "other_target_lobe", "target_doppler_row", "target_lobe"]
    assert set(kinds) <= set(guiutil.CELL_KINDS)


def test_the_frame_for_the_page():
    """The time engine's frame as the page gets it: pooled by maximum so the
    peak survives, cells labelled, and the check against the statistical
    engine (invariant #3: within 1 dB for LTI + Gaussian noise)."""
    f = guiutil.run_frame(FAST)
    json.dumps(f)
    m = f["rd_map"]
    grid = np.array(m["db_rel_peak"])
    assert f["ok"] and grid.shape == (m["rows"], m["cols"]) == (8, 150) and m["full_grid_shape"] == [8, 2000]
    assert grid.max() == 0.0 and grid.min() >= -99.9 and len(m["range_m_col_centres"]) == 150 and len(m["velocity_mps_row_centres"]) == 8
    i, j = np.unravel_index(int(grid.argmax()), grid.shape)
    assert m["range_m_col_centres"][j] == pytest.approx(5.0, abs=0.1) and m["max_range_m"] == pytest.approx(14.99, abs=0.01)
    te = f["time_engine"]
    assert abs(te["snr_difference_db"]) < 1.0 and te["snr_difference_db"] == pytest.approx(te["snr_cell_db"] - te["snr_cell_expected_db"])
    assert te["peak_range_m"] == pytest.approx(5.0, abs=0.05) and te["n_chirps"] == 8
    assert sum(f["cell_counts"].values()) == len(f["cells"]) and f["cell_counts"]["target_lobe"] >= 1
    assert f["config_sha256"] == guiutil.config_hash(apply_overrides(RadarConfig(), FAST)) and f["seed"] == 1
    # pooled smaller, the peak is still the peak
    small = guiutil.pool_max(np.arange(40.0).reshape(4, 10), 2, 5)[0]
    assert small.shape == (2, 5) and small[-1, -1] == 39.0 and guiutil.pool_max(np.ones((3, 4)), 64, 150)[0].shape == (3, 4)


def test_report_is_unchanged_by_the_page_layer():
    """The library's report for the default config, through the page layer
    and straight: the same object (the page layer must not perturb it)."""
    cfg = RadarConfig()
    st = run_statistical(cfg)
    assert guiutil.run_report({})["report"] == guiutil.plain(report(cfg, st))

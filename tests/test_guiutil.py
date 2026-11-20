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


# ---------------------------------------------------------------- P3: the system diagram, the band rows, a sweep, a baseline

@pytest.mark.parametrize("name", ["radar_60g_sensing", "radar_60g_mimo", "radar_60g_dither", "radar_60g_x10lo", "radar_77g_automotive"])
def test_the_diagram_holds_the_runs_own_numbers(name):
    """Every stage of the system diagram, for every bundled config: a control
    line shows what the form holds (or the number behind an empty field), a
    read line a finite number from the run, and the optional stages are in
    play exactly when the config uses them."""
    flat = guispec.values_from_config(load_config(REPO / "configs" / f"{name}.yaml"))
    flat["chirp.n_chirps"] = 8
    r = guiutil.run_report(flat)
    assert r["ok"]
    by = {c.path: c for c in guispec.controls(guispec.values_to_config(flat))}
    st = {s["id"]: s for s in r["system"]["stages"]}
    assert list(st) == [s["id"] for s in guispec.STAGES]
    for s in st.values():
        for ln in s["lines"] + ([s["out"]] if s["out"] else []):
            if ln["kind"] == "control":
                c = by[ln["path"]]
                held = r["values"][c.path]
                assert ln["value"] == guiutil.plain(guispec.to_display(c, c.resolved if held is None and c.source else held)), ln["path"]
                assert ln["unit"] == c.unit
            elif ln["kind"] == "read" and s["active"]:
                if ln["value"] is None:                              # the one number a run may not have: no ghost, no strongest ghost
                    assert ln["en"] == "strongest ghost" and r["plots"]["ghosts"]["stems"] == []
                else:
                    assert isinstance(ln["value"], (int, float)) and np.isfinite(ln["value"]), (s["id"], ln["en"])
    rep = r["report"]
    assert st["pa"]["out"]["value"] == rep["compliance"]["conducted_dbm"] and st["txant"]["out"]["value"] == rep["compliance"]["eirp_dbm"]
    assert st["rfft"]["lines"][2]["value"] == rep["radar"]["range_res_m"] / 1e-2 and st["rfft"]["lines"][2]["unit"] == "cm"
    assert st["dbf"]["active"] == (name == "radar_60g_mimo") == bool(rep["angle"])
    assert st["leak"]["active"] == bool(flat["leakage.enabled"]) and st["hpf"]["active"] == (flat["rx.hpf_corner_hz"] > 0)
    assert st["comp"]["active"] == rep["compliance"]["applies"] == (name != "radar_77g_automotive")
    assert st["comp"].get("verdict") == rep["compliance"].get("compliant")
    assert guiutil.pick(r, "report.budget[received power P_r].value") == st["rxant"]["out"]["value"]
    assert guiutil.pick(r, "report.nothing.here") is None and guiutil.pick(r, "values.target.range_m") == flat["target.range_m"]


def test_a_band_row_is_a_config_you_can_be_on():
    """Each row of the band trade-off is a real config -- the sweep moved, the
    scenario declared, the transmitter backed off just to the governing
    tier's limit -- and its numbers are that config's own report.  Checked
    the way example 09 computes them: the budget with the EIRP capped."""
    from fmcw_radar.link import link_budget

    b = guiutil.band_tradeoff(FAST)
    assert b["ok"] and b["applies"] and [r["id"] for r in b["rows"]] == [r["id"] for r in guispec.BAND_ROWS]
    rows = {r["id"]: r for r in b["rows"]}
    assert all(r["ok"] and r["compliant"] for r in rows.values()) and rows["current"]["apply"] == {}
    for r in rows.values():
        there = guiutil.run_report({**FAST, **r["apply"]})
        assert there["metrics"] == r["metrics"] and there["repro"]["config_sha256"] == r["config_sha256"]
        assert r["eirp_dbm"] == pytest.approx(min(r["full_power_eirp_dbm"], r["limit_dbm"]), abs=1e-9)
        assert r["backoff_db"] == pytest.approx(max(0.0, r["full_power_over_db"]), abs=1e-12)
        cfg = guispec.values_to_config({**FAST, **r["apply"]})
        open_ = apply_overrides(cfg, {"frontend.tx_backoff_db": 0.0, "chirp.frame_period_s": None})
        k = compliance_check(open_)
        assert k.tier.tier == r["governing"] and k.tier.peak_eirp_limit_dbm == r["limit_dbm"]
        assert link_budget(open_, eirp_cap_dbm=k.eirp_cap_dbm).snr_cell_db == pytest.approx(r["metrics"]["snr_cell_db"], abs=1e-9)
        # the detection range is where that budget meets what the map's CFAR needs
        assert link_budget(cfg, range_m=r["detection_range_m"]).snr_cell_db == pytest.approx(r["metrics"]["snr_pd90_db"], abs=1e-6)
    # the same sweep under a tier 6 dB higher: 6 dB more SNR; a wider sweep: resolution as 1/B
    a, o = rows["57_64"], rows["57_64_outdoor_fixed"]
    assert o["limit_dbm"] - a["limit_dbm"] == 6.0
    assert o["metrics"]["snr_cell_db"] - a["metrics"]["snr_cell_db"] == pytest.approx(6.0, abs=1e-9)
    assert rows["current"]["metrics"]["range_res_m"] / a["metrics"]["range_res_m"] == pytest.approx(7.0 / 4.0, rel=1e-9)
    # the transmit antenna's gain stops moving the SNR once the EIRP is held to the limit; the receive antenna's moves it dB for dB
    ant = b["antenna"]
    assert ant[0]["snr_at_limit_db"] == pytest.approx(ant[2]["snr_at_limit_db"], abs=1e-9) and ant[0]["tx_gain_dbi"] == ant[2]["tx_gain_dbi"] - 8
    assert ant[4]["snr_at_limit_db"] - ant[3]["snr_at_limit_db"] == pytest.approx(4.0, abs=1e-9)
    assert ant[2]["snr_full_power_db"] - ant[2]["snr_at_limit_db"] == pytest.approx(8.0, abs=1e-9)
    assert {c["config"] for c in b["bundled"]} == {p.stem for p in (REPO / "configs").glob("*.yaml")}
    # where the rule does not apply there is no table, and the page is told why
    car = guiutil.band_tradeoff(guispec.band_switch(FAST, "77g_automotive"))
    assert car["ok"] and car["applies"] is False and car["rows"] == [] and "57-71 GHz" in car["why"]
    assert guiutil.band_tradeoff({"mimo.n_rx": 2})["field"] == "mimo.angle_window"
    json.dumps(b)


def test_a_sweep_point_is_a_run_of_its_own_config():
    seen = []
    s = guiutil.run_sweep(FAST, "target.range_m", 2.5, 10.0, 4, lambda done, total: seen.append((done, total)))
    assert s["ok"] and [p["x"] for p in s["points"]] == [2.5, 5.0, 7.5, 10.0] and s["current"] == 5.0 and s["unit"] == "m"
    assert seen == [(0, 4), (1, 4), (2, 4), (3, 4), (4, 4)]
    for p in s["points"]:
        assert p["ok"] and p["metrics"] == guiutil.run_report({**FAST, "target.range_m": p["x"]})["metrics"]
    # R^-4 and the oxygen over the extra path: twice the range costs 40 log 2 dB plus 2 * 2.5 m of 14.651 dB/km
    snr = [p["metrics"]["snr_cell_db"] for p in s["points"]]
    assert snr[0] - snr[1] == pytest.approx(40 * np.log10(2.0) + 2 * 2.5 * 14.651e-3, abs=1e-9)
    # past the IF band's range the point says so
    far = guiutil.run_sweep(FAST, "target.range_m", 14.0, 16.0, 2)["points"]
    assert far[0]["in_if_band"] and not far[1]["in_if_band"]
    # a value the schema refuses is a point with the schema's sentence
    bo = guiutil.run_sweep(FAST, "frontend.tx_backoff_db", -2.0, 2.0, 3)["points"]
    assert not bo[0]["ok"] and bo[0]["field"] == "frontend.tx_backoff_db" and bo[1]["ok"] and bo[2]["ok"]
    # an integer control steps whole numbers, once each
    assert [p["x"] for p in guiutil.run_sweep(FAST, "chirp.n_chirps", 8, 10, 5)["points"]] == [8, 9, 10]
    # the empty field's own number is "current"
    assert guiutil.run_sweep(FAST, "frontend.nf_db", 10.0, 14.0, 2)["current"] == 12.0
    for bad in (("target.kind", 1, 2, 3), ("target.range_m", 1, 2, 1), ("target.range_m", 1, 2, guispec.SWEEP_MAX_POINTS + 1), ("target.range_m", 3, 3, 4)):
        assert guiutil.run_sweep(FAST, *bad)["ok"] is False
    assert guiutil.run_sweep({"mimo.n_rx": 2}, "target.range_m", 1, 2, 2)["field"] == "mimo.angle_window"


def test_a_baseline_says_which_way_each_number_moved(fast):
    pin = {"values": FAST, "metrics": fast["metrics"]}
    far = guiutil.run_report({**FAST, "target.range_m": 10.0, "frontend.nf_db": 10.0}, pin)
    plain_run = guiutil.run_report({**FAST, "target.range_m": 10.0, "frontend.nf_db": 10.0})
    b = far["baseline"]
    assert "baseline" not in plain_run and far["metrics"] == plain_run["metrics"]            # pinning changes nothing in the run
    assert {c["path"]: (c["a"], c["b"]) for c in b["changed"]} == {"target.range_m": (5.0, 10.0), "frontend.nf_db": (None, 10.0)}
    assert b["config_sha256"] == fast["repro"]["config_sha256"]
    for name, row in b["metrics"].items():
        assert row["base"] == fast["metrics"][name] and row["now"] == far["metrics"][name]
        if row["delta"] is not None:
            assert row["delta"] == pytest.approx(float(row["now"]) - float(row["base"]))
    snr, res, pn = b["metrics"]["snr_cell_db"], b["metrics"]["range_res_m"], b["metrics"]["pn_residual_rms_rad"]
    assert snr["delta"] < 0 and snr["verdict"] == "worse" and res["verdict"] == "same" and pn["delta"] > 0 and pn["verdict"] == "worse"
    near = guiutil.run_report({**FAST, "target.range_m": 3.0}, pin)["baseline"]["metrics"]
    assert near["snr_cell_db"]["verdict"] == "better" and near["pn_residual_rms_rad"]["verdict"] == "better"
    # the run against itself: nothing changed, nothing moved
    same = guiutil.run_report(FAST, pin)["baseline"]
    assert same["changed"] == [] and all(r["verdict"] in ("same", None) and r["delta"] in (0.0, None) for r in same["metrics"].values())


# ---------------------------------------------------------------- a preview ahead of the cycle-accurate run; a config file in and out

@pytest.mark.parametrize("name", ["radar_60g_sensing", "radar_60g_mimo", "radar_60g_dither", "radar_60g_x10lo", "radar_77g_automotive"])
def test_a_preview_is_the_linearised_engines_run_of_the_real_config(name):
    """A config on the cycle-accurate chirp engine can be answered at once
    with the linearised engine's run of it.  The preview says so, keeps
    everything about the config itself (values, tags, hash), and is already
    final in every headline number that is not the chirp engine's own."""
    flat = guispec.values_from_config(load_config(REPO / "configs" / f"{name}.yaml"))
    flat["chirp.n_chirps"] = 8
    assert flat["lo.engine"] == "event"
    pre, full = guiutil.run_report(flat, preview=True), guiutil.run_report(flat)
    own = [k for k, m in guispec.METRICS.items() if m.get("chirp_engine")]
    assert pre["preview"] == {"shown": "response", "final": "event", "pending": own} and "preview" not in full
    assert own == ["ghost_detections_per_frame", "pn_residual_rms_rad", "chirp_rms_hz"]
    assert pre["report"] == guiutil.run_report({**flat, "lo.engine": "response"})["report"]
    assert pre["report"]["radar"]["lo_engine"] == "response" and full["report"]["radar"]["lo_engine"] == "event"
    for key in ("values", "tags", "inert", "refused", "resolved", "full_power"):
        assert pre[key] == full[key], key
    assert pre["values"]["lo.engine"] == "event" and pre["repro"]["config_sha256"] == full["repro"]["config_sha256"]
    assert pre["repro"]["call"] == full["repro"]["call"]
    for k in guispec.METRICS:
        if k not in own:
            assert pre["metrics"][k] == full["metrics"][k], k                 # final already
    assert pre["metrics"]["chirp_rms_hz"] != full["metrics"]["chirp_rms_hz"]  # and this one is not
    assert [e["id"] for e in pre["engines"]][1] == "chirp:response" and pre["engines"][1]["vouches_for_spurs"] is False


def test_where_the_linearised_engine_cannot_stand_in_the_run_is_the_full_one():
    f8 = {"chirp.n_chirps": 8}
    for ov in ({"lo.engine": "response"}, {"lo.engine": "ideal"}, {"lo.dp_cal": "online"}):       # not cycle-accurate; or refused by the stand-in
        r = guiutil.run_report({**f8, **ov}, preview=True)
        assert r["ok"] and "preview" not in r and r["report"]["radar"]["lo_engine"] == {**{"lo.engine": "event"}, **ov}["lo.engine"]
    assert guiutil.run_report({"mimo.n_rx": 2}, preview=True)["field"] == "mimo.angle_window"   # a refusal is a refusal either way


@pytest.mark.parametrize("name", ["radar_60g_sensing", "radar_60g_mimo", "radar_60g_x10lo", "radar_77g_automotive"])
def test_a_config_file_goes_out_and_comes_back(name, tmp_path):
    cfg = apply_overrides(load_config(REPO / "configs" / f"{name}.yaml"), {"target.range_m": 7.25, "frontend.nf_db": 10.5})
    flat = guispec.values_from_config(cfg)
    out = guiutil.export_yaml(flat)
    assert out["ok"] and out["config_sha256"] == guiutil.config_hash(cfg) and out["filename"] == f"fmcw_radar_{out['config_sha256'][:8]}.yaml"
    assert out["yaml"].splitlines()[0] == f"# fmcw_radar {guiutil.__version__} -- config sha256 {out['config_sha256']}"
    # the library reads the file back to the same config ...
    path = tmp_path / out["filename"]
    path.write_text(out["yaml"], encoding="utf-8")
    assert load_config(path) == cfg
    # ... and so does the page's own way in
    back = guiutil.load_yaml(out["yaml"])
    assert back["ok"] and back["config_sha256"] == out["config_sha256"] and guispec.values_to_config(back["values"]) == cfg
    assert guiutil.load_bundled(name)["values"] == guiutil.plain(guispec.values_from_config(load_config(REPO / "configs" / f"{name}.yaml")))


def test_a_file_that_is_not_a_config_says_why():
    assert guiutil.bundled_configs() == sorted(p.stem for p in (REPO / "configs").glob("*.yaml"))
    assert "band.kind must be one of" in guiutil.load_yaml("band: {kind: nope}")["error"]
    assert "mapping of sections" in guiutil.load_yaml("- 1\n- 2")["error"] and guiutil.load_yaml("a: [")["error"].startswith("not YAML")
    assert "at most" in guiutil.load_yaml("x" * (guiutil.YAML_MAX_BYTES + 1))["error"] and guiutil.load_yaml(None)["ok"] is False
    assert "2 virtual elements" in guiutil.load_yaml("mimo: {n_rx: 2}")["error"]
    assert guiutil.load_bundled("../pyproject")["ok"] is False
    assert guiutil.export_yaml({"mimo.n_rx": 2})["field"] == "mimo.angle_window"
    # an empty file is the default config, as it is for load_config
    assert guispec.values_to_config(guiutil.load_yaml("{}")["values"]) == RadarConfig()

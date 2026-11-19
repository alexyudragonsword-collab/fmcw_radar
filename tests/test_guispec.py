"""The GUI contract (guispec): every control is a config field, defaults are
read not typed, the default form builds ``RadarConfig()``, every control
turned one step moves the output it says it moves -- in the settings it
says it needs, and not without them -- and a number edited on the page is
``assumed``.

The "turn every knob" test is polar_tx's (its ``cairn/gui-redesign.md``):
a control that is offered and does nothing, or a setting the library
quietly drops, cannot be read off any output; only a declaration plus a
turn of the knob finds it.  It found three things here (cairn/gui.md): a
schema field nothing reads, online calibration silently not done by the
linearised engine, and the IF high-pass seen by one engine only."""

import functools
import json
import math

import numpy as np
import pytest
from conftest import REPO

from fmcw_radar import guispec as g
from fmcw_radar.config import RadarConfig, apply_overrides, config_to_dict, load_config
from fmcw_radar.config.form import SECTIONS, form_paths
from fmcw_radar.config.schema import BANDS
from fmcw_radar.engine import run_radar
from fmcw_radar.engine.statistical import run_statistical
from fmcw_radar.engine.timedomain import run_time
from fmcw_radar.report import report

CONTROLS = g.controls()
BY = {c.path: c for c in CONTROLS}
NUMERIC = ("int", "float", "opt_int", "opt_float")


# ---------------------------------------------------------------- the list

def test_every_control_is_a_form_field_and_every_field_is_a_control_or_hidden():
    ctl = [c.path for c in CONTROLS]
    assert len(ctl) == len(set(ctl)) and set(ctl) | set(g.HIDDEN) == set(form_paths()) and not set(ctl) & set(g.HIDDEN)
    assert [c.path for c in CONTROLS] == [p for p in form_paths() if p not in g.HIDDEN]          # the form's order
    assert list(g.GROUPS) == [sec for sec, _, _ in SECTIONS] and all(c.group in g.GROUPS for c in CONTROLS)
    assert {c.kind for c in CONTROLS} <= {"bool", "enum", "opt_enum", "float", "int", "opt_float", "opt_int", "opt_str", "table"}
    for c in CONTROLS:
        assert c.zh and c.en and "[" not in c.en and "(empty" not in c.en and not c.en.startswith("..."), c.path
        assert c.seen in ("report", "frame", "run")
    assert set(g.ZH) == set(form_paths()) and set(g.COMMON) <= set(ctl) and len(set(g.COMMON)) == len(g.COMMON) == 34
    for table in (g.RANGES, g.WHEN, g.SEEN, g.EN):
        assert set(table) <= set(form_paths()), set(table) - set(form_paths())
    assert BY["chirp.duration_s"].unit == "µs" and BY["chirp.duration_s"].scale == 1e-6 and BY["lo.kdco_hz"].unit == "kHz/LSB"
    assert BY["mimo.rx_spacing_lambda"].unit == "λ" and BY["target.angle_deg"].unit == "°" and BY["lo.tdc_res_s"].unit == "ps"


def test_defaults_are_read_from_the_config_never_typed():
    d = g.values_from_config(RadarConfig())
    assert set(d) == set(form_paths())
    for c in CONTROLS:
        assert c.default == d[c.path], c.path
    # the default form builds the default config, and so does an empty one
    assert g.values_to_config({c.path: c.default for c in CONTROLS}) == RadarConfig()
    assert g.values_to_config({}) == RadarConfig()
    assert g.diff(g.values_to_config({"target.range_m": 7.0}), RadarConfig()) == [{"path": "target.range_m", "a": 7.0, "b": 5.0}]


@pytest.mark.parametrize("name", ["radar_60g_sensing", "radar_60g_mimo", "radar_60g_x10lo", "radar_60g_dither", "radar_77g_automotive"])
def test_bundled_configs_round_trip_through_the_form(name):
    cfg = load_config(REPO / "configs" / f"{name}.yaml")
    assert g.values_to_config(g.values_from_config(cfg), canonical=False) == cfg
    # written canonically, only fields that spelled out the source table's own number change (to empty)
    for row in g.diff(cfg, g.values_to_config(g.values_from_config(cfg))):
        assert row["b"] is None and float(row["a"]) == float(g.resolve(cfg, row["path"])[0]), row


def test_the_number_behind_an_empty_field_is_the_librarys_own():
    """18 fields have a sourced number behind them when left empty; it is
    read through the library's lookups, so it follows the band, the target
    kind and -- for the in-band compression point -- the receive gain."""
    cfg = RadarConfig()
    sourced = {c.path: c for c in CONTROLS if c.source}
    assert len(sourced) == 18 and all(c.default is None for c in sourced.values())
    assert sourced["frontend.tx_power_dbm"].resolved == cfg.frontend_value("tx_power_dbm")[0] == 12.0
    assert (sourced["frontend.tx_power_dbm"].source, sourced["frontend.tx_power_dbm"].sources_key) == ("spec", "60g_sensing.tx_power_dbm")
    assert sourced["lo.tdc_res_s"].resolved == cfg.lo_value("tdc_res_s")[0] and sourced["lo.mult"].resolved == cfg.lo_mult == 4
    assert sourced["channel.oxygen_db_per_km"].source == "derived" and sourced["target.rcs_dbsm"].sources_key == "rcs.human_dbsm"
    from fmcw_radar import sources
    for c in sourced.values():
        assert sources.number(c.sources_key).source == c.source, c.path
    # an empty field that only means "not set" has no number and no tag
    for path in ("lo.profile", "mimo.tx_spacing_lambda", "leakage.reflector_range_m", "regulatory.scenario", "sim.time_n_chirps",
                 "mimo.coupling.touchstone"):
        assert BY[path].default is None and BY[path].resolved is None and BY[path].source is None, path
    assert g.resolve(apply_overrides(cfg, {"target.kind": "car"}), "target.rcs_dbsm")[2] == "rcs.car_dbsm"
    assert g.resolve(apply_overrides(cfg, {"target.kind": "custom", "target.rcs_dbsm": 3.0}), "target.rcs_dbsm") is None
    assert g.resolve(apply_overrides(cfg, {"frontend.rx_gain_db": 44.0}), "frontend.p1db_inband_dbm")[0] == pytest.approx(-38.0)
    assert g.resolve(apply_overrides(cfg, {"frontend.nf_db": 9.0}), "frontend.nf_db")[:2] == (12.0, "spec")       # the table's, not the edit


def test_ranges_hold_the_defaults_and_units_round_trip():
    for c in CONTROLS:
        if c.kind in NUMERIC:
            assert c.lo is not None and c.hi is not None and c.step and c.step > 0 and c.lo < c.hi, c.path
            v = c.default if c.default is not None else c.resolved
            if v is not None:
                assert c.lo - 1e-9 <= g.to_display(c, v) <= c.hi + 1e-9, (c.path, g.to_display(c, v), c.lo, c.hi)
                back = g.from_display(c, g.to_display(c, v))
                assert back == pytest.approx(v, rel=1e-12) and type(back) is (int if c.kind in ("int", "opt_int") else float), c.path
        else:
            assert c.lo is None and c.step is None, c.path
        assert g.from_display(c, "") is None and g.from_display(c, None) is None
    assert g.to_display(BY["chirp.duration_s"], 100e-6) == pytest.approx(100.0) and g.from_display(BY["lo.tdc_res_s"], 12.2) == pytest.approx(12.2e-12)
    assert g.from_display(BY["chirp.n_chirps"], "64") == 64 and g.from_display(BY["lo.engine"], "event") == "event"


# ---------------------------------------------------------------- every control acts

FAST = {"chirp.n_chirps": 8, "lo.engine": "response"}       # the linearised engine: 0.1 s a report instead of 1.2 s
#: a value that satisfies a "gt" or a "set" atom
EXAMPLE = {"lo.profile": g.bundled_profiles()[0], "leakage.reflector_range_m": 0.02, "rx.hpf_corner_hz": 200e3,
           "lo.tdc_dither_lsb": 1.0, "mimo.n_rx": 4, "mimo.n_tx": 2}
#: physics the turn needs besides the declared settings.  Off broadside: at 0 deg the element pattern is 1 and the
#: coupling's bias on the angle is 0 by symmetry, so the array's controls are turned with the target at 20 deg --
#: and on four receivers: two virtual elements under the default Hann angle window have both weights zero and the
#: estimate is garbage (found by this test, ROADMAP P1).  A mismatch for the calibration's controls to work on.
ALSO = {"mimo": {"target.angle_deg": 20.0, "mimo.n_rx": 4},
        "lo.dp_cal_iterations": {"lo.dp_gain": 1.05}, "lo.dp_cal_mu": {"lo.dp_gain": 1.05}, "lo.dp_cal_window_cycles": {"lo.dp_gain": 1.05}}
#: one step from the default is not a legal config, or not a turn: the value to turn to instead
TURN_TO = {"lo.profile": g.bundled_profiles()[0], "extra_targets": [{"kind": "car", "range_m": 8.0}], "regulatory.scenario": "indoor",
           "sim.time_n_chirps": 2, "mimo.tx_spacing_lambda": 1.5, "leakage.reflector_range_m": 0.05, "sim.engine": "time"}


def _plain(o):
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, np.ndarray):
        return _plain(o.tolist())
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else repr(v)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


@functools.lru_cache(maxsize=None)
def _report(key: str) -> str:
    cfg = apply_overrides(RadarConfig(), json.loads(key))
    with np.errstate(all="ignore"):
        return json.dumps(_plain(report(cfg, run_statistical(cfg))), sort_keys=True)


@functools.lru_cache(maxsize=None)
def _frame(key: str):
    cfg = apply_overrides(RadarConfig(), {**json.loads(key), "chirp.n_chirps": 4})
    return run_time(cfg).frame


def _see(seen: str, overrides: dict):
    key = json.dumps(overrides, sort_keys=True)
    if seen == "report":
        return _report(key)
    if seen == "frame":
        return _frame(key)
    cfg = apply_overrides(RadarConfig(), {**overrides, "chirp.n_chirps": 4})
    r = run_radar(cfg)
    return (r.stat is not None, r.time is not None)


def _same(a, b) -> bool:
    if isinstance(a, np.ndarray):
        return a.shape == b.shape and bool(np.array_equal(a, b))
    return a == b


def _satisfy(atoms) -> dict:
    out = {}
    for a in atoms:
        out[a["path"]] = a["value"][0] if a["op"] == "in" else EXAMPLE[a["path"]]
    return out


def _context(c: g.Control) -> dict:
    return {**FAST, **ALSO.get(c.group, {}), **ALSO.get(c.path, {}), **_satisfy(c.when)}


def _turned(c: g.Control, ctx: dict, tmp_path=None):
    """The control one step from where it stands in ``ctx`` (config units)."""
    if c.path == "band.kind":
        return None                                      # turned through band_switch, below
    if c.path == "mimo.coupling.touchstone":
        from fmcw_radar.mimo import VirtualArray
        from fmcw_radar.vendor.arraytx.coupling import write_matrix_touchstone

        va = VirtualArray(apply_overrides(RadarConfig(), {**ctx, "mimo.coupling.source": "analytic", "mimo.coupling.touchstone": None}))
        path = tmp_path / "c.s4p"
        write_matrix_touchstone(str(path), va.coupling)
        return str(path)
    if c.path in TURN_TO:
        return TURN_TO[c.path]
    cur = ctx.get(c.path, c.default)
    if c.kind == "bool":
        return not cur
    if c.kind in ("enum", "opt_enum"):
        ok = [o for o in c.choices if o != cur and all(_holds(a, ctx) for opt, atoms in c.choice_when if opt == o for a in atoms)]
        return ok[0]
    cur = c.resolved if cur is None else cur
    d = g.to_display(c, cur) + c.step
    if d > c.hi:
        d = g.to_display(c, cur) - c.step
    return g.from_display(c, d)


def _holds(atom, ctx) -> bool:
    return g._holds(atom, {**g.values_from_config(RadarConfig()), **ctx})


@pytest.mark.parametrize("path", [c.path for c in CONTROLS if c.path not in ("band.kind", "chirp.shape")])
def test_every_control_moves_the_output_it_says_it_moves(path, tmp_path):
    """One step of the control -- its own ``step``, from its default or its
    resolved placeholder -- in the settings its ``when`` declares, and the
    output named by ``seen`` is no longer the same: the statistical report,
    the time engine's frame, or what the run holds."""
    c = BY[path]
    ctx = _context(c)
    if path == "mimo.coupling.touchstone":
        # the file's own content: the analytic matrix scaled, so the angle estimate reads another bias
        ctx = {**ctx, "mimo.coupling.touchstone": None, "mimo.coupling.source": "analytic", "mimo.coupling.c1_db": -10.0}
        base = _see(c.seen, ctx)
        alt = {**_context(c), "mimo.coupling.touchstone": _turned(c, _context(c), tmp_path)}
        assert not _same(base, _see(c.seen, alt)), path
        return
    alt = {**ctx, path: _turned(c, ctx, tmp_path)}
    apply_overrides(RadarConfig(), alt)                                  # one step is a legal config
    assert not _same(_see(c.seen, ctx), _see(c.seen, alt)), (path, ctx, alt[path])


def test_the_band_is_switched_with_its_sweep_and_one_option_controls_cannot_turn():
    """``band.kind`` alone is not a legal edit (the 60 GHz sweep lies outside
    the 77 GHz window): ``band_switch`` moves the sweep into the new window,
    and the fields left empty then read the new band's placeholders."""
    with pytest.raises(ValueError, match="leaves the 77g_automotive window"):
        g.values_to_config({"band.kind": "77g_automotive"})
    v = g.band_switch({}, "77g_automotive")
    cfg = g.values_to_config(v)
    lo, hi = BANDS["77g_automotive"]
    assert cfg.band.kind == "77g_automotive" and cfg.band.center_hz == 0.5 * (lo + hi) and cfg.band.sweep_hz == RadarConfig().band.sweep_hz
    assert g.resolve(cfg, "frontend.tx_backoff_db")[0] == 0.0 and g.resolve(cfg, "channel.oxygen_db_per_km")[2] == "oxygen.77g_db_per_km"
    assert {c.path: c.sources_key for c in g.controls(cfg)}["frontend.nf_db"] == "77g_automotive.nf_db"
    assert _report(json.dumps({**FAST, **v}, sort_keys=True)) != _report(json.dumps(FAST, sort_keys=True))
    wide = g.band_switch({"band.sweep_hz": 7.0e9}, "77g_automotive")
    assert wide["band.sweep_hz"] == hi - lo and g.values_to_config(wide).band.sweep_hz == 5.0e9
    back = g.band_switch(v, "60g_sensing")
    assert g.values_to_config(back).band.center_hz == 60.5e9
    # a choice with one option is shown, not turned: the only such control is the chirp's shape
    assert [c.path for c in CONTROLS if c.choices is not None and len(c.choices) < 2] == ["chirp.shape"]


def test_a_control_whose_condition_fails_moves_nothing():
    """The other half of ``when``: with the declared settings off -- the
    defaults -- one step of the control leaves its output bit for bit as it
    was.  That is what lets a page grey it out and say why."""
    idle = g.inert(FAST)
    for c in CONTROLS:
        if not c.when:
            continue
        ctx = dict(FAST)
        if c.path not in idle:                           # its condition holds here: nothing to check
            assert all(_holds(a, ctx) for a in c.when), c.path
            continue
        if c.path in ("mimo.coupling.touchstone", "lo.dp_cal_iterations"):
            continue
        alt = {**ctx, c.path: _turned(c, {**ctx, **{k: v for k, v in _satisfy(c.when).items() if k == c.path}})}
        try:
            apply_overrides(RadarConfig(), alt)
        except ValueError:
            continue                                     # the schema refuses the edit outright (the dither's gain error without dither)
        assert _same(_see(c.seen, ctx), _see(c.seen, alt)), c.path
    assert sorted(idle) == sorted(c.path for c in CONTROLS if c.when and c.path != "lo.dp_cal_iterations")      # offline is the default
    assert sorted(set(idle) - set(g.inert({}))) == ["lo.settle_cycles"]                                          # ... and so is event
    idle = g.inert({})
    # ... and the reason a page shows is the atom that fails
    assert idle["mimo.coupling.c1_db"] == [g._gt("mimo.n_rx", 1), g._in("mimo.coupling.source", "analytic", "survey")]
    assert "mimo.coupling.c1_db" not in g.inert({"mimo.n_rx": 4, "mimo.coupling.source": "survey"})
    assert g.inert({"lo.engine": "response"})["lo.settle_cycles"] == [g._in("lo.engine", "event")]
    assert g.inert({"leakage.enabled": True})["leakage.reflector_level_db"] == [g._set("leakage.reflector_range_m")]


def test_online_calibration_is_the_event_engines_only():
    """Found by turning the knobs: with ``lo.engine: response`` the library
    takes ``lo.dp_cal: online`` and runs the chirp uncalibrated, with no
    note -- the same curve as ``none``.  The spec says so (``CHOICE_WHEN``),
    so a page can refuse the pair; this pins the behaviour the declaration
    rests on (ROADMAP: the engine should say it itself)."""
    mis = {**FAST, "lo.dp_gain": 1.05}
    chirp = lambda cal: json.loads(_report(json.dumps({**mis, "lo.dp_cal": cal}, sort_keys=True)))["chirp"]      # noqa: E731
    assert chirp("online") == chirp("none") and chirp("online")["dp_gain_used"] == 1.05 and chirp("online")["notes"] == []
    assert chirp("offline")["dp_gain_used"] == pytest.approx(1.0, abs=1e-4)
    assert g.inert({"lo.engine": "response", "lo.dp_cal": "online"})["lo.dp_cal=online"] == [g._in("lo.engine", "event")]
    assert "lo.dp_cal=online" not in g.inert({"lo.dp_cal": "online"})            # the default engine is event
    assert BY["lo.dp_cal"].choice_when == (("online", (g._in("lo.engine", "event"),)),)


def test_hidden_fields_move_nothing():
    """``sim.pn_bins_per_decade`` is in the schema and no engine reads it:
    20, 60 and 120 give the same report and the same frame.  It is not
    offered; if it is ever wired up this test says to take it out of
    ``HIDDEN``."""
    assert list(g.HIDDEN) == ["sim.pn_bins_per_decade"]
    for path in g.HIDDEN:
        for v in (20, 120):
            assert _same(_see("report", FAST), _see("report", {**FAST, path: v})), path
            assert _same(_see("frame", FAST), _see("frame", {**FAST, path: v})), path


def test_the_high_pass_alone_shows_in_the_time_engine_only():
    """Found by turning the knobs: without the leakage the statistical
    report does not move with the IF high-pass at all, while the time
    engine filters the frame -- a corner at 1 MHz under the 1.33 MHz beat
    takes 1.1 dB off the target there.  Hence ``seen: frame`` for the two
    controls (ROADMAP P1: the statistical budget applies the filter inside
    the leakage budget only)."""
    hp = {**FAST, "rx.hpf_corner_hz": 1.0e6, "rx.hpf_order": 2}
    assert _same(_see("report", FAST), _see("report", hp))
    off, on = (run_time(apply_overrides(RadarConfig(), {**o, "chirp.n_chirps": 4})) for o in (FAST, hp))
    drop = 10.0 * math.log10(on.extras["peak_power"] / off.extras["peak_power"])
    assert drop == pytest.approx(-1.08, abs=0.1)
    assert BY["rx.hpf_corner_hz"].seen == BY["rx.hpf_order"].seen == "frame"
    # with the leakage on it is in the statistical budget
    leak = {**FAST, "leakage.enabled": True}
    assert not _same(_see("report", {**leak, "rx.hpf_corner_hz": 200e3}), _see("report", leak))


# ---------------------------------------------------------------- tags, spec

def test_a_number_edited_on_the_page_is_assumed():
    t0 = g.tags({})
    assert t0["frontend.tx_power_dbm"] == "spec" and t0["frontend.tx_gain_dbi"] == "assumed" and t0["channel.oxygen_db_per_km"] == "derived"
    assert set(t0) == {c.path for c in CONTROLS if c.source}                     # design decisions carry no tag
    t = g.tags({"frontend.tx_power_dbm": 10.0, "frontend.nf_db": 12.0, "target.range_m": 9.0})
    assert t["frontend.tx_power_dbm"] == "assumed" and t["frontend.nf_db"] == "spec" and "target.range_m" not in t
    assert g.tags({"target.kind": "custom", "target.rcs_dbsm": 0.0})["target.rcs_dbsm"] == "assumed"
    assert g.tags(g.band_switch({}, "77g_automotive"))["frontend.tx_power_dbm"] == "assumed"       # that band's figures are placeholders
    # typing the table's own number into a field changes nothing: the config is the same object, value for value
    same = g.values_to_config({"frontend.tx_power_dbm": 12.0, "lo.tdc_res_s": 12.2e-12})
    assert same == RadarConfig() and same.frontend.tx_power_dbm is None
    kept = g.values_to_config({"frontend.tx_power_dbm": 12.0}, canonical=False)
    assert kept.frontend.tx_power_dbm == 12.0 and kept.frontend_value("tx_power_dbm") == (12.0, "config")
    edited = g.values_to_config({"frontend.tx_power_dbm": 10.0})
    assert edited.frontend.tx_power_dbm == 10.0 and g.diff(edited, RadarConfig()) == [{"path": "frontend.tx_power_dbm", "a": 10.0, "b": None}]
    with pytest.raises(ValueError, match="tx_backoff_db is a reduction"):
        g.values_to_config({"frontend.tx_backoff_db": -1.0})


def test_spec_is_json_ready_and_the_metrics_are_in_the_report():
    s = g.spec()
    text = json.dumps(s, ensure_ascii=False)
    assert len(s["controls"]) == len(CONTROLS) == 88 and [x["id"] for x in s["groups"]] == list(g.GROUPS)
    assert s["hidden"] == g.HIDDEN and set(s["tags"]) == {"spec", "survey", "assumed", "derived"} and "config" not in s["tags"]
    assert json.loads(text)["controls"][0]["path"] == "band.kind"
    rep = json.loads(_report(json.dumps(FAST, sort_keys=True)))
    for name, m in g.METRICS.items():
        node = rep
        for k in m["report"].split("."):
            assert k in node, (name, m["report"])
            node = node[k]
        assert isinstance(node, (int, float, bool)) and m["zh"] and m["en"] and m["better"] in ("higher", "lower", None), name
    # an engine entry for the two engines of a run and for every chirp engine the config offers
    assert set(g.ENGINES) == {"statistical", "time"} | {f"chirp:{e}" for e in BY["lo.engine"].choices}
    assert all(v[k] for v in g.ENGINES.values() for k in ("zh", "en", "does_zh", "does_en", "covers_zh", "covers_en"))
    assert config_to_dict(RadarConfig())["lo"]["engine"] == "event"

"""tools/budget_report.py: one page from the config, every input with its source."""

import importlib.util
import json

from conftest import REPO

from fmcw_radar.config import apply_overrides, load_config
from fmcw_radar.report import report, sources_markdown, to_markdown
from fmcw_radar.engine.statistical import run_statistical


def test_report_carries_every_section_and_source(cfg60):
    cfg = apply_overrides(cfg60, {"chirp.n_chirps": 3})
    rep = report(cfg, run_statistical(cfg))
    md = to_markdown(rep)
    for word in ("## Link budget", "## Inputs and their sources", "## LO phase noise after range correlation",
                 "## Chirp linearity", "source: spec", "| oxygen_db_per_km | 14.65 | derived |", "assumed", "cycle-accurate"):
        assert word in md, word
    assert {v["source"] for v in rep["inputs"].values()} == {"assumed", "config", "spec", "derived"}
    assert len(rep["phase_noise"]["floor"]) == 6
    assert "| 60g_sensing.nf_db |" in sources_markdown()


def test_report_says_where_the_lo_profile_stops_being_the_answer(cfg60):
    """ROADMAP P1 #1(c): parked, the default loop is in the TDC's dead zone.
    The report says so, with the loop's own note, and says which parked
    state the config actually has."""
    cfg = apply_overrides(cfg60, {"chirp.n_chirps": 3})
    rep = report(cfg, run_statistical(cfg))
    md = to_markdown(rep)
    assert rep["phase_noise"]["parked"]["dead_zone_center"] and len(rep["phase_noise"]["notes"]) == 1
    for word in ("### The LO while it is not ramping", "FCW 150, an integer: **in the dead zone**", "no idle time between ramps",
                 "No number in this report describes the LO there.", "> TDC dead zone: integer-N (FCW 150)"):
        assert word in md, word
    idle = apply_overrides(cfg, {"chirp.idle_s": 10e-6, "band.sweep_hz": 2e9, "lo.tdc_jitter_s": 6.5e-12})
    md = to_markdown(report(idle, run_statistical(idle)))
    assert "`chirp.idle_s` = 10 us, 9.1 % of the PRI" in md and "FCW 147.5: not in the dead zone (fractional-N)" in md
    assert "FCW 150: not in the dead zone (enough dither)" in md and "No number in this report" not in md and "> TDC dead zone" not in md
    file = apply_overrides(cfg, {"lo.profile": "data/clock_profiles/adpll_15g_fingerprint.yaml"})
    assert "its loop is not analysed here" in to_markdown(report(file, run_statistical(file)))


def test_cli_writes_markdown_and_json(tmp_path):
    spec = importlib.util.spec_from_file_location("budget_report", REPO / "tools" / "budget_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out, js = tmp_path / "b.md", tmp_path / "b.json"
    assert mod.main([str(REPO / "configs" / "radar_77g_automotive.yaml"), "-o", str(out), "--json", str(js), "--sources"]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# FMCW radar budget: 77g_automotive") and "## Every sourced number" in text
    d = json.loads(js.read_text(encoding="utf-8"))
    assert d["radar"]["band"] == "77g_automotive" and d["target"]["in_if_band"] is True


def test_out_of_band_target_is_said_so(cfg60):
    cfg = apply_overrides(cfg60, {"target.range_m": 20.0, "chirp.n_chirps": 3})
    assert cfg.beat_hz() > cfg.rx.if_bw_hz
    md = to_markdown(report(cfg, run_statistical(cfg)))
    assert "OUTSIDE the IF band" in md
    assert load_config(REPO / "configs" / "radar_60g_sensing.yaml").beat_hz() < cfg60.rx.if_bw_hz

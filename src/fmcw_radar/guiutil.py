"""What a page shows for one run: the compute layer of the GUI.

``guispec`` describes; this module computes -- and "computes" means
orchestrates: every number comes from the library's own entry points
(``run_statistical``, ``report.report``, ``link_budget``,
``compliance_check``, ``run_time``).  ``tests/test_guiutil.py`` holds the
report inside ``run_report`` equal, value for value, to the one the command
line gives for the same config.

What it adds, because a page needs it and the library had no place for it:

* ``config_hash``: sha256 of the resolved config as canonical JSON -- the
  reproducibility card's handle on "which run was this";
* the full-power column of the link budget (the same budget with the
  backoff at 0), for the page's two-column comparison;
* plot data (the LO's L(f) and its residual at the target, the ghost
  stems, the level diagram, the transmit timing) -- numbers only, the page
  draws;
* for the time engine's frame: the range-Doppler map pooled to a size a
  page can draw, and every CFAR cell labelled by where it lies.  The labels
  are positional (``classify_cells`` says the rule); the library itself
  only lists threshold crossings.

A value the config refuses is not an exception here: ``run_report`` returns
``{"ok": False, "error": <the schema's sentence>, "field": <path>}`` for
the page to put beside the control.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__, guispec
from .config import RadarConfig, apply_overrides, config_to_dict
from .engine.statistical import run_statistical
from .engine.timedomain import run_time
from .link import compliance_check, leakage_budget, link_budget
from .link.budget import with_compression
from .lo import LOProfile
from .phase_noise.range_correlation import RangeCorrelation
from .report import report as build_report

C0 = 299_792_458.0
#: the labels ``classify_cells`` gives, in the order they are tried
CELL_KINDS = ("leakage", "target_lobe", "other_target_lobe", "ghost", "target_doppler_row", "elsewhere")


def plain(obj: Any) -> Any:
    """JSON-ready: numpy scalars and arrays to Python, non-finite floats to None."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return plain(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def config_hash(cfg: RadarConfig) -> str:
    """sha256 of the resolved config as canonical JSON (sorted keys, no
    whitespace): two configs hash alike exactly when ``config_to_dict``
    gives the same values."""
    blob = json.dumps(plain(config_to_dict(cfg)), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


@functools.lru_cache(maxsize=1)
def vendored_pins() -> tuple[tuple[str, str], ...]:
    """``(repo, pin)`` of every vendored library, read from the
    ``# Vendored from <repo>@<sha>`` header of the files under ``vendor/``."""
    root = Path(__file__).resolve().parent / "vendor"
    found = set()
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".yaml", ".yml"):
            try:
                head = p.read_text(encoding="utf-8", errors="ignore")[:400]
            except OSError:
                continue
            found.update(re.findall(r"# Vendored from ([\w_]+)@([0-9a-f]{7,40})", head))
    return tuple(sorted(found))


def validate(values: dict[str, Any]) -> dict:
    """``{"ok": True, "config": cfg}`` or ``{"ok": False, "error", "field"}``:
    the schema's own sentence and the control it names (its leading dotted
    path, when it starts with one)."""
    try:
        return {"ok": True, "config": guispec.values_to_config(values)}
    except (ValueError, TypeError, KeyError) as e:
        msg = str(e)
        m = re.match(r"([a-z_]+(?:\.[a-z0-9_]+)+)", msg)
        paths = set(guispec.values_from_config(RadarConfig()))
        field = m.group(1) if m and m.group(1) in paths else None
        if field is None:
            field = next((p for p in sorted(paths, key=len, reverse=True) if p in msg), None)
        return {"ok": False, "error": msg, "field": field}


# ---------------------------------------------------------------- one run: the statistical report

def _budget_rows(b) -> list[dict]:
    return [{"term": lab, "value": v, "unit": u} for lab, v, u in b.as_rows()]


def full_power(cfg: RadarConfig) -> dict | None:
    """The link budget with the transmitter at its full power (backoff 0),
    the receiver's compression by the leakage included as the statistical
    engine includes it -- closed form, no chirp engine.  None when the
    config is at full power already."""
    if cfg.frontend_value("tx_backoff_db")[0] == 0.0:
        return None
    c0 = apply_overrides(cfg, {"frontend.tx_backoff_db": 0.0})
    b = link_budget(c0)
    leak = leakage_budget(c0, b)
    if leak is not None:
        b = with_compression(b, leak.compression_signal_db, leak.compression_noise_db)
    k = compliance_check(c0)
    return {"budget": _budget_rows(b), "eirp_dbm": b.eirp_dbm, "snr_cell_db": b.snr_cell_db,
            "compliance": {"applies": k.applies, "verdict": k.verdict, "compliant": None if k.tier is None else k.tier.compliant,
                           "eirp_margin_db": None if k.tier is None else k.tier.eirp_margin_db}}


def _pn_curves(cfg: RadarConfig) -> dict:
    prof = LOProfile.from_config(cfg)
    f = np.logspace(4, math.log10(0.5 * cfg.lo.fref_hz), 90)
    rc = RangeCorrelation.from_config(cfg)
    comp = {}
    for name, s in (prof.components or {}).items():
        comp[name] = np.round(10.0 * np.log10(np.maximum(np.interp(f, prof.f_hz, s) / 2.0, 1e-30)), 2).tolist()
    return {"f_hz": np.round(f, 1).tolist(), "lo_l_dbc_hz": np.round(prof.l_dbc(f), 2).tolist(),
            "residual_l_dbc_hz": np.round(rc.residual_l_dbc(f), 2).tolist(), "components_l_dbc_hz": comp,
            "l_1mhz_dbc_hz": float(prof.l_dbc(1e6)), "tau_s": 2.0 * cfg.target.range_m / C0, "source": prof.source}


def _levels(rep: dict, full: dict | None, k: dict) -> list[dict]:
    """The signal from the transmitter to the ADC: what it can deliver, after
    the backoff, EIRP, at the receive antenna, at the ADC -- now and (when
    backed off) at full power."""
    def row(rows, term):
        return next(r["value"] for r in rows if r["term"] == term)

    tx_gain = rep["inputs"]["tx_gain_dbi"]["value"]
    now = [k["tx_power_dbm"], k["conducted_dbm"], k["eirp_dbm"], row(rep["budget"], "received power P_r"), row(rep["budget"], "signal at the ADC")]
    fp = None
    if full is not None:
        fp = [k["tx_power_dbm"], k["tx_power_dbm"], full["eirp_dbm"], row(full["budget"], "received power P_r"), row(full["budget"], "signal at the ADC")]
        assert abs(fp[2] - (k["tx_power_dbm"] + tx_gain)) < 1e-9
    ids = ("tx_power", "conducted", "eirp", "p_r", "adc")
    return [{"id": i, "now": now[n], "full_power": None if fp is None else fp[n]} for n, i in enumerate(ids)]


def run_report(values: dict[str, Any]) -> dict:
    """One statistical run for the page: the library's report with what the
    page shows around it.  JSON-ready."""
    v = validate(values)
    if not v["ok"]:
        return {"ok": False, "error": v["error"], "field": v["field"], "inert": guispec.inert(values),
                "refused": guispec.refused_choices(values)}
    cfg: RadarConfig = v["config"]
    t0 = time.perf_counter()
    st = run_statistical(cfg)
    wall = time.perf_counter() - t0
    rep = plain(build_report(cfg, st))
    flat = guispec.values_from_config(cfg)
    full = plain(full_power(cfg))
    k = rep["compliance"]
    metrics = {}
    for name, m in guispec.METRICS.items():
        node = rep
        for key in m["report"].split("."):
            node = node.get(key) if isinstance(node, dict) else None
        metrics[name] = node
    chirp = rep.get("chirp") or {}
    engines = [
        {"id": "statistical", "wall_s": round(wall, 3)},
        {"id": f"chirp:{cfg.lo.engine}", "vouches_for_spurs": bool(chirp.get("vouches_for_spurs", False)),
         "rms_hz": chirp.get("rms_hz"), "peak_hz": chirp.get("peak_hz"), "notes": list(chirp.get("notes") or [])},
        {"id": "time", "state": "not_run"},
    ]
    nl = rep.get("nonlinearity") or {}
    gov = next((t for t in k.get("tiers", []) if t["tier"] == k.get("governing")), None)
    plots = {
        "pn": plain(_pn_curves(cfg)),
        "ghosts": {"stems": [{"offset_m": g[0], "level_dbc": g[1]} for g in (nl.get("ghosts") or [])],
                   "limit_dbc": nl.get("ghost_limit_dbc"), "vouched": bool(nl.get("ghosts_vouched", False)),
                   "list": (rep.get("cfar") or {}).get("ghosts") or []},
        "levels": _levels(rep, full, k),
        "timing": {"frame_on_s": k.get("frame_on_s"), "frame_period_s": k.get("frame_period_s"),
                   "off_time_required_s": k.get("off_time_required_s"), "off_time_have_s": None if gov is None else gov.get("off_time_have_s"),
                   "window_s": 0.033},
    }
    edits = {p: val for p, val in flat.items() if val != guispec.values_from_config(RadarConfig())[p]}
    call = ("from fmcw_radar.config import RadarConfig, apply_overrides; from fmcw_radar.report import build; "
            f"rep = build(apply_overrides(RadarConfig(), {edits!r}))")
    return {
        "ok": True, "values": plain(flat), "tags": guispec.tags(flat), "inert": guispec.inert(flat),
        "refused": guispec.refused_choices(flat),
        "resolved": {c.path: {"value": c.resolved, "source": c.source, "key": c.sources_key} for c in guispec.controls(cfg) if c.source},
        "report": rep, "full_power": full, "metrics": plain(metrics), "engines": engines, "plots": plots,
        "warnings": list(chirp.get("notes") or []) + list((rep.get("phase_noise") or {}).get("notes") or []),
        "repro": {"seed": cfg.sim.seed, "config_sha256": config_hash(cfg), "library": "fmcw_radar", "version": __version__,
                  "python": sys.version.split()[0], "numpy": np.__version__,
                  "vendored": [{"repo": r, "pin": p} for r, p in vendored_pins()],
                  "edits": plain(edits), "call": call},
        "wall_s": round(wall, 3),
    }


# ---------------------------------------------------------------- the time engine's frame

def pool_max(a: np.ndarray, n_rows: int, n_cols: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``a`` reduced to at most ``n_rows x n_cols`` blocks, each its maximum
    (a peak survives the reduction), with the block edges."""
    n_rows, n_cols = min(n_rows, a.shape[0]), min(n_cols, a.shape[1])
    r = np.linspace(0, a.shape[0], n_rows + 1).round().astype(int)
    c = np.linspace(0, a.shape[1], n_cols + 1).round().astype(int)
    out = np.empty((n_rows, n_cols))
    for i in range(n_rows):
        for j in range(n_cols):
            out[i, j] = a[r[i]:r[i + 1], c[j]:c[j + 1]].max()
    return out, r, c


def classify_cells(cfg: RadarConfig, ghosts: list[dict], detections) -> list[dict]:
    """Every CFAR cell ``(velocity, range)`` of a frame, labelled by where it
    lies.  The rule, tried in this order:

    * ``leakage`` (only with the leakage modelled): within 3 velocity cells
      of zero Doppler, or closer than 4 range cells -- the leakage tone at
      ~0 m and its flyback transient along zero Doppler;
    * ``target_lobe`` / ``other_target_lobe``: within 4 range and 3
      velocity cells of the primary / another target (the zero-padded
      grid's neighbours of the peak);
    * ``ghost``: at the primary target's Doppler and within 2 range cells of
      a listed ghost (``ghost_index`` says which);
    * ``target_doppler_row``: at a target's Doppler, outside every lobe and
      every listed ghost (a strong target's range skirt);
    * ``elsewhere``: the rest (noise false alarms, mostly).

    A label says where a cell is, not what caused it."""
    r0, v0 = cfg.target.range_m, cfg.target.velocity_mps
    dr, dv = cfg.range_resolution_m, cfg.velocity_resolution_mps
    others = [(t.range_m, t.velocity_mps) for t in cfg.targets[1:]]
    out = []
    for v, r in detections:
        kind, ref = "elsewhere", None
        if cfg.leakage.enabled and (abs(v) < 3 * dv or r < 4 * dr):
            kind = "leakage"
        elif abs(r - r0) < 4 * dr and abs(v - v0) < 3 * dv:
            kind = "target_lobe"
        elif any(abs(r - rr) < 4 * dr and abs(v - vv) < 3 * dv for rr, vv in others):
            kind = "other_target_lobe"
        else:
            for i, g in enumerate(ghosts):
                if abs(r - g["range_m"]) < 2 * dr and abs(v - v0) < 3 * dv:
                    kind, ref = "ghost", i
                    break
            else:
                if any(abs(v - vv) < 3 * dv for vv in [v0] + [vv for _, vv in others]):
                    kind = "target_doppler_row"
        cell = {"range_m": round(float(r), 4), "velocity_mps": round(float(v), 4), "kind": kind}
        if ref is not None:
            cell["ghost_index"] = ref
        out.append(cell)
    return out


def run_frame(values: dict[str, Any], rows: int = 64, cols: int = 150) -> dict:
    """The time engine's frame for the page: the range-Doppler map pooled to
    ``rows x cols``, its CFAR cells labelled, and the readings that check
    the statistical engine.  Slow (seconds): a host runs it as a job."""
    v = validate(values)
    if not v["ok"]:
        return {"ok": False, "error": v["error"], "field": v["field"]}
    cfg: RadarConfig = v["config"]
    st = run_statistical(cfg)
    t0 = time.perf_counter()
    tm = run_time(cfg)
    wall = time.perf_counter() - t0
    half = tm.rd_db.shape[1] // 2
    rd = tm.rd_db[:, :half]
    r_ax, v_ax = tm.range_axis_m[:half], tm.velocity_axis_mps
    pooled, re_, ce_ = pool_max(rd - float(rd.max()), rows, cols)
    ghosts = list(st.cfar.get("ghosts") or [])
    cells = classify_cells(cfg, ghosts, tm.cfar_detections)
    counts = {kind: sum(1 for c in cells if c["kind"] == kind) for kind in CELL_KINDS}
    expected = st.extras.get("snr_cell_expected_db")
    return plain({
        "ok": True, "config_sha256": config_hash(cfg), "seed": cfg.sim.seed, "wall_s": round(wall, 3),
        "rd_map": {"rows": pooled.shape[0], "cols": pooled.shape[1], "full_grid_shape": [rd.shape[0], rd.shape[1]],
                   "range_m_col_centres": [round(float(r_ax[ce_[j]:ce_[j + 1]].mean()), 4) for j in range(pooled.shape[1])],
                   "velocity_mps_row_centres": [round(float(v_ax[re_[i]:re_[i + 1]].mean()), 4) for i in range(pooled.shape[0])],
                   "range_m_span": [float(r_ax[0]), float(r_ax[-1])], "velocity_mps_span": [float(v_ax[0]), float(v_ax[-1])],
                   "db_rel_peak": np.round(np.maximum(pooled, -99.9), 1),
                   "noise_floor_db_rel_peak": 10.0 * math.log10(tm.extras["noise_floor"] / tm.extras["peak_power"]),
                   "max_range_m": st.extras["max_range_m"]},
        "cells": cells, "cell_counts": counts,
        "ghosts": ghosts,
        "time_engine": {"n_chirps": tm.n_chirps, "samples_per_chirp": tm.extras.get("n_wave"), "envelope_fs_hz": tm.extras.get("fs_wave_hz"),
                        "peak_range_m": tm.peak_range_m, "peak_range_interp_m": tm.extras.get("peak_range_interp_m"),
                        "peak_velocity_mps": tm.peak_velocity_mps, "snr_cell_db": tm.snr_cell_db,
                        "snr_cell_expected_db": expected,
                        "snr_difference_db": None if expected is None else tm.snr_cell_db - expected,
                        "width_3db_m": tm.width_3db_m, "clipped_fraction": tm.extras.get("clipped_fraction"),
                        "targets_found": tm.extras.get("targets_found"), "angle_deg": tm.extras.get("angle_deg"),
                        "lo_noise_split": tm.extras.get("lo_noise_split")},
    })


__all__ = ["CELL_KINDS", "plain", "config_hash", "vendored_pins", "validate", "full_power", "run_report", "pool_max", "classify_cells",
           "run_frame"]

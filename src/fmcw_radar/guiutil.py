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


def run_report(values: dict[str, Any], baseline: dict | None = None) -> dict:
    """One statistical run for the page: the library's report with what the
    page shows around it.  JSON-ready.

    ``baseline``: ``{"values", "metrics"}`` of an earlier run the page pinned;
    the result then carries ``baseline`` (``compare``)."""
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
                   "strongest_dbc": max((g[1] for g in (nl.get("ghosts") or [])), default=None),
                   "list": (rep.get("cfar") or {}).get("ghosts") or []},
        "levels": _levels(rep, full, k),
        "timing": {"frame_on_s": k.get("frame_on_s"), "frame_period_s": k.get("frame_period_s"),
                   "off_time_required_s": k.get("off_time_required_s"), "off_time_have_s": None if gov is None else gov.get("off_time_have_s"),
                   "window_s": 0.033},
    }
    edits = {p: val for p, val in flat.items() if val != guispec.values_from_config(RadarConfig())[p]}
    call = ("from fmcw_radar.config import RadarConfig, apply_overrides; from fmcw_radar.report import build; "
            f"rep = build(apply_overrides(RadarConfig(), {edits!r}))")
    out = {
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
    out["system"] = system(out, cfg)
    if baseline is not None:
        out["baseline"] = compare(baseline, out, cfg)
    return out


# ---------------------------------------------------------------- the system diagram's numbers

def pick(root: Any, path: str) -> Any:
    """Follow ``a.b[term].c`` into nested data: a dotted key per step,
    ``[x]`` picks from a list of rows the one whose ``term`` is ``x`` (or
    whose ``offset_m`` is the number ``x``).  ``values.<path>`` reads the
    flat values, whose keys are dotted themselves.  None when it is not there."""
    if path.startswith("values."):
        return (root.get("values") or {}).get(path[7:])
    node = root
    for tok in re.findall(r"\[[^\]]*\]|[^.\[\]]+", path):
        if node is None:
            return None
        if tok.startswith("["):
            key = tok[1:-1]
            if not isinstance(node, list):
                return None
            hit = [r for r in node if isinstance(r, dict) and (r.get("term") == key or (
                "offset_m" in r and re.fullmatch(r"-?[0-9.]+", key) and float(key) == r["offset_m"]))]
            node = hit[0] if hit else None
        else:
            node = node.get(tok) if isinstance(node, dict) else None
    return node


def system(run: dict, cfg: RadarConfig) -> dict:
    """``guispec.STAGES`` filled in for this run: every control line with the
    value the library uses (display unit), every read line with its number,
    whether an optional stage is in play, the compliance verdict.  No
    arithmetic beyond the unit scale the spec declares."""
    by = {c.path: c for c in guispec.controls(cfg)}

    def line(ln: dict) -> dict:
        if ln["kind"] == "control":
            c = by[ln["path"]]
            v = run["values"].get(c.path)
            if v is None and c.source:
                v = c.resolved
            return {"kind": "control", "path": c.path, "zh": ln["zh"], "en": ln["en"], "value": plain(guispec.to_display(c, v)), "unit": c.unit}
        if ln["kind"] == "read":
            v = pick(run, ln["read"])
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                v = v / ln["scale"]
            return {"kind": "read", "zh": ln["zh"], "en": ln["en"], "value": v, "unit": ln["unit"], "digits": ln["digits"]}
        return dict(ln)

    stages = []
    for st in guispec.STAGES:
        d = {"id": st["id"], "lane": st["lane"], "zh": st["zh"], "en": st["en"], "lines": [line(x) for x in st["lines"]],
             "out": line(st["out"]) if st.get("out") else None,
             "active": True if "active" not in st else bool(pick(run, st["active"]))}
        if "verdict" in st:
            d["verdict"] = pick(run, st["verdict"])
        stages.append(d)
    return {"stages": stages}


# ---------------------------------------------------------------- a pinned baseline

def compare(baseline: dict, run: dict, cfg: RadarConfig) -> dict:
    """This run against a pinned one: which controls differ and, metric by
    metric, the difference and whether it is an improvement
    (``guispec.METRICS[...]["better"]``; None where neither way is)."""
    base_cfg = validate(baseline.get("values") or {})
    changed = [] if not base_cfg["ok"] else plain(guispec.diff(base_cfg["config"], cfg))
    rows = {}
    for name, m in guispec.METRICS.items():
        a, b = (baseline.get("metrics") or {}).get(name), run["metrics"].get(name)
        if a is None or b is None:
            rows[name] = {"base": a, "now": b, "delta": None, "verdict": None}
            continue
        d = float(b) - float(a)
        if d == 0.0 or m["better"] is None:
            verdict = "same" if d == 0.0 else None
        else:
            verdict = "better" if (d > 0) == (m["better"] == "higher") else "worse"
        rows[name] = {"base": a, "now": b, "delta": d, "verdict": verdict}
    return {"ok": base_cfg["ok"], "config_sha256": None if not base_cfg["ok"] else config_hash(base_cfg["config"]),
            "changed": changed, "metrics": rows}


# ---------------------------------------------------------------- the band trade-off

def detection_range_m(cfg: RadarConfig, snr_req_db: float) -> float:
    """Where the cell SNR of ``link_budget`` falls to ``snr_req_db`` (the
    radar equation and the oxygen; the IF band is not asked) -- a bisection
    on the library's budget, as example 09 does it."""
    lo, hi = 0.5, 5000.0
    for _ in range(60):
        mid = (lo * hi) ** 0.5
        lo, hi = (mid, hi) if link_budget(cfg, range_m=mid).snr_cell_db > snr_req_db else (lo, mid)
    return lo


def band_tradeoff(values: dict[str, Any], progress=None) -> dict:
    """``guispec.BAND_ROWS`` for these settings.  Each row is a real config:
    the sweep moved into that band, the scenario declared, the transmitter
    backed off just to the governing tier's limit and the frame period
    stretched to the off-time the tier asks -- ``apply`` is what to put in
    the form to be there, and the row's numbers are that config's own
    statistical report.  Also: the antenna-gain table (the transmit gain
    stops mattering once the EIRP is held to a limit) and the bundled
    configs as they are."""
    v = validate(values)
    if not v["ok"]:
        return {"ok": False, "error": v["error"], "field": v["field"]}
    cfg: RadarConfig = v["config"]
    flat = guispec.values_from_config(cfg)
    t0 = time.perf_counter()
    k_now = compliance_check(cfg)
    if not k_now.applies:
        return {"ok": True, "applies": False, "why": k_now.why, "rule": k_now.rule, "rows": [], "antenna": [], "bundled": _bundled_verdicts()}
    rows = []
    for n, row in enumerate(guispec.BAND_ROWS):
        if progress is not None:
            progress(n, len(guispec.BAND_ROWS))
        move = {}
        if row["lo_ghz"] is not None:
            move = {"band.center_hz": 0.5e9 * (row["lo_ghz"] + row["hi_ghz"]), "band.sweep_hz": 1e9 * (row["hi_ghz"] - row["lo_ghz"])}
        if row["scenario"] != "as_configured":
            move["regulatory.scenario"] = row["scenario"]
        out = {"id": row["id"], "zh": row["zh"], "en": row["en"]}
        # the transmitter at its full power, the frame period left open: what the band would allow it
        open_ = validate({**flat, **move, "frontend.tx_backoff_db": 0.0, "chirp.frame_period_s": None})
        if not open_["ok"]:
            rows.append({**out, "ok": False, "error": open_["error"], "field": open_["field"]})
            continue
        k0 = compliance_check(open_["config"])
        g = k0.tier
        over = max(0.0, -g.eirp_margin_db)
        period = flat.get("chirp.frame_period_s")
        if g.min_frame_period_s is not None and (period is None or period < g.min_frame_period_s):
            period = math.ceil(g.min_frame_period_s * 1e4) / 1e4            # up to the next 0.1 ms
        apply = {**move, "frontend.tx_backoff_db": over, "chirp.frame_period_s": period}
        r = run_report({**flat, **apply})
        if not r["ok"]:
            rows.append({**out, "ok": False, "error": r["error"], "field": r["field"]})
            continue
        at = guispec.values_to_config({**flat, **apply})
        kk = r["report"]["compliance"]
        rows.append({**out, "ok": True, "apply": plain({p: val for p, val in r["values"].items() if val != flat.get(p)}),
                     "config_sha256": r["repro"]["config_sha256"], "sweep_ghz": kk["sweep_ghz"], "scenario": kk["scenario"],
                     "governing": kk["governing"], "limit_dbm": kk["limit_dbm"], "full_power_eirp_dbm": k0.eirp_dbm,
                     "full_power_over_db": -g.eirp_margin_db, "backoff_db": over, "eirp_dbm": kk["eirp_dbm"],
                     "frame_period_s": period, "off_time_required_s": kk["off_time_required_s"], "max_frame_rate_hz": kk["max_frame_rate_hz"],
                     "compliant": kk["compliant"], "verdict": kk["verdict"], "tiers": kk["tiers"], "metrics": r["metrics"],
                     "detection_range_m": detection_range_m(at, r["metrics"]["snr_pd90_db"])})
    # the antenna gains under the limit: the configured band, the transmitter at full power
    base = apply_overrides(cfg, {"frontend.tx_backoff_db": 0.0})
    gt0, gr0 = cfg.frontend_value("tx_gain_dbi")[0], cfg.frontend_value("rx_gain_dbi")[0]
    antenna = []
    for dt, dr in guispec.ANTENNA_STEPS:
        c = apply_overrides(base, {"frontend.tx_gain_dbi": gt0 + dt, "frontend.rx_gain_dbi": gr0 + dr})
        k = compliance_check(c)
        antenna.append({"tx_gain_dbi": gt0 + dt, "rx_gain_dbi": gr0 + dr, "full_power_eirp_dbm": k.eirp_dbm, "eirp_at_limit_dbm": k.eirp_cap_dbm,
                        "snr_full_power_db": link_budget(c).snr_cell_db, "snr_at_limit_db": link_budget(c, eirp_cap_dbm=k.eirp_cap_dbm).snr_cell_db})
    if progress is not None:
        progress(len(guispec.BAND_ROWS), len(guispec.BAND_ROWS))
    return {"ok": True, "applies": True, "rule": k_now.rule, "config_sha256": config_hash(cfg), "rows": rows, "antenna": plain(antenna),
            "bundled": _bundled_verdicts(), "tx_power_dbm": k_now.conducted_dbm + cfg.frontend_value("tx_backoff_db")[0],
            "wall_s": round(time.perf_counter() - t0, 3)}


@functools.lru_cache(maxsize=1)
def _bundled_verdicts() -> tuple[dict, ...]:
    """The compliance check on the bundled configs as they are."""
    from .config import load_config

    out = []
    for f in sorted((Path(__file__).resolve().parents[2] / "configs").glob("*.yaml")):
        c = load_config(f)
        k = compliance_check(c)
        out.append({"config": f.stem, "n_tx": c.mimo.n_tx, "applies": k.applies, "why": k.why, "verdict": k.verdict,
                    "eirp_dbm": k.eirp_dbm, "compliant": None if k.tier is None else k.tier.compliant,
                    "limit_dbm": None if k.tier is None else k.tier.peak_eirp_limit_dbm})
    return tuple(plain(out))


# ---------------------------------------------------------------- a sweep of one control

def run_sweep(values: dict[str, Any], path: str, lo: float, hi: float, points: int, progress=None) -> dict:
    """The headline metrics with one numeric control stepped from ``lo`` to
    ``hi`` (config units), everything else as it is.  Every point is a full
    statistical run of its own config; a value the schema refuses is a point
    that carries the schema's sentence instead of numbers."""
    c = next((x for x in guispec.controls() if x.path == path), None)
    if c is None or path not in guispec.sweepable():
        return {"ok": False, "error": f"{path}: not a control a sweep can step", "field": None}
    points = int(points)
    if not 2 <= points <= guispec.SWEEP_MAX_POINTS:
        return {"ok": False, "error": f"a sweep takes 2 to {guispec.SWEEP_MAX_POINTS} points, got {points}", "field": None}
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo == hi:
        return {"ok": False, "error": f"{path}: the sweep needs two different ends, got {lo:g} and {hi:g}", "field": path}
    v = validate(values)
    if not v["ok"]:
        return {"ok": False, "error": v["error"], "field": v["field"]}
    flat = guispec.values_from_config(v["config"])
    xs = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    if c.kind in ("int", "opt_int"):
        xs = sorted({int(round(x)) for x in xs}, reverse=hi < lo)
    t0 = time.perf_counter()
    out = []
    for n, x in enumerate(xs):
        if progress is not None:
            progress(n, len(xs))
        r = run_report({**flat, path: x})
        if r["ok"]:
            out.append({"x": x, "ok": True, "metrics": r["metrics"], "config_sha256": r["repro"]["config_sha256"],
                        "in_if_band": r["report"]["target"]["in_if_band"]})
        else:
            out.append({"x": x, "ok": False, "error": r["error"], "field": r["field"]})
    if progress is not None:
        progress(len(xs), len(xs))
    cur = flat.get(path)
    if cur is None:
        cur = next((k.resolved for k in guispec.controls(v["config"]) if k.path == path and k.source), None)
    return {"ok": True, "path": path, "zh": c.zh, "en": c.en, "unit": c.unit, "scale": c.scale, "current": cur, "points": plain(out),
            "config_sha256": config_hash(v["config"]), "wall_s": round(time.perf_counter() - t0, 3)}


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

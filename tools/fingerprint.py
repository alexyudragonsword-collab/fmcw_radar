"""Numerical fingerprint of the engines: prove a change did not move a number (invariant #7).

Tests assert thresholds and relations; a result that moves a little and still
satisfies them passes.  A refactor therefore has to be checked bit for bit
(Halo_Serdes ``tools/fingerprint.py`` method, by way of d2d_link).  This
records every bundled config through the chirp engine, the closed-form link
and phase-noise budget, the statistical engine and the time engine (at a
small size), plus a set of synthetic radars for the paths no config reaches:
the response and ideal chirp engines, a two-point mismatch without
calibration, the online calibrator, a rectangular window, a clock-profile
LO, the 7 GHz sweep.

Scalars are stored by ``repr`` and arrays by SHA-256, so the comparison is
exact.  Bit-exact means the same machine and library versions: record both
sides in one environment.

    python tools/fingerprint.py record before.json     # on the base commit
    python tools/fingerprint.py record after.json      # on the change
    python tools/fingerprint.py compare before.json after.json

``compare`` prints every differing value and exits 1 if there is one.  A
change meant to move numbers (a fix) should move only the ones it explains;
list them in the commit message with the ``(numbers-move: why)`` marker CI
looks for.  Both commands also list the entries that raised instead of
recording values: two sides failing the same way compare equal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def digest(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(np.asarray(a, dtype=np.float64))).hexdigest()[:16]


def _scalar(v) -> str:
    return repr(float(v))


def chirp_values(c) -> dict:
    out = {"engine": c.engine, "f_err": digest(c.f_err_dco_hz), "f_cmd": digest(c.f_cmd_dco_hz),
           "dp_gain_used": _scalar(c.dp_gain_used), "ui99": _scalar(c.ui_per_ref_cycle_p99)}
    for k, v in c.metrics().items():
        out["metric." + k] = _scalar(v)
    for i, p in enumerate(c.dp_cal_passes):
        out[f"cal.{i}.eps"] = _scalar(p["eps_hat"])
    if c.dp_cal_trace is not None:
        out["cal.trace"] = digest(c.dp_cal_trace)
    return out


def stat_values(s) -> dict:
    out = {k: _scalar(getattr(s, k)) for k in ("beat_hz", "doppler_hz", "range_bin", "doppler_bin", "snr_cell_db",
                                               "snr_chirp_db", "pd", "range_res_rect_m", "range_res_m",
                                               "range_res_rayleigh_m", "velocity_res_mps", "window_sidelobe_db",
                                               "pn_rms_rad", "lo_rms_rad")}
    for lab, v, _ in s.budget.as_rows():
        out["budget." + lab] = _scalar(v)
    for dr, (a, b) in s.pn_floor.items():
        out[f"pn.{dr:g}.bin"] = _scalar(a)
        out[f"pn.{dr:g}.cell"] = _scalar(b)
    for k, v in s.nonlinearity.items():
        if isinstance(v, (int, float)):
            out["nl." + k] = _scalar(v)
    for i, (dr, lvl) in enumerate(s.nonlinearity.get("ghosts") or []):
        out[f"nl.ghost.{i}"] = f"{dr!r},{lvl!r}"
    if "nonlinearity_profile" in s.extras:
        out["nl.profile"] = digest(s.extras["nonlinearity_profile"][1])
    for i, t in enumerate(s.targets):
        for k in ("snr_cell_db", "interference_dbc", "margin_db"):
            if t.get(k) is not None:
                out[f"target.{i}.{k}"] = _scalar(t[k])
    for k, v in s.angle.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out["angle." + k] = _scalar(v)
    if s.leakage is not None:
        for lab, v, _ in s.leakage.as_rows():
            out["leak." + lab] = _scalar(v)
    for k, v in getattr(s, "cfar", {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out["cfar." + k] = _scalar(v)
    return out


def time_values(t) -> dict:
    out = {"frame": digest(np.concatenate([t.frame.real.ravel(), t.frame.imag.ravel()])), "rd": digest(t.rd_db),
           "peak_range_m": _scalar(t.peak_range_m), "peak_velocity_mps": _scalar(t.peak_velocity_mps),
           "snr_cell_db": _scalar(t.snr_cell_db), "width_3db_m": _scalar(t.width_3db_m),
           "peak_sidelobe_db": _scalar(t.peak_sidelobe_db), "n_detections": repr(len(t.cfar_detections))}
    for k in ("angle_deg", "clipped_fraction", "clipped_fraction_after_blanking"):
        if k in t.extras:
            out[k] = _scalar(t.extras[k])
    for i, d in enumerate(t.extras.get("targets_found") or []):
        out[f"found.{i}"] = repr(tuple(round(float(x), 6) for x in d))
    return out


def _guarded(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _small(cfg):
    from fmcw_radar.config import apply_overrides

    # few chirps: the time engine on 64 chirps of 500k envelope samples is seconds per config
    return apply_overrides(cfg, {"chirp.n_chirps": 8, "sim.engine": "both"})


def _one(cfg) -> dict:
    from fmcw_radar.engine import run_radar
    from fmcw_radar.phase_noise import RangeCorrelation

    res = run_radar(cfg)
    d = {"stat": stat_values(res.stat)}
    if res.chirp is not None:
        d["chirp"] = chirp_values(res.chirp)
    if res.time is not None:
        d["time"] = time_values(res.time)
    rc = RangeCorrelation.from_config(cfg)
    d["pn.residual"] = digest(rc.synthesize_residual(1 << 12, cfg.rx.adc_fs_hz, np.random.default_rng(5)))
    return d


def record_configs() -> dict:
    from fmcw_radar.config import load_config

    out = {}
    for p in sorted((REPO / "configs").glob("*.yaml")):
        cfg = _small(load_config(p))
        out[p.stem] = _guarded(lambda cfg=cfg: _one(cfg))
        print(f"  config {p.stem}", file=sys.stderr, flush=True)
    return out


def record_synthetic() -> dict:
    from fmcw_radar.config import RadarConfig, apply_overrides

    base = _small(RadarConfig())
    cases = {
        "response_mismatch": apply_overrides(base, {"lo.engine": "response", "lo.dp_gain": 1.05, "lo.dp_cal": "none"}),
        "event_mismatch_nocal": apply_overrides(base, {"lo.dp_gain": 1.02, "lo.dp_cal": "none"}),
        "event_online_cal": apply_overrides(base, {"lo.dp_gain": 1.02, "lo.dp_cal": "online", "chirp.n_chirps": 4}),
        "ideal_rect": apply_overrides(base, {"lo.engine": "ideal", "processing.window_range": "rect",
                                             "processing.window_doppler": "rect"}),
        "sweep_7g_blackman": apply_overrides(base, {"band.center_hz": 60.5e9, "band.sweep_hz": 7.0e9,
                                                    "processing.window_range": "blackman", "sim.time_osr": 1.0,
                                                    "target.range_m": 2.0, "target.velocity_mps": -4.0}),
        "profile_lo": apply_overrides(base, {"lo.profile": "data/clock_profiles/adpll_15g_fingerprint.yaml",
                                             "lo.profile_shift_db": 3.0, "sim.engine": "statistical"}),
        "far_target_idle": apply_overrides(base, {"target.range_m": 12.0, "target.kind": "corner_reflector",
                                                  "chirp.idle_s": 10e-6, "frontend.nf_db": 8.0}),
        # milestone 2 (0.2.0): TDM-MIMO with coupling, several targets, the leakage with its high-pass
        "mimo_2x4_coupled": apply_overrides(base, {"mimo.n_tx": 2, "mimo.n_rx": 4, "target.angle_deg": 20.0,
                                                   "mimo.coupling.source": "survey", "chirp.n_chirps": 8}),
        "mimo_1x4_calibrated_cos": apply_overrides(base, {"mimo.n_rx": 4, "target.angle_deg": -35.0,
                                                          "mimo.coupling.source": "analytic", "mimo.coupling.calibrated": True,
                                                          "mimo.element_pattern": "cos", "mimo.angle_window": "blackman"}),
        "three_targets": apply_overrides(base, {"extra_targets": [{"kind": "car", "range_m": 5.3, "velocity_mps": 2.0},
                                                                   {"kind": "human", "range_m": 9.9, "velocity_mps": -1.0}]}),
        "leakage_hpf": apply_overrides(base, {"leakage.enabled": True, "leakage.reflector_range_m": 0.02,
                                              "rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2}),
        # 0.2.1: the flyback transient blanked at every chirp's start
        "leakage_hpf_blanked": apply_overrides(base, {"leakage.enabled": True, "leakage.reflector_range_m": 0.02,
                                                      "rx.hpf_corner_hz": 200e3, "rx.hpf_order": 2, "rx.blank_s": 4.5e-6}),
    }
    out = {}
    for name, cfg in cases.items():
        out[name] = _guarded(lambda cfg=cfg: _one(cfg))
        print(f"  synthetic {name}", file=sys.stderr, flush=True)
    return out


def compare(a: dict, b: dict) -> tuple[int, list[str]]:
    """(leaf values compared, the differing ones as 'path: old -> new')."""
    diffs, n = [], 0

    def walk(path, x, y):
        nonlocal n
        if isinstance(x, dict) or isinstance(y, dict):
            x = x if isinstance(x, dict) else {}
            y = y if isinstance(y, dict) else {}
            for k in sorted(set(x) | set(y)):
                walk(path + [k], x.get(k), y.get(k))
        else:
            n += 1
            if x != y:
                diffs.append(" / ".join(path) + f": {x!r} -> {y!r}")

    walk([], a, b)
    return n, diffs


def raised(fp: dict) -> list[str]:
    out = []

    def walk(path, x):
        if isinstance(x, dict):
            for k in sorted(x):
                if k == "error":
                    out.append(" / ".join(path) + f": {x[k]}")
                else:
                    walk(path + [k], x[k])

    walk([], fp)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="run the engines and write the fingerprint")
    rec.add_argument("out", type=Path)
    rec.add_argument("--no-synthetic", action="store_true", help="bundled configs only")
    cmp_ = sub.add_parser("compare", help="diff two fingerprints; exit 1 on any difference")
    cmp_.add_argument("a", type=Path)
    cmp_.add_argument("b", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "record":
        warnings.filterwarnings("ignore")
        t0 = time.time()
        fp = {"configs": record_configs()}
        if not args.no_synthetic:
            fp["synthetic"] = record_synthetic()
        args.out.write_text(json.dumps(fp, indent=1, sort_keys=True))
        n, _ = compare(fp, fp)
        print(f"recorded {n} values to {args.out} in {time.time() - t0:.0f} s")
        for line in raised(fp):
            print(f"  raised: {line}")
        return 0

    a = json.loads(args.a.read_text())
    b = json.loads(args.b.read_text())
    n, diffs = compare(a, b)
    for d in diffs:
        print(d)
    bad = raised(b)
    for line in bad:
        print(f"  raised: {line}")
    if bad:
        print(f"{len(bad)} entries raised (compare equal when both sides fail the same way)")
    if diffs:
        print(f"{len(diffs)} of {n} values differ")
        return 1
    print(f"{n} values bit-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())

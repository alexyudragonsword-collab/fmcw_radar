"""The radar's budget as one Markdown (or JSON) page, from the config alone.

    python tools/budget_report.py configs/radar_60g_sensing.yaml
    python tools/budget_report.py configs/radar_60g_sensing.yaml -o budget.md
    python tools/budget_report.py configs/radar_77g_automotive.yaml --json budget.json
    python tools/budget_report.py configs/radar_60g_sensing.yaml --sources

d2d_link's ``tools/budget_report.py`` method.  Everything comes from the
config and the statistical engine (invariants #1, #3): the radar equation
line by line with the source of every input (invariant #5), the detection
SNR and probability, the LO phase noise after range correlation at a table
of range offsets (invariant #2), and the chirp's frequency error and the
range response it leaves (invariant #4).  ``--sources`` appends the whole
table of sourced numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fmcw_radar.config import load_config  # noqa: E402
from fmcw_radar.report import build, sources_markdown, to_markdown  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None, help="write Markdown here instead of stdout")
    ap.add_argument("--json", type=Path, default=None, help="also write the report as JSON")
    ap.add_argument("--sources", action="store_true", help="append the table of every sourced number")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    rep = build(cfg)
    md = to_markdown(rep)
    if args.sources:
        md += "\n" + sources_markdown()
    if args.json is not None:
        args.json.write_text(json.dumps(_plain(rep), indent=1, sort_keys=True), encoding="utf-8")
    if args.out is not None:
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(md)
    return 0


def _plain(obj):
    import numpy as np

    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    return obj


if __name__ == "__main__":
    sys.exit(main())

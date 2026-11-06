"""Shared plumbing for the examples: repo paths, a non-interactive matplotlib,
the smoke flag (d2d_link's ``examples/_common.py`` method)."""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "examples" / "output"
OUT.mkdir(exist_ok=True)
CONFIGS = REPO / "configs"
CONFIG = CONFIGS / "radar_60g_sensing.yaml"
#: set by ``tools/run_examples.py --smoke``: examples whose cost is not in
#: n_chirps (the range sweeps) run a subset; the numbers they print are then
#: not the documented ones
SMOKE = os.environ.get("FMCW_RADAR_SMOKE") == "1"


def plt_or_none():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        return None


def tag(cfg, name: str) -> str:
    """``value (source: x)`` of a front-end number, for the printed lines."""
    v, src = cfg.frontend_value(name)
    return f"{v:g} (source: {src})"

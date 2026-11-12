"""Write the LO's phase-noise profile as a pll_simulator clock-profile YAML.

    python tools/export_lo_profile.py configs/radar_60g_sensing.yaml out.yaml

The file holds the DCO's own L(f) (at ``center / mult``, before the
multiplier) in pll_simulator's export format (``f0_hz``, ``f_hz``,
``l_dbc_hz``, ``spurs``, ``source``), so a config can name it in
``lo.profile`` and the same radar runs from a file instead of the live
analysis -- the way d2d_link and array_tx carry profiles.  The bundled
``data/clock_profiles/adpll_15g_fingerprint.yaml`` was written by this tool
from the default config; tests/test_lo.py checks a config reading it back
gets the live profile within interpolation error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fmcw_radar.config import load_config  # noqa: E402
from fmcw_radar.lo import LOProfile  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args(argv)
    import numpy as np
    import yaml

    cfg = load_config(args.config)
    # the live profile, the TDC-jitter term included, referred back to the DCO; the loop's part only
    # (above fref / 2 the live profile is the DCO alone, which a reader of the file gets from its own floor rule)
    prof = LOProfile.from_config(cfg)
    keep = prof.f_hz <= 0.5 * cfg.lo.fref_hz
    s = prof.s_phi[keep] / (cfg.lo_mult ** 2)
    data = {"f0_hz": float(cfg.dco_center_hz), "f_hz": [float(x) for x in prof.f_hz[keep]],
            "l_dbc_hz": [float(x) for x in 10.0 * np.log10(np.maximum(s, 1e-300) / 2.0)], "spurs": [],
            "source": f"fmcw_radar tools/export_lo_profile.py from {args.config.name}: vendored pll_simulator ADPLL "
                      f"analyze() plus the TDC-jitter term at {cfg.dco_center_hz / 1e9:.4g} GHz (source: assumed placeholder LO)"}
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("# pllsim clock phase-noise profile (fmcw_radar export): L(f) = S_phi/2 of the\n"
                 "# linear model in dBc/Hz at the DCO; the config scales it by (center / mult / f0)^2 mult^2.\n")
        yaml.safe_dump(data, fh, sort_keys=False)
    print(f"wrote {args.out} ({len(data['f_hz'])} points)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

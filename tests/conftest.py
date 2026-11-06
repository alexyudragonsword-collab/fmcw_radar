import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

CONFIG = REPO / "configs" / "radar_60g_sensing.yaml"


def trapz(y, x):
    """numpy 1.x has only trapz, 2.x renames it trapezoid (the declared floor is 1.26)."""
    import numpy as np

    return (getattr(np, "trapezoid", None) or np.trapz)(y, x)


@pytest.fixture(scope="session")
def cfg60():
    from fmcw_radar.config import load_config

    return load_config(CONFIG)

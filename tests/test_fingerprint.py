"""Invariant #7: the fingerprint tool catches a moved value; engines are deterministic."""

import importlib.util
import json

import numpy as np
import pytest
from conftest import REPO

from fmcw_radar.config import RadarConfig, apply_overrides
from fmcw_radar.engine import run_statistical, run_time


@pytest.fixture(scope="module")
def fp():
    spec = importlib.util.spec_from_file_location("fingerprint", REPO / "tools" / "fingerprint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compare_finds_every_kind_of_difference(fp):
    a = {"configs": {"c": {"stat": {"snr": "0.1", "rd": "abc"}}}, "synthetic": {"x": "1"}}
    assert fp.compare(a, json.loads(json.dumps(a))) == (3, [])
    b = {"configs": {"c": {"stat": {"snr": "0.1", "rd": "abd", "new": "1"}}}, "synthetic": {"x": "2"}}
    n, diffs = fp.compare(a, b)
    assert n == 4 and len(diffs) == 3 and diffs[0].startswith("configs / c / stat / new")


def test_compare_cli_exit_codes(fp, tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"k": "1"}))
    b.write_text(json.dumps({"k": "1"}))
    assert fp.main(["compare", str(a), str(b)]) == 0
    b.write_text(json.dumps({"k": "2"}))
    assert fp.main(["compare", str(a), str(b)]) == 1
    assert "k: '1' -> '2'" in capsys.readouterr().out


def test_raised_entries_are_listed(fp):
    side = {"configs": {"c": {"error": "TypeError: bad"}, "d": {"stat": {"snr": "0"}}}}
    assert fp.raised(side) == ["configs / c: TypeError: bad"]


def test_engines_are_deterministic(fp):
    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 3})
    s1, s2 = run_statistical(cfg), run_statistical(cfg)
    assert fp.stat_values(s1) == fp.stat_values(s2)
    t1, t2 = run_time(cfg), run_time(cfg)
    assert fp.time_values(t1) == fp.time_values(t2)
    assert fp.digest(np.arange(3.0)) == fp.digest([0.0, 1.0, 2.0])

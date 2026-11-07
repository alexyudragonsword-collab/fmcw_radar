"""Vendor drift: the vendored tree matches the pinned polar_tx commit.

Runs the real ``tools/vendor_check.py``.  Skips when the sibling checkout is
absent (a bare checkout still passes); the ``vendor-drift`` CI job checks it
out at the pinned SHA and passes ``--strict --fail-on-skip`` so there a skip
is red.  Adapted from d2d_link tests/test_vendor_check.py.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vendor_check", REPO / "tools" / "vendor_check.py")
vc = importlib.util.module_from_spec(_spec)
sys.modules["vendor_check"] = vc
_spec.loader.exec_module(vc)

PINS = {"polar_tx": "70577381f678da34da20fcd083c5052afae1c437", "array_tx": "e897c159e5fc5b2e26af6336cf9f6164461ff7f5"}
PIN = PINS["polar_tx"]


def _siblings():
    return vc.Siblings({})


def test_no_drift():
    sib = _siblings()
    if any(sib.path(r) is None for r in PINS):
        pytest.skip("sibling checkouts not present")
    manifest = vc.json.loads(vc.MANIFEST.read_text()) if vc.MANIFEST.exists() else {}
    results = vc.check(sib, manifest)
    drift = [r for r in results if r.status == "DRIFT"]
    assert not drift, "vendor drift:\n" + "\n".join(f"  {r.rel}: {r.detail}" for r in drift)
    assert not [r for r in results if r.status == "skip"]
    adapted = {r.rel for r in results if r.status == "adapted"}
    assert adapted == {"arraytx/coupling.py"}                      # the one dropped import line
    assert all(r.status == "verbatim" for r in results if r.rel not in adapted)


def test_every_file_has_a_full_sha_header_pinned_to_its_sibling():
    bad = []
    for f in sorted((REPO / "src/fmcw_radar/vendor").rglob("*.py")):
        if f.name == "__init__.py":
            continue
        first = f.read_text().splitlines()[0]
        m = vc.HEADER.match(first)
        want = PINS["arraytx" and ("array_tx" if "arraytx" in f.parts else "polar_tx")]
        if not m or m["sha"] != want or m["repo"] not in PINS:
            bad.append(str(f.relative_to(REPO)))
    assert not bad, "vendored files not pinned to their sibling's full SHA: " + ", ".join(bad)


def test_nested_pllsim_headers_are_kept_under_ours():
    f = REPO / "src/fmcw_radar/vendor/polartx/vendor/pllsim/arch/adpll.py"
    lines = f.read_text().splitlines()[:3]
    assert lines[0].startswith("# Vendored from polar_tx@") and lines[2].startswith("# Vendored from pll_simulator@")


def test_manifest_files_exist():
    declared = vc.json.loads(vc.MANIFEST.read_text()).get("files", {})
    missing = [rel for rel in declared if not (REPO / "src/fmcw_radar/vendor" / rel).exists()]
    assert not missing


def test_detects_injected_drift():
    sib = _siblings()
    if sib.path("polar_tx") is None:
        pytest.skip("polar_tx checkout not present")
    target = REPO / "src/fmcw_radar/vendor/polartx/phasemod/adpll_tp.py"
    original = target.read_text()
    try:
        target.write_text(original + "\nINJECTED_DRIFT = 1\n")
        results = vc.check(sib, vc.json.loads(vc.MANIFEST.read_text()))
        assert any(r.status == "DRIFT" and "adpll_tp.py" in r.rel for r in results)
    finally:
        target.write_text(original)


def test_outside_code_imports_vendor_only_through_the_seam():
    import re

    hits = []
    for p in (REPO / "src/fmcw_radar").rglob("*.py"):
        if "vendor" in p.parts:
            continue
        for m in re.finditer(r"^\s*(?:from|import)\s+(polartx|pllsim|arraytx)\b", p.read_text(), re.M):
            hits.append((p.relative_to(REPO), m.group(0)))
    assert not hits, hits

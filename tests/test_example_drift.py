"""tools/example_drift.py: expected outputs cover every example and are stored
masked; a moved number is paired and found in the docs that quote it.
Adapted from d2d_link tests/test_example_drift.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def drift():
    spec = importlib.util.spec_from_file_location("example_drift", REPO / "tools" / "example_drift.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def test_expected_outputs_cover_every_example(drift):
    examples = {p.stem for p in (REPO / "examples").glob("[0-9][0-9]_*.py")}
    assert {p.stem for p in drift.EXPECTED.glob("*.txt")} == examples


def test_expected_outputs_are_stored_normalised(drift):
    for p in sorted(drift.EXPECTED.glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        assert drift.normalise(text) == text, p.name


def test_timings_and_paths_are_masked(drift):
    raw = "a  [3.2s]\n18 runs in 33s\n  wrote /home/runner/work/d/d/examples/output/00_x.png\n"
    assert drift.normalise(raw) == "a  [~s]\n18 runs in ~s\n  wrote examples/output/00_x.png\n"


def test_changes_pair_numbers(drift):
    old = "head\n  snr 51.30 dB 5.012 m\ntail\n"
    new = "head\n  snr 51.84 dB 5.012 m\ntail\n"
    (ch,) = drift.changes("00_x", old, new)
    assert ch.pairs == [("51.30", "51.84")]


def test_stale_quotes_are_found_by_scope(drift, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "A.md").write_text("# One\n\n示例 00 的 SNR 51.3 dB。\n\n# Two\n\n别处 51.3 dB。\n",
                                           encoding="utf-8")
    index = drift.DocIndex(drift.all_doc_numbers(tmp_path))
    ch = drift.Change("00_x", "", "", [("51.30", "51.84")])
    hits = sorted((d.lineno, where) for d, _, _, where in drift.stale(ch, index))
    assert hits == [(3, "block"), (7, "elsewhere")]


def test_every_registered_derived_quote_holds(drift):
    entries = drift.load_derived()
    assert entries
    bad, broken = drift.check_derived(entries, drift._outputs(drift.EXPECTED), drift.REPO)
    assert not broken, broken
    assert not bad, [(e.name, doc, ln, tok, value) for e, doc, ln, tok, value in bad]


def test_accept_refuses_while_a_citing_table_quotes_a_moved_number(drift, tmp_path):
    exp = tmp_path / "expected"
    new = tmp_path / "new"
    exp.mkdir()
    new.mkdir()
    doc = tmp_path / "README.md"
    doc.write_text("| `00_single_target_rd_map.py` | one target | cell SNR 51.30 dB |\n", encoding="utf-8")
    (exp / "00_single_target_rd_map.txt").write_text("  SNR, one range-Doppler cell  51.30 dB\n", encoding="utf-8")
    (new / "00_single_target_rd_map.txt").write_text("  SNR, one range-Doppler cell  51.60 dB\n", encoding="utf-8")
    hits = drift.blocking_quotes(exp, new, tmp_path)
    assert [(h[0], h[2]) for h in hits] == [("README.md", "51.30")]
    doc.write_text("| `00_single_target_rd_map.py` | one target | cell SNR 51.60 dB |\n", encoding="utf-8")
    assert drift.blocking_quotes(exp, new, tmp_path) == []

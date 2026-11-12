# Vendored from mmw60_trx@ef0f00c50c508271abdf1423fde7062ba0a0b92d: src/mmw60/spec.py
# Adapted-copy policy: see src/fmcw_radar/vendor/__init__.py
"""Specification / literature numbers with provenance (iron rule 5; d2d_link's ``spec`` method).

Every number the library takes from a standard, a paper or a regulation
lives in ``data/spec/survey.yaml`` with a ``source`` tag; code reads it
through :func:`survey` and never types the value itself.  ``source`` is
one of

* ``spec``     — from the original text; needs ``quote`` and ``section``;
* ``survey``   — from a paper / talk / search hit, unverified (the note
  must say 未核实);
* ``assumed``  — the paper does not say; this library's own choice;
* ``derived``  — computed from the above (the cite is the formula).

``grep -c "source: survey" src/mmw60/data/spec/survey.yaml`` lists the
unverified entries exactly (``tests/test_spec_sources.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

SOURCES = ("spec", "survey", "assumed", "derived")
DATA_DIR = Path(__file__).resolve().parent / "data" / "spec"
SURVEY_FILE = DATA_DIR / "survey.yaml"
FIG4_FILE = DATA_DIR / "liu2025_fig4.yaml"
LDPC_FILE = DATA_DIR / "ldpc_80211.yaml"
THRESHOLDS_FILE = DATA_DIR / "per_thresholds.yaml"


@dataclass(frozen=True)
class SpecNumber:
    key: str
    value: object
    unit: str
    source: str
    cite: str
    note: str = ""
    quote: str | None = None
    section: str | None = None

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError(f"{self.key}: source must be one of {SOURCES}, got {self.source!r}")
        if self.source == "spec" and not (self.quote and self.section):
            raise ValueError(f"{self.key}: a 'spec' entry must carry the quoted text and section")
        if self.source == "survey" and "未核实" not in self.note:
            raise ValueError(f"{self.key}: a 'survey' entry's note must say it is unverified (未核实)")
        if not self.cite:
            raise ValueError(f"{self.key}: cite is required")

    @property
    def verified(self) -> bool:
        return self.source == "spec"


def load_table(path: Path = SURVEY_FILE) -> dict[str, SpecNumber]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, SpecNumber] = {}
    for key, e in raw["entries"].items():
        out[key] = SpecNumber(key=key, value=e["value"], unit=str(e.get("unit", "")),
                              source=e["source"], cite=e.get("cite", ""),
                              note=e.get("note", ""), quote=e.get("quote"),
                              section=e.get("section"))
    return out


_TABLE: dict[str, SpecNumber] | None = None


def all_entries() -> dict[str, SpecNumber]:
    global _TABLE
    if _TABLE is None:
        _TABLE = load_table()
    return _TABLE


def survey(key: str) -> SpecNumber:
    """The entry for ``key`` (any source); KeyError names what exists."""
    table = all_entries()
    if key not in table:
        raise KeyError(f"no spec entry {key!r}; known: {sorted(table)}")
    return table[key]


def value(key: str):
    return survey(key).value


def unverified() -> dict[str, SpecNumber]:
    return {k: e for k, e in all_entries().items() if e.source == "survey"}


def by_source(source: str) -> dict[str, SpecNumber]:
    return {k: e for k, e in all_entries().items() if e.source == source}


def fig4_readings() -> dict:
    """Liu 2025 Fig. 4 read-offs (``liu2025_fig4.yaml``), as the file holds them."""
    return yaml.safe_load(FIG4_FILE.read_text(encoding="utf-8"))


_LDPC: dict | None = None


def ldpc_document() -> dict:
    """The 802.11 LDPC base-matrix file (``ldpc_80211.yaml``) with its source tag."""
    global _LDPC
    if _LDPC is None:
        _LDPC = yaml.safe_load(LDPC_FILE.read_text(encoding="utf-8"))
    return _LDPC


def ldpc_base_matrices() -> dict:
    """``{n: {rate: base matrix (list of rows)}}`` for n = 648 / 1296 / 1944."""
    return ldpc_document()["matrices"]


_THRESHOLDS: dict | None = None


def per_threshold_document() -> dict:
    """The measured ideal-chain PER thresholds (``per_thresholds.yaml``,
    source derived: ``tools/measure_thresholds.py``) with their tag."""
    global _THRESHOLDS
    if _THRESHOLDS is None:
        _THRESHOLDS = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    return _THRESHOLDS


def per_threshold_db(standard: str, bandwidth_hz: float, mcs: int) -> float | None:
    """SNR per active subcarrier at PER 1e-2 of a 4096-byte packet on the
    ideal chain; None when the base has no coded data field or the MCS
    never reaches the target."""
    table = per_threshold_document()["thresholds_db"]
    return table.get(standard, {}).get(float(bandwidth_hz), {}).get(int(mcs))

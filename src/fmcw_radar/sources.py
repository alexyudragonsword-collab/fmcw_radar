"""Every number that is not the user's own design decision, with its source (invariant #5).

The front-end placeholders (``source: assumed``, to be replaced when
mmw60_trx's front end exists), the atmospheric and RCS figures and the window
table (``source: survey``, read in summaries and unverified) live in
``src/fmcw_radar/data/sources.yaml``, one entry each.  Code takes them through
:func:`number` by key and carries the source along; the budget report prints
the tag next to every such value.  ``grep -c "source:"`` on the file counts
exactly the entries (the header is written so it cannot match).

An entry may name the sibling table its number comes from (``upstream:``):
``mmw60_trx:<entry>#<field>`` is that field of mmw60_trx's entry in the
vendored copy of its ``data/spec/survey.yaml`` (``#a-b`` is a difference of
two fields, ``#field@key=value`` the element of a tabulated curve).  The
number is written here as well, so the table reads on its own, and loading
refuses a pair that disagrees: a re-pin that moves the sibling's figure
fails until this file follows.

d2d_link's ``spec`` module is the model (its ``survey`` / ``spec`` / ``model``
tags become ``survey`` / ``spec`` / ``assumed`` here: a radar has no
specification to quote yet, and what the siblings call a model estimate is
here a front-end placeholder waiting for a sibling library).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCES_FILE = DATA_DIR / "sources.yaml"
SOURCES = ("assumed", "survey", "spec")


@dataclass(frozen=True)
class SourcedNumber:
    key: str
    value: Any
    unit: str
    source: str          # "assumed" | "survey" | "spec"
    cite: str
    note: str = ""
    quote: str = ""      # required when source == "spec"
    section: str = ""
    upstream: str = ""   # "mmw60_trx:<entry>#<field>": the sibling's sourced entry this number is read from

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError(f"entry {self.key!r}: source must be one of {SOURCES}, got {self.source!r}")
        if not self.cite:
            raise ValueError(f"entry {self.key!r}: cite is required")
        if self.source == "spec" and not self.quote:
            raise ValueError(f"entry {self.key!r}: source 'spec' needs the quoted text")
        if self.source == "survey" and "未核实" not in self.note:
            raise ValueError(f"entry {self.key!r}: a survey entry's note must say it is unverified (未核实)")

    @property
    def placeholder(self) -> bool:
        return self.source == "assumed"

    def tag(self) -> str:
        """``value unit (source: assumed)`` -- how a result line prints it."""
        return f"{self.value} {self.unit} (source: {self.source})".replace("  ", " ")


def upstream_value(ref: str) -> float:
    """The number ``ref`` names in a sibling's sourced table (the module
    docstring has the three forms)."""
    repo, _, rest = ref.partition(":")
    entry, _, field = rest.partition("#")
    if repo != "mmw60_trx" or not entry or not field:
        raise ValueError(f"upstream {ref!r}: expected 'mmw60_trx:<entry>#<field>'")
    from .vendor.mmw60 import spec

    v = spec.value(entry)
    if "@" in field:                                    # a tabulated curve: the element where key == value
        name, _, cond = field.partition("@")
        key, _, at = cond.partition("=")
        axis = [float(x) for x in v[key]]
        if float(at) not in axis:
            raise ValueError(f"upstream {ref!r}: {key} has no point {at} (have {axis})")
        return float(v[name][axis.index(float(at))])
    if "-" in field:                                    # a difference of two fields of one entry
        a, _, b = field.partition("-")
        return float(v[a]) - float(v[b])
    return float(v[field])


def load_sources(path: Path | str = SOURCES_FILE) -> dict[str, SourcedNumber]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("entries") or {}
    out = {}
    for key, e in entries.items():
        if not isinstance(e, dict):
            raise ValueError(f"entry {key!r} is not a mapping")
        unknown = set(e) - {"value", "unit", "source", "cite", "note", "quote", "section", "upstream"}
        if unknown:
            raise ValueError(f"entry {key!r}: unknown fields {sorted(unknown)}")
        out[key] = SourcedNumber(key=key, value=e.get("value"), unit=str(e.get("unit", "")),
                                 source=str(e.get("source", "")), cite=str(e.get("cite", "")),
                                 note=str(e.get("note", "")), quote=str(e.get("quote", "")),
                                 section=str(e.get("section", "")), upstream=str(e.get("upstream", "")))
        if out[key].upstream:
            up = upstream_value(out[key].upstream)
            if abs(float(out[key].value) - up) > 1e-9:
                raise ValueError(f"entry {key!r}: value {out[key].value} is not its upstream's "
                                 f"({out[key].upstream} = {up}); the sibling's table moved, or this one did")
    return out


@lru_cache(maxsize=1)
def _table() -> dict[str, SourcedNumber]:
    return load_sources()


def number(key: str) -> SourcedNumber:
    """The tagged number ``key`` (``<group>.<name>``)."""
    table = _table()
    if key not in table:
        raise KeyError(f"no sourced number {key!r} (have {sorted(table)})")
    return table[key]


def frontend_placeholder(band: str, name: str) -> SourcedNumber:
    """The front-end placeholder ``<band>.<name>`` (source: assumed)."""
    return number(f"{band}.{name}")


def all_entries() -> dict[str, SourcedNumber]:
    return dict(_table())


def by_source(source: str) -> dict[str, SourcedNumber]:
    return {k: v for k, v in _table().items() if v.source == source}


__all__ = ["SourcedNumber", "SOURCES", "SOURCES_FILE", "load_sources", "number", "frontend_placeholder", "upstream_value",
           "all_entries", "by_source"]

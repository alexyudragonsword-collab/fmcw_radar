"""Every number that is not the user's own design decision, with its source (invariant #5).

The placeholders (``source: assumed``), the figures read in summaries only
(``source: survey``, unverified), those read in the original (``source:
spec``, quoted) and those computed from such originals by a stated formula
(``source: derived``: the oxygen attenuation, ITU-R P.676's line-by-line
sum) live in ``src/fmcw_radar/data/sources.yaml``, one entry each.  Code takes them through
:func:`number` by key and carries the source along; the budget report prints
the tag next to every such value.  ``grep -c "source:"`` on the file counts
exactly the entries (the header is written so it cannot match).

An entry may name the shared table its number comes from (``upstream:``):
``spec_sources:<reference>`` is looked up in the vendored copy of
spec_sources (``vendor/spec_sources/``) with its reader's ``ref()`` --
``<key>``, ``<key>#<field>`` or ``<key>#<field>@<axis>=<value>``, a lookup
and nothing else: a difference or any other formula is a ``derived`` entry
there, with the formula in its note.  The number is written here as well, so
the table reads on its own, and loading refuses a pair that disagrees: a
re-pin that moves the shared figure fails until this file follows.

d2d_link's ``spec`` module is the model (its ``survey`` / ``spec`` / ``model``
tags become ``survey`` / ``spec`` / ``assumed`` here); ``derived`` is
spec_sources' fourth tag, taken over in 0.2.11 when the first computed figure
arrived: a derived entry must name its upstream and carry its formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCES_FILE = DATA_DIR / "sources.yaml"
SOURCES = ("assumed", "survey", "spec", "derived")


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
    upstream: str = ""   # "spec_sources:<reference>": the shared table's entry this number is read from

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError(f"entry {self.key!r}: source must be one of {SOURCES}, got {self.source!r}")
        if not self.cite:
            raise ValueError(f"entry {self.key!r}: cite is required")
        if self.source == "spec" and not self.quote:
            raise ValueError(f"entry {self.key!r}: source 'spec' needs the quoted text")
        if self.source == "derived" and not (self.upstream and self.note):
            raise ValueError(f"entry {self.key!r}: a derived number names the entry it is read from (upstream) and its formula (note)")
        if self.source == "survey" and "未核实" not in self.note:
            raise ValueError(f"entry {self.key!r}: a survey entry's note must say it is unverified (未核实)")

    @property
    def placeholder(self) -> bool:
        return self.source == "assumed"

    def tag(self) -> str:
        """``value unit (source: assumed)`` -- how a result line prints it."""
        return f"{self.value} {self.unit} (source: {self.source})".replace("  ", " ")


def upstream_value(ref: str) -> float:
    """The number ``ref`` names in spec_sources (``spec_sources:<reference>``; the
    reader's ref(): ``<key>[#<field>[@<axis>=<value>]]``, lookup only)."""
    repo, _, rest = ref.partition(":")
    if repo != "spec_sources" or not rest:
        raise ValueError(f"upstream {ref!r}: expected 'spec_sources:<reference>'")
    from .vendor.spec_sources import ref as lookup

    try:
        return float(lookup(rest))
    except KeyError as e:                       # keep this module's contract: a bad reference is a ValueError
        raise ValueError(f"upstream {ref!r}: {e}") from e


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

# Vendored from spec_sources@dfaa36b67a144eb53acf692727efd431c4ac34e4: src/spec_sources/reader.py
# Adapted-copy policy: see src/fmcw_radar/vendor/__init__.py
"""Numbers about the outside world, with their provenance: the reader.

Every number a sibling library takes from a standard, a paper, a datasheet or
a regulation lives in one of the domain tables ``data/<domain>.yaml``, one
entry per number, with a ``source`` tag.  Code reads it by key through
:func:`survey` / :func:`value` / :func:`ref` and never types the value
itself.  The tag is one of

* ``spec``     -- from the original text; needs ``quote`` and ``section``;
* ``survey``   -- from a summary, a search hit or a second-hand quote,
  unverified (the note must say 未核实);
* ``assumed``  -- the original does not say; a library's own choice.  These
  stay in the library that made them (it reads its own table with
  :func:`load_table`); the shared tables hold none;
* ``derived``  -- computed only from the above (the note or cite is the formula).

This module is meant to be vendored: the package directory copied as it is
under a consumer's ``vendor/``, pinned at a full SHA.  It therefore imports
only the standard library and PyYAML, uses no absolute import of its own
package and finds its data next to itself.  A consumer may copy only the
domain tables it reads; the reader loads whatever ``data/*.yaml`` it finds.

A reference (:func:`ref`) is a lookup and nothing else::

    "<key>"                         the whole value
    "<key>#<field>"                 one field of a mapping value
    "<key>#<field>@<axis>=<at>"     the element of a tabulated curve whose
                                    ``<axis>`` element equals ``<at>``

A difference, a ratio or a unit conversion is not a reference: it is a
``derived`` entry of its own, with the formula in its note.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import yaml

SOURCES = ("spec", "survey", "assumed", "derived")
#: the fields an entry may carry (mmw60_trx's SpecNumber fields)
FIELDS = ("value", "unit", "source", "cite", "note", "quote", "section")

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
LEGACY_DIR = PACKAGE_DIR / "legacy_keys"

#: a key: a lower-case domain prefix, a dot, then the name (which may hold
#: dots, digits and d2d_link's ``@lo-hi`` rate-range suffix)
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*\.[A-Za-z0-9_.@+-]+")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[-+]?[0-9]+(\.[0-9]*)?([eE][-+]?[0-9]+)?")
#: an entry's own tag line; any other line holding ``source: <tag>`` changes a grep count
_TAG_LINE = re.compile(r"\s+source: (" + "|".join(SOURCES) + r")\s*")
_TAG_WORD = re.compile(r"source: (" + "|".join(SOURCES) + r")")
#: the prose fields of an entry: no "source:" in them at all (iron rule 5)
_PROSE_FIELD = re.compile(r"\s+(cite|note|quote|section|unit):")


class DeprecatedKeyWarning(FutureWarning):
    """A renamed or retired key was read through its alias."""


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

    def tag(self) -> str:
        """``value unit (<tag>)`` -- how a result line prints it."""
        return f"{self.value} {self.unit} (source: {self.source})".replace("  ", " ")


@dataclass(frozen=True)
class Alias:
    old: str
    to: str
    since: str
    note: str = ""


# ----------------------------------------------------------------------------- YAML
class _StrictLoader(yaml.SafeLoader):
    """PyYAML's safe loader, except that a key repeated in one mapping is an
    error (``yaml.safe_load`` silently keeps the last one)."""


def _mapping_without_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        k = loader.construct_object(key_node, deep=deep)
        if k in seen:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {k!r}", key_node.start_mark)
        seen.add(k)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates)


def _read(path: Path) -> dict:
    doc = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_StrictLoader) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: a table is a mapping with 'entries' (and optionally 'aliases')")
    unknown = set(doc) - {"entries", "aliases"}
    if unknown:
        raise ValueError(f"{path}: unknown top-level keys {sorted(unknown)}")
    return doc


# ----------------------------------------------------------------------------- tables
def data_files(data_dir: Path | str | None = None) -> list[Path]:
    """The domain tables present, in name order."""
    return sorted(Path(DATA_DIR if data_dir is None else data_dir).glob("*.yaml"))


def _entries_of(path: Path) -> dict[str, SpecNumber]:
    raw = _read(path).get("entries") or {}
    out: dict[str, SpecNumber] = {}
    for key, e in raw.items():
        if not isinstance(e, dict):
            raise ValueError(f"{path}: entry {key!r} is not a mapping")
        unknown = set(e) - set(FIELDS)
        if unknown:
            raise ValueError(f"{path}: entry {key!r} has unknown fields {sorted(unknown)}")
        if "value" not in e or "source" not in e:
            raise ValueError(f"{path}: entry {key!r} needs a value and a source")
        out[key] = SpecNumber(key=key, value=e["value"], unit=str(e.get("unit", "")),
                              source=e["source"], cite=e.get("cite", ""),
                              note=e.get("note", ""), quote=e.get("quote"),
                              section=e.get("section"))
    return out


def merge_tables(*tables: dict[str, SpecNumber]) -> dict[str, SpecNumber]:
    """One table from several; a key in two of them is an error (keys are
    global: a consumer's local table may not shadow a shared entry)."""
    out: dict[str, SpecNumber] = {}
    for t in tables:
        for k, e in t.items():
            if k in out:
                raise ValueError(f"key {k!r} is in two tables")
            out[k] = e
    return out


def load_table(path: Path | str | None = None) -> dict[str, SpecNumber]:
    """The entries of one table file, of every ``*.yaml`` in a directory, or
    (``path`` None) of every shared domain table.  Each entry is checked as
    it is built (:class:`SpecNumber`); a key repeated anywhere is an error."""
    if path is None:
        path = DATA_DIR
    p = Path(path)
    if p.is_dir():
        return merge_tables(*(_entries_of(f) for f in data_files(p)))
    return _entries_of(p)


_TABLE: dict[str, SpecNumber] | None = None
_ALIASES: dict[str, Alias] | None = None


def all_entries() -> dict[str, SpecNumber]:
    """Every shared entry, from every domain table present (cached)."""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_table()
    return _TABLE


def aliases() -> dict[str, Alias]:
    """Old key -> :class:`Alias` for every renamed key still in its
    deprecation period (iron rule 3).  An alias may not shadow a live key and
    must point at one (no chains)."""
    global _ALIASES
    if _ALIASES is None:
        table = all_entries()
        out: dict[str, Alias] = {}
        for f in data_files():
            for old, a in (_read(f).get("aliases") or {}).items():
                if not isinstance(a, dict) or not a.get("to") or not a.get("since"):
                    raise ValueError(f"{f.name}: alias {old!r} needs 'to' and 'since'")
                if old in table or old in out:
                    raise ValueError(f"{f.name}: alias {old!r} is also a live key or another alias")
                if a["to"] not in table:
                    raise ValueError(f"{f.name}: alias {old!r} points at {a['to']!r}, which is not a live key")
                out[old] = Alias(old=old, to=a["to"], since=str(a["since"]), note=str(a.get("note", "")))
        _ALIASES = out
    return _ALIASES


def _resolve(key: str, stacklevel: int) -> SpecNumber:
    table = all_entries()
    if key in table:
        return table[key]
    a = aliases().get(key)
    if a is not None:
        warnings.warn(f"spec key {key!r} is deprecated since {a.since}: read {a.to!r}",
                      DeprecatedKeyWarning, stacklevel=stacklevel)
        return table[a.to]
    raise KeyError(f"no spec entry {key!r}; known: {sorted(table)}")


def survey(key: str) -> SpecNumber:
    """The entry for ``key`` (any source); KeyError names what exists.  An
    old key in its deprecation period resolves with a DeprecatedKeyWarning."""
    return _resolve(key, stacklevel=3)


def value(key: str):
    return _resolve(key, stacklevel=3).value


def unverified() -> dict[str, SpecNumber]:
    return {k: e for k, e in all_entries().items() if e.source == "survey"}


def by_source(source: str) -> dict[str, SpecNumber]:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    return {k: e for k, e in all_entries().items() if e.source == source}


# ----------------------------------------------------------------------------- references
def _scalar(text: str):
    """``40`` -> 40, ``x`` -> 'x' (YAML's reading of a plain scalar); a number
    YAML 1.1 leaves as a string (``4e1``, no dot) is still a number."""
    v = yaml.safe_load(text)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return float(a) == float(b)
    return a == b


def ref(reference: str, table: dict[str, SpecNumber] | None = None):
    """Look a reference up (module docstring: three forms).  Lookup only: an
    expression is refused, its result belongs in a ``derived`` entry.
    ``table`` defaults to the shared tables (aliases resolve there only)."""
    key, hash_, rest = reference.partition("#")
    if table is None:
        entry = _resolve(key, stacklevel=3)
    elif key in table:
        entry = table[key]
    else:
        raise KeyError(f"reference {reference!r}: no entry {key!r}")
    if not hash_:
        return entry.value
    field, at_, cond = rest.partition("@")
    if not _FIELD.fullmatch(field):
        raise ValueError(f"reference {reference!r}: {field!r} is not a field name. A reference only looks a number "
                         "up; a difference or any other formula is a 'derived' entry with the formula in its note")
    v = entry.value
    if not isinstance(v, dict):
        raise ValueError(f"reference {reference!r}: {key} is not a mapping, it has no fields")
    name = field if field in v else _scalar(field)
    if name not in v:
        raise KeyError(f"reference {reference!r}: {key} has no field {field!r} (has {list(v)})")
    if not at_:
        return v[name]
    axis_name, eq, at = cond.partition("=")
    if not (axis_name and eq and at):
        raise ValueError(f"reference {reference!r}: a selector is '@<axis>=<value>'")
    if axis_name not in v:
        raise KeyError(f"reference {reference!r}: {key} has no axis {axis_name!r} (has {list(v)})")
    axis, column = v[axis_name], v[name]
    if not (isinstance(axis, list) and isinstance(column, list) and len(axis) == len(column)):
        raise ValueError(f"reference {reference!r}: {axis_name} and {field} must be lists of one length")
    target = _scalar(at)
    hits = [i for i, x in enumerate(axis) if _same(x, target)]
    if len(hits) != 1:
        raise KeyError(f"reference {reference!r}: {axis_name} = {at} matches {len(hits)} points (have {axis})")
    return column[hits[0]]


# ----------------------------------------------------------------------------- consumers' old names
def legacy_keys(repo: str) -> dict[str, str]:
    """A consumer's old key -> this library's key (``legacy_keys/<repo>.yaml``),
    for the consumer's shim: it keeps its old names in its own namespace while
    reading the shared entries.  Every target must be a live key."""
    path = LEGACY_DIR / f"{repo}.yaml"
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader) or {}
    keys = doc.get("keys") or {}
    table = all_entries()
    missing = sorted(new for new in keys.values() if new not in table)
    if missing:
        raise ValueError(f"{path.name}: targets not in the shared tables: {missing}")
    if len(set(keys.values())) != len(keys):
        raise ValueError(f"{path.name}: two old keys map to one new key")
    return dict(keys)


# ----------------------------------------------------------------------------- the grep guard
def _misplaced_tag(line: str) -> bool:
    if "source:" not in line or _TAG_LINE.fullmatch(line):
        return False
    _, hash_, after = line.partition("#")
    in_comment = bool(hash_) and "source:" in after
    return bool(_TAG_WORD.search(line)) or in_comment or bool(_PROSE_FIELD.match(line))


def audit_tags(path: Path | str) -> list[str]:
    """What breaks ``grep -c "source: <tag>"`` on one table file ([] when
    nothing does), iron rule 5: for each of the four tags the grep count must
    equal the number of entries carrying it; no line but an entry's own tag
    line may hold ``source: <tag>``; and no comment or prose field (cite,
    note, quote, section, unit) may hold ``source:`` at all.  A ``source:``
    key inside a value mapping is data, not prose, and breaks no count."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines()
    problems = [f"{p.name}:{i}: tag word outside an entry's tag line: {line.strip()!r}"
                for i, line in enumerate(lines, 1) if _misplaced_tag(line)]
    entries = _entries_of(p)
    for tag in SOURCES:
        grep = sum(f"source: {tag}" in line for line in lines)
        parsed = sum(e.source == tag for e in entries.values())
        if grep != parsed:
            problems.append(f"{p.name}: grep -c 'source: {tag}' = {grep}, entries = {parsed}")
    return problems


__all__ = ["SpecNumber", "SOURCES", "load_table", "all_entries", "survey", "value", "unverified", "by_source",
           "ref", "aliases", "Alias", "DeprecatedKeyWarning", "legacy_keys", "merge_tables", "audit_tags",
           "data_files", "FIELDS", "KEY_PATTERN", "DATA_DIR", "LEGACY_DIR"]

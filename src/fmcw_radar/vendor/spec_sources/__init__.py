"""spec_sources' reader and the one domain table fmcw_radar reads, nothing else.

spec_sources is the siblings' shared table of numbers about the outside
world (specification clauses, datasheet and paper figures, and what is
derived from them alone), each with its provenance.  Vendored here at
``d7b4d1eb510617d69784622c593c8ed31ab32b8b`` (its main, milestone 1):
``reader.py`` and ``data/frontend60.yaml`` (the 60 GHz radar chip's
receiver and transmitter figures, its Figure 7-2 curve, the TX-RX isolation
and the derived no-EBG figure).  The reader loads whatever ``data/*.yaml``
sits next to it, so the other domain tables are simply not copied.

``fmcw_radar.sources`` reads these by reference (``upstream:`` in
``data/sources.yaml``, ``spec_sources:<reference>``) and refuses to load if a
number there disagrees.  This ``__init__`` is fmcw_radar's own (the vendor
check does not compare package ``__init__`` files); ``reader.py`` and the
table are verbatim under their attribution headers.
"""
from .reader import all_entries, audit_tags, data_files, ref, survey, value

__all__ = ["ref", "survey", "value", "all_entries", "audit_tags", "data_files"]

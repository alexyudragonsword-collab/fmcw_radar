"""spec_sources' reader and the domain tables fmcw_radar reads, nothing else.

spec_sources is the siblings' shared table of numbers about the outside
world (specification clauses, datasheet and paper figures, and what is
derived from them alone), each with its provenance.  Vendored here at
``f87cc9b54af9d6510e406d8356c04267fa1dd388`` (its main, fmcw_radar#19):
``reader.py`` and the five domain tables fmcw_radar reads --
``data/frontend60.yaml`` (the 60 GHz radar chip's figures, its Figure 7-2,
the TX-RX isolation and its derived no-EBG figure), ``data/atmosphere.yaml``
(ITU-R P.676-13's oxygen lines and method, and the derived sea-level
attenuation), ``data/radar_targets.yaml`` (the pedestrian RCS, ISO 19206-3's
passenger-car bands, the trihedral formulas), ``data/adpll60.yaml`` (a 60 GHz
FMCW ADPLL's TDC resolution, Wu et al. 2014) and ``data/windows.yaml``
(Harris 1978 Table I).  The
reader loads whatever ``data/*.yaml`` sits next to it, so the other domain
tables are simply not copied.

``fmcw_radar.sources`` reads these by reference (``upstream:`` in
``data/sources.yaml``, ``spec_sources:<reference>``) and refuses to load if a
number there disagrees.  This ``__init__`` is fmcw_radar's own (the vendor
check does not compare package ``__init__`` files); ``reader.py`` and the
table are verbatim under their attribution headers.
"""
from .reader import all_entries, audit_tags, data_files, ref, survey, value

__all__ = ["ref", "survey", "value", "all_entries", "audit_tags", "data_files"]

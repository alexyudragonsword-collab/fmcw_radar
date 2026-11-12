"""mmw60_trx's sourced-number table and its reader, and nothing else of it.

fmcw_radar reads the 60 GHz front-end figures mmw60_trx has collected with
their provenance (its ``data/spec/survey.yaml`` through its ``spec``
module): the radar chip's receiver and transmitter figures and the TX-RX
isolation.  ``Frontend60`` itself is not vendored -- it stands on wifitrx's
whole transmit / receive chain, which a radar that reads a handful of
numbers has no use for.  ``fmcw_radar.sources`` ties its own entries to
this table (``upstream:``) and refuses to load if the two disagree.

This ``__init__`` is fmcw_radar's own; ``spec.py`` and
``data/spec/survey.yaml`` are verbatim under their attribution headers.
"""

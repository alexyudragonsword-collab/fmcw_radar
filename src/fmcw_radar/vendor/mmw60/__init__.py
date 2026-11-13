"""One file of mmw60_trx: its x10 LO phase-noise profile, nothing else.

``data/clock_profiles/pllsim_wu19_x10_60p48g_floor150.yaml`` (a 6.048 GHz
fractional-N PLL behind a x10 multiplier, floor -150 dBc/Hz: mmw60_trx's
baseline file), read by ``configs/radar_60g_x10lo.yaml`` through
``lo.profile``.  It is a model output, not a sourced figure, so it stays
here pinned at mmw60_trx's commit; the sourced front-end figures this
library once read from mmw60_trx's table now come from spec_sources
(``vendor/spec_sources/``).  This ``__init__`` is fmcw_radar's own; the
profile file is verbatim under its attribution header.
"""

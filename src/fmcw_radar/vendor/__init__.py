"""Adapted copies of the sibling library fmcw_radar builds on (polar_tx).

This tree is a VERIFIABLE COPY, not a fork (polar_tx CONTRIBUTING 3): every
file carries an attribution header naming its upstream repository, commit and
path, and ``tools/vendor_check.py --strict`` re-derives the relationship on
every CI run.  Code outside this tree imports only through
``fmcw_radar.vendor.polartx...``.

Pins
----
* ``polartx/`` -- polar_tx @ ``70577381f678da34da20fcd083c5052afae1c437``
  (its ``main``), the chirp generator's parts only:

  - ``phasemod/base.py``, ``phasemod/adpll_tp.py`` -- the two-point ADPLL
    phase modulator (``ADPLLTwoPoint``: linearised ``response`` engine and the
    cycle-accurate ``event`` engine with the online ``dp_cal`` hook);
  - ``cal/twopoint.py`` -- the offline least-squares direct-path gain
    estimator;
  - ``vendor/pllsim/`` -- polar_tx's own vendored subset of pll_simulator
    (pll_simulator @ 931cfaf, ``arch/adpll.py`` and ``arch/frac.py`` held at
    d7be4712 for polar_tx's two-point extension).  The nested files keep
    polar_tx's ``# Vendored from pll_simulator@...`` headers UNDER ours, so the
    provenance chain reads top-down; the drift check strips only the outer
    header and compares the rest with polar_tx's file, byte for byte.

  The package ``__init__`` files of ``phasemod/`` and ``cal/`` are
  fmcw_radar's own (polar_tx's import the DTC modulator and the skew
  calibrator, which are not vendored); ``vendor/pllsim/`` keeps polar_tx's.

Local changes
-------------
None in any ``.py`` body.  A linear FM chirp is the two-point modulator fed a
frequency ramp, so the chirp generator (``fmcw_radar.chirp``) wraps these
classes rather than editing them.  A change to a vendored body goes upstream
first (polar_tx's ROADMAP), then gets re-vendored at a new pin; if it cannot,
it is declared in ``tools/vendor_manifest.json`` with a reason, or it does not
happen.
"""

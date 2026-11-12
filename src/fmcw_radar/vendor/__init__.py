"""Adapted copies of the sibling library fmcw_radar builds on (polar_tx).

This tree is a VERIFIABLE COPY, not a fork (polar_tx CONTRIBUTING 3): every
file carries an attribution header naming its upstream repository, commit and
path, and ``tools/vendor_check.py --strict`` re-derives the relationship on
every CI run.  Code outside this tree imports only through
``fmcw_radar.vendor.polartx...``.

Pins
----
* ``polartx/`` -- polar_tx @ ``b007e60477bac68806138db733cbafd0c0761282``
  (its ``main``), the chirp generator's parts only:

  - ``phasemod/base.py``, ``phasemod/adpll_tp.py`` -- the two-point ADPLL
    phase modulator (``ADPLLTwoPoint``: linearised ``response`` engine and the
    cycle-accurate ``event`` engine with the online ``dp_cal`` hook, a step
    kernel inside the ADPLL's per-cycle loop since this pin);
  - ``cal/twopoint.py`` -- the offline least-squares direct-path gain
    estimator;
  - ``vendor/pllsim/`` -- polar_tx's own vendored subset of pll_simulator
    (all of it at pll_simulator @ 5564c64 since polar_tx b007e60; ``arch/adpll.py``
    carries polar_tx's two-point extension, the direct point and the dp_cal
    hook).  The nested files keep
    polar_tx's ``# Vendored from pll_simulator@...`` headers UNDER ours, so the
    provenance chain reads top-down; the drift check strips only the outer
    header and compares the rest with polar_tx's file, byte for byte.

  The package ``__init__`` files of ``phasemod/`` and ``cal/`` are
  fmcw_radar's own (polar_tx's import the DTC modulator and the skew
  calibrator, which are not vendored); ``vendor/pllsim/`` keeps polar_tx's.

* ``arraytx/`` -- array_tx @ ``e897c159e5fc5b2e26af6336cf9f6164461ff7f5``
  (its ``main``), the virtual array's parts only (milestone 2):

  - ``geometry.py`` (``ArrayGeometry``: positions, delays, element pattern),
  - ``beam.py`` (array factor, beamwidth, the phase-shifter squint
    ``squint_analytic_deg``),
  - ``coupling.py`` (``CouplingMatrix`` from the three sources and the one
    ``apply_coupling``; adapted: the ``from .config import ArrayConfig`` line
    is dropped, fmcw_radar builds the matrix from its own config and never
    calls ``build_coupling``),
  - ``touchstone.py`` (the .sNp reader / writer).

Local changes
-------------
None in any ``.py`` body (the one import line above is the adapted copy's
whole difference, which ``tools/vendor_check.py`` classifies as such).  A linear FM chirp is the two-point modulator fed a
frequency ramp, so the chirp generator (``fmcw_radar.chirp``) wraps these
classes rather than editing them.  A change to a vendored body goes upstream
first (polar_tx's ROADMAP), then gets re-vendored at a new pin; if it cannot,
it is declared in ``tools/vendor_manifest.json`` with a reason, or it does not
happen.
"""

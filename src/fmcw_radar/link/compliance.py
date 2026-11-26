"""Regulatory check of the transmitter: 47 CFR 15.255(c)(2), the radar limits
of the 57-71 GHz band.

Every number is read from ``data/sources.yaml`` (``fcc15255.<tier>.<field>``,
``source: spec``, each tied to spec_sources' entry of the rule's current
text); this module holds the rule's *structure* and no limit of its own.

What the rule says (spec_sources#50, each sentence quoted there):

* A field disturbance sensor / radar in 57-71 GHz is held to -10 dBm peak
  conducted power **and** 10 dBm peak EIRP (``radar_default``), unless it
  limits its operation to all or part of one of the listed bands and meets
  that tier's conditions; then that tier's peak EIRP applies and there is no
  conducted limit.
* It may use any tier it qualifies for ((c)(2)(iv): one at a time, 33 ms in
  a mode before switching).  The check therefore lists every tier and names
  the *governing* one: the highest limit among those the configuration can
  use (between two equal limits, the one without an off-time condition).
* Off-time, where a tier asks for it: within any contiguous 33 ms, the sum
  of the transmitter's off-times that are each continuous for at least 2 ms
  is at least 25.5 ms (or 16.5 ms).  A flyback of a few microseconds
  between chirps is not an off-time; a frame is one burst.

What the rule does not say, and how this library reads it (each printed
with the result, so nobody takes the reading for the rule):

* "Indoor", "outdoor", "fixed", "vehicular" are not defined.  The config
  declares one (``regulatory.scenario``) or nothing; undeclared, the tiers
  that depend on it are reported as "scenario not declared" and not used.
* Which band decides whether an emission is "within" a tier's band.  The
  tiers are judged here on the commanded sweep, ``center +- sweep / 2``.
  FCC 23-35 para. 62 has the occupied bandwidth of 47 CFR 2.1049 measured
  as part of the compliance measurements -- a statement of the Report and
  Order, not of the rule's text -- and neither says that this measured band
  is what a tier's band is compared with (spec_sources' reading,
  fmcw_radar#46).  The measured band is reported beside the verdict
  (``link/occupied.py``; ``check_emission(occupied_band_hz=...)``): for a
  linear sweep it lies inside the commanded one, so the commanded sweep is
  the stricter of the two.  No margin for temperature or supply, which
  paragraph (f) wants the fundamental kept inside the band under.
* Whether the transmitter is on between ramps: taken as off (the ramps are
  the transmit intervals).  If it stays on through ``chirp.idle_s`` the
  flyback's transient is part of the emission and its occupied band can
  reach the commanded edge or pass it; the report gives that band too
  whenever there is idle time.
* Which part of an off-time counts when the 33 ms interval cuts it: the
  part inside the interval, of an off-time that is itself at least 2 ms
  long.  (Counting only pieces that are 2 ms long *inside* the interval
  would take up to 4 ms more and no 6.4 ms frame could meet the 25.5 ms
  tier at any frame rate.)
* How several transmit channels add: nothing.  This library's MIMO is TDM,
  one transmitter on at a time, so the EIRP is one transmitter's.
* The measurement bandwidth of "peak EIRP": nothing.  The configured
  ``tx_power_dbm - tx_backoff_db + tx_gain_dbi`` is taken as the peak EIRP,
  ``tx_power_dbm - tx_backoff_db`` as the peak conducted power.

Outside 57-71 GHz the section does not apply and the check says so (the
77 GHz band); it does not borrow the 60 GHz limits.

Two entries (0.2.33, fmcw_radar#42):

* ``check_emission(...)`` is the rule on explicit numbers: the occupied
  band, the transmit power and gain, when the transmitter is on within a
  frame, the frame period, the scenario -- and ``number``, the function the
  limits are read through.  It reads no config object and no source table
  of its own, and this module imports nothing of the library at load time,
  so another library can vendor the file as it is and hand in its own
  ``number``.
* ``check(cfg)`` takes those numbers out of a ``RadarConfig`` and calls it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:                       # the annotation of check(cfg) only: nothing of the library is imported at load time
    from ..config.schema import RadarConfig

RULE = "47 CFR 15.255(c)(2)"

#: tier -> (label, the scenarios it is open to (None: any), has an off-time condition, has a bandwidth condition,
#:          has a conducted limit).  The structure of the rule; the numbers are in sources.yaml.
TIERS = {
    "radar_default": ("default: any field disturbance sensor / radar in the band", None, False, False, True),
    "radar_57_59p4_indoor": ("57.0-59.4 GHz, indoor", ("indoor",), False, False, False),
    "radar_57_59p4_outdoor": ("57.0-59.4 GHz, outdoor", ("outdoor", "outdoor_fixed", "vehicular"), False, False, False),
    "radar_57_61p56": ("57.0-61.56 GHz, no off-time", None, False, False, False),
    "radar_57_61p56_off_time": ("57.0-61.56 GHz, with off-time", None, True, False, False),
    "radar_57_64": ("57.0-64.0 GHz, with off-time", None, True, False, False),
    "radar_57_64_outdoor": ("57.0-64.0 GHz, outdoors fixed or vehicular, with off-time", ("outdoor_fixed", "vehicular"), True, False, False),
    "radar_61_61p5": ("61.0-61.5 GHz, 500 MHz or less", None, False, True, False),
    "radar_uav_60_64": ("60-64 GHz on an unmanned aircraft, with off-time", ("uav",), True, False, False),
}


#: the tag of an input whose origin the caller did not state (``check_emission(sources=...)``)
NOT_STATED = "not stated"


def frame_intervals(n: int, on_s: float, pri_s: float) -> list[tuple[float, float]]:
    """``n`` transmissions of ``on_s`` each, one every ``pri_s``: the
    intervals ``(start, end)`` [s] the transmitter is on within one frame
    (an FMCW frame's ramps, a train of bursts)."""
    return [(k * pri_s, k * pri_s + on_s) for k in range(n)]


def merge_bursts(on_intervals: Sequence[tuple[float, float]], min_run_s: float) -> list[tuple[float, float]]:
    """Transmit intervals ``(start, end)`` [s], in order, as the off-time
    rule sees them: every gap shorter than ``min_run_s`` is counted as
    transmitting."""
    out: list[tuple[float, float]] = []
    for a, b in on_intervals:
        if out and a - out[-1][1] < min_run_s:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def on_bursts(cfg: RadarConfig, min_run_s: float) -> list[tuple[float, float]]:
    """The frame's transmit intervals ``(start, end)`` [s] as the off-time
    rule sees them: the ramps, with every gap shorter than ``min_run_s``
    counted as transmitting."""
    c = cfg.chirp
    return merge_bursts(frame_intervals(c.n_chirps, c.duration_s, c.pri_s), min_run_s)


def min_off_sum(bursts: list[tuple[float, float]], period_s: float, window_s: float, min_run_s: float) -> float:
    """The least, over every placement of a ``window_s`` interval, of the
    off-time inside it, counting only off-times that are themselves at
    least ``min_run_s`` long.  ``bursts`` repeat every ``period_s``.  The
    counted off-time inside a sliding interval is piecewise linear in the
    interval's start, so its minimum is at a start (or end) that sits on
    an edge of a burst: those are the placements tried."""
    if not bursts:
        return window_s
    reps = int(window_s // period_s) + 3
    on: list[tuple[float, float]] = []
    for r in range(-1, reps):
        on += [(a + r * period_s, b + r * period_s) for a, b in bursts]
    on.sort()
    merged: list[tuple[float, float]] = []
    for a, b in on:
        # an off-time shorter than min_run_s (the wrap from one frame's end to the next one's start too) is transmitting
        if merged and a - merged[-1][1] < min_run_s:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    edges = [e for iv in merged for e in iv]
    starts = {e for e in edges if 0.0 <= e < period_s} | {e - window_s for e in edges if 0.0 <= e - window_s < period_s} | {0.0}
    best = window_s
    for s in starts:
        t_on = sum(max(0.0, min(b, s + window_s) - max(a, s)) for a, b in merged)
        best = min(best, window_s - t_on)
    return best


def min_frame_period(bursts: list[tuple[float, float]], window_s: float, sum_min_s: float, min_run_s: float) -> float | None:
    """The shortest frame period [s] at which the off-time condition holds
    (and holds for every longer one), or None when the frame's own burst
    already leaves too little of the window."""
    frame = bursts[-1][1] - bursts[0][0]
    ok = lambda t: min_off_sum(bursts, t, window_s, min_run_s) >= sum_min_s - 1e-12      # noqa: E731
    hi = frame + 2.0 * window_s
    if not ok(hi):
        return None
    lo = frame
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return hi


@dataclass
class TierResult:
    tier: str
    label: str
    band_ghz: tuple[float, float]
    peak_eirp_limit_dbm: float
    conducted_limit_dbm: float | None
    in_band: bool                       # the sweep lies inside this tier's band
    bandwidth_ok: bool | None           # None: the tier has no bandwidth condition
    scenario: str                       # "any" | "met" | "not met" | "not declared"
    off_time: str                       # "none required" | "met" | "not met" | "frame period not declared" | "cannot be met"
    off_time_required_s: float | None
    off_time_have_s: float | None       # the least counted off-time in any window, when the frame period is declared
    min_frame_period_s: float | None    # the shortest frame period that meets the off-time (None: none does, or none required)
    eirp_margin_db: float               # limit - EIRP: negative = over
    conducted_margin_db: float | None
    usable: bool                        # band, bandwidth and scenario allow it, and its off-time is met or can be
    power_ok: bool                      # the EIRP (and the conducted power, where the tier limits it) is within the limit
    compliant: bool | None              # as configured; None = the power is within the limit but the off-time cannot be
                                        # judged (the frame period is not declared)
    sources: dict = field(default_factory=dict)
    # with a measured occupied band handed in (47 CFR 2.1049; reported, the verdict above stays on the commanded sweep):
    in_band_measured: bool | None = None        # the measured band lies inside this tier's band
    bandwidth_ok_measured: bool | None = None   # the measured bandwidth meets the tier's bandwidth condition (None: it has none)

    @property
    def max_frame_rate_hz(self) -> float | None:
        return None if self.min_frame_period_s is None else 1.0 / self.min_frame_period_s


@dataclass
class ComplianceResult:
    rule: str
    applies: bool
    why: str                            # one sentence: why it applies, or why not
    sweep_ghz: tuple[float, float]
    eirp_dbm: float
    conducted_dbm: float
    n_tx: int
    frame_on_s: float
    frame_period_s: float | None
    scenario: str | None
    tiers: list[TierResult] = field(default_factory=list)
    tx_power_dbm: float = 0.0           # what the transmitter can put out, and
    tx_backoff_db: float = 0.0          # how far it is backed off: conducted_dbm = tx_power_dbm - tx_backoff_db
    governing: str | None = None        # the usable tier with the highest limit
    eirp_cap_dbm: float | None = None   # what the EIRP has to come down to under the governing tier (its conducted limit too)
    readings: tuple = ()                # what the rule leaves open and how it was read here
    sources: dict = field(default_factory=dict)
    occupied_ghz: tuple[float, float] | None = None    # the measured occupied band handed in (None: none was)

    @property
    def tier(self) -> TierResult | None:
        return next((t for t in self.tiers if t.tier == self.governing), None)

    @property
    def verdict(self) -> str:
        """Two statements, kept apart: the power against the limit, and the off-time."""
        if not self.applies:
            return "not applicable"
        g = self.tier
        if g is None:
            return "no tier of the rule fits this configuration"
        power = (f"EIRP within the limit (margin {g.eirp_margin_db:+.1f} dB)" if g.eirp_margin_db >= -1e-12
                 else f"EIRP over the limit by {-g.eirp_margin_db:.1f} dB")
        if g.conducted_margin_db is not None:
            power += ("; conducted power within its limit" if g.conducted_margin_db >= -1e-12
                      else f"; conducted power over its limit by {-g.conducted_margin_db:.1f} dB")
        if g.off_time == "none required":
            off = "no off-time required"
        elif g.off_time == "frame period not declared":
            off = (f"off-time: frame period not declared, cannot be judged (it needs a frame period of at least "
                   f"{g.min_frame_period_s * 1e3:.2f} ms, at most {g.max_frame_rate_hz:.1f} frames a second)")
        else:
            off = f"off-time {g.off_time} ({g.off_time_have_s * 1e3:.2f} ms of the {g.off_time_required_s * 1e3:g} ms required)"
        return f"{power}; {off}"

    def as_dict(self) -> dict:
        d = {"rule": self.rule, "applies": self.applies, "why": self.why, "verdict": self.verdict, "compliant": None if self.tier is None else self.tier.compliant,
             "sweep_ghz": list(self.sweep_ghz), "eirp_dbm": self.eirp_dbm, "conducted_dbm": self.conducted_dbm, "n_tx": self.n_tx,
             "tx_power_dbm": self.tx_power_dbm, "tx_backoff_db": self.tx_backoff_db,
             "frame_on_s": self.frame_on_s, "frame_period_s": self.frame_period_s, "scenario": self.scenario,
             "governing": self.governing, "eirp_cap_dbm": self.eirp_cap_dbm, "readings": list(self.readings),
             "sources": dict(self.sources), "occupied_ghz": None if self.occupied_ghz is None else list(self.occupied_ghz), "tiers": []}
        for t in self.tiers:
            d["tiers"].append({"tier": t.tier, "label": t.label, "band_ghz": list(t.band_ghz),
                               "peak_eirp_limit_dbm": t.peak_eirp_limit_dbm, "conducted_limit_dbm": t.conducted_limit_dbm,
                               "in_band": t.in_band, "bandwidth_ok": t.bandwidth_ok, "scenario": t.scenario, "off_time": t.off_time,
                               "off_time_required_s": t.off_time_required_s, "off_time_have_s": t.off_time_have_s,
                               "min_frame_period_s": t.min_frame_period_s, "max_frame_rate_hz": t.max_frame_rate_hz,
                               "eirp_margin_db": t.eirp_margin_db, "conducted_margin_db": t.conducted_margin_db,
                               "usable": t.usable, "power_ok": t.power_ok, "compliant": t.compliant, "sources": dict(t.sources),
                               "in_band_measured": t.in_band_measured, "bandwidth_ok_measured": t.bandwidth_ok_measured})
        g = self.tier
        if g is not None:
            d.update({"limit_dbm": g.peak_eirp_limit_dbm, "eirp_margin_db": g.eirp_margin_db,
                      "off_time_required_s": g.off_time_required_s, "min_frame_period_s": g.min_frame_period_s,
                      "max_frame_rate_hz": g.max_frame_rate_hz})
        return d


READINGS = (
    "'Indoor', 'outdoor', 'fixed' and 'vehicular' are not defined in the rule: the config's regulatory.scenario is taken at its word.",
    "The tiers are judged on the commanded sweep (center +- sweep / 2).  FCC 23-35 para. 62 has the occupied bandwidth of 47 CFR "
    "2.1049 measured as part of the compliance measurements -- in the Report and Order, not in the rule's text -- and neither says "
    "that the measured band is what a tier's band is compared with.  The measured band is reported beside the verdict; for a linear "
    "sweep it lies inside the commanded one, which makes the commanded sweep the stricter reading.  No margin is kept for the "
    "temperature and supply range of paragraph (f).",
    "The transmitter is taken to be on during the ramps only.  If it stays on through the idle time between ramps, the flyback's "
    "transient is part of the emission and the occupied band can reach the commanded edge or pass it (reported when there is idle time).",
    "An off-time counts if it is continuous for at least 2 ms; of one the 33 ms interval cuts, the part inside the interval counts.",
    "The rule does not say how several transmit channels add.  TDM: one transmitter is on at a time, the EIRP is one transmitter's.",
    "Peak EIRP is taken as tx_power_dbm - tx_backoff_db + tx_gain_dbi, peak conducted power as tx_power_dbm - tx_backoff_db; the "
    "rule gives no measurement bandwidth.",
)


def check_emission(f_lo_hz: float, f_hi_hz: float, tx_power_dbm: float, tx_gain_dbi: float,
                   on_intervals: Sequence[tuple[float, float]], *, number: Callable, tx_backoff_db: float = 0.0,
                   frame_period_s: float | None = None, scenario: str | None = None, n_tx: int = 1,
                   occupied_bw_hz: float | None = None, frame_on_s: float | None = None,
                   sources: dict | None = None, occupied_band_hz: tuple[float, float] | None = None) -> ComplianceResult:
    """An emission against 47 CFR 15.255(c)(2), on explicit numbers.

    ``f_lo_hz``, ``f_hi_hz``: the band the emission occupies (how it is
    measured is the caller's reading; ``READINGS`` states this library's).
    ``tx_power_dbm - tx_backoff_db`` is taken as the peak conducted power,
    that plus ``tx_gain_dbi`` as the peak EIRP.
    ``on_intervals``: when the transmitter is on within one frame,
    ``(start, end)`` in seconds, in order, as they are -- each tier merges
    the gaps shorter than its own minimum off-time (``frame_intervals``
    builds a regular train).  ``frame_period_s``: the frame repeats with
    it; ``None`` = not declared, and an off-time condition is then reported
    with the shortest period that would meet it instead of a verdict.
    ``scenario``: one of the words in ``TIERS``, or ``None`` = not declared.
    ``occupied_bw_hz``: for the tier with a bandwidth condition; the band's
    own width when not given.  ``frame_on_s``: reported only; first start to
    last end when not given.  ``sources``: the tags of ``tx_power_dbm``,
    ``tx_backoff_db`` and ``tx_gain_dbi``, reported with the result
    (``NOT_STATED`` for those left out).  ``occupied_band_hz``: the
    emission's *measured* occupied band ``(lower, upper)`` (47 CFR 2.1049),
    when the caller has one: each tier then also says whether that band lies
    inside its own and meets its bandwidth condition
    (``in_band_measured``, ``bandwidth_ok_measured``).  The verdict does not
    change with it: it stays on ``f_lo_hz .. f_hi_hz`` (see the module's
    note on which band decides).

    ``number``: the function every limit is read through --
    ``number("fcc15255.<tier>.<field>")`` and ``number("fcc15255.band_low_hz"
    / "band_high_hz")`` give an object with ``.value`` and ``.source``.  The
    keys are spec_sources' ``fcc15255.<tier>#<field>`` written with a dot."""
    num = lambda tier, name: float(number(f"fcc15255.{tier}.{name}").value)       # noqa: E731
    tag = lambda tier, name: number(f"fcc15255.{tier}.{name}").source             # noqa: E731
    f_lo, f_hi = f_lo_hz, f_hi_hz
    on = list(on_intervals)
    bw = f_hi - f_lo if occupied_bw_hz is None else occupied_bw_hz
    pt0, bo, gt = tx_power_dbm, tx_backoff_db, tx_gain_dbi
    pt = pt0 - bo                               # the transmitter as it runs
    given = dict(sources or {})
    lo, hi = float(number("fcc15255.band_low_hz").value), float(number("fcc15255.band_high_hz").value)
    res = ComplianceResult(rule=RULE, applies=False, why="", sweep_ghz=(f_lo / 1e9, f_hi / 1e9), eirp_dbm=pt + gt, conducted_dbm=pt,
                           n_tx=n_tx, frame_on_s=(on[-1][1] - on[0][0] if on else 0.0) if frame_on_s is None else frame_on_s,
                           frame_period_s=frame_period_s, scenario=scenario,
                           tx_power_dbm=pt0, tx_backoff_db=bo,
                           sources={**{k: given.get(k, NOT_STATED) for k in ("tx_power_dbm", "tx_backoff_db", "tx_gain_dbi")},
                                    "band": number("fcc15255.band_low_hz").source})
    if occupied_band_hz is not None:
        res.occupied_ghz = (occupied_band_hz[0] / 1e9, occupied_band_hz[1] / 1e9)
    if f_hi <= lo or f_lo >= hi:
        res.why = (f"the sweep {f_lo / 1e9:g}-{f_hi / 1e9:g} GHz lies outside the {lo / 1e9:g}-{hi / 1e9:g} GHz band this section "
                   f"governs; its limits are not applied to it")
        return res
    res.applies = True
    res.readings = READINGS
    if f_lo < lo or f_hi > hi:
        res.why = (f"the sweep {f_lo / 1e9:g}-{f_hi / 1e9:g} GHz is partly inside the {lo / 1e9:g}-{hi / 1e9:g} GHz band and leaves it: "
                   f"no tier of this section holds a sweep that does")
        return res
    res.why = f"the sweep {f_lo / 1e9:g}-{f_hi / 1e9:g} GHz lies inside the {lo / 1e9:g}-{hi / 1e9:g} GHz band"
    for tier, (label, scenarios, has_off, has_bw, has_cond) in TIERS.items():
        b_lo, b_hi = num(tier, "band_low_hz"), num(tier, "band_high_hz")
        limit = num(tier, "peak_eirp_dbm")
        cond = num(tier, "peak_conducted_dbm") if has_cond else None
        in_band = f_lo >= b_lo and f_hi <= b_hi
        bw_ok = (bw <= num(tier, "max_bandwidth_hz")) if has_bw else None
        scen = ("any" if scenarios is None else "not declared" if scenario is None
                else "met" if scenario in scenarios else "not met")
        off, need, have, t_min = "none required", None, None, None
        if has_off:
            need, win, run = num(tier, "off_time_sum_min_s"), num(tier, "off_time_window_s"), num(tier, "off_time_min_run_s")
            bursts = merge_bursts(on, run)
            t_min = min_frame_period(bursts, win, need, run)
            if t_min is None:
                off = "cannot be met"
            elif frame_period_s is None:
                off = "frame period not declared"
            else:
                have = min_off_sum(bursts, frame_period_s, win, run)
                off = "met" if have >= need - 1e-12 else "not met"
        usable = in_band and bw_ok is not False and scen in ("any", "met") and off in ("none required", "met", "frame period not declared")
        power_ok = res.eirp_dbm <= limit + 1e-12 and (cond is None or res.conducted_dbm <= cond + 1e-12)
        compliant = (False if not usable or not power_ok else None if off == "frame period not declared" else True)
        res.tiers.append(TierResult(
            tier=tier, label=label, band_ghz=(b_lo / 1e9, b_hi / 1e9), peak_eirp_limit_dbm=limit, conducted_limit_dbm=cond,
            in_band=in_band, bandwidth_ok=bw_ok, scenario=scen, off_time=off, off_time_required_s=need, off_time_have_s=have,
            min_frame_period_s=t_min, eirp_margin_db=limit - res.eirp_dbm,
            conducted_margin_db=None if cond is None else cond - res.conducted_dbm, usable=usable, power_ok=power_ok,
            compliant=compliant,
            sources={"peak_eirp_dbm": tag(tier, "peak_eirp_dbm"), "band": tag(tier, "band_low_hz"),
                     **({"off_time": tag(tier, "off_time_sum_min_s")} if has_off else {}),
                     **({"peak_conducted_dbm": tag(tier, "peak_conducted_dbm")} if has_cond else {})},
            in_band_measured=None if occupied_band_hz is None else bool(occupied_band_hz[0] >= b_lo and occupied_band_hz[1] <= b_hi),
            bandwidth_ok_measured=(None if occupied_band_hz is None or not has_bw
                                   else bool(occupied_band_hz[1] - occupied_band_hz[0] <= num(tier, "max_bandwidth_hz")))))
    usable = [t for t in res.tiers if t.usable]
    if usable:
        # the highest limit; between two equal ones the tier that asks for no off-time
        g = max(usable, key=lambda t: (t.peak_eirp_limit_dbm, t.off_time == "none required"))
        res.governing = g.tier
        # what the transmitter has to come down to: the tier's EIRP, and through its conducted limit if it has one
        capped_pt = pt if g.conducted_limit_dbm is None else min(pt, g.conducted_limit_dbm)
        res.eirp_cap_dbm = min(capped_pt + gt, g.peak_eirp_limit_dbm)
    return res


def check(cfg: RadarConfig, occupied_band_hz: tuple[float, float] | None = None) -> ComplianceResult:
    """The configuration against 47 CFR 15.255(c)(2).  Reads the sweep, the
    transmit power and antenna gain, the frame's burst, ``chirp.frame_period_s``
    and ``regulatory.scenario``; changes nothing.  ``check_emission`` on the
    config's numbers, the limits read from this library's source table.
    ``occupied_band_hz``: the chirp's measured occupied band, when the caller
    has run the chirp engine (``link.occupied.chirp_occupied_band``)."""
    from ..sources import number

    pt0, s_pt = cfg.frontend_value("tx_power_dbm")
    bo, s_bo = cfg.frontend_value("tx_backoff_db")
    gt, s_gt = cfg.frontend_value("tx_gain_dbi")
    c = cfg.chirp
    return check_emission(
        cfg.band.center_hz - 0.5 * cfg.band.sweep_hz, cfg.band.center_hz + 0.5 * cfg.band.sweep_hz, pt0, gt,
        frame_intervals(c.n_chirps, c.duration_s, c.pri_s), number=number, tx_backoff_db=bo, frame_period_s=c.frame_period_s,
        scenario=cfg.regulatory.scenario, n_tx=cfg.mimo.n_tx, occupied_bw_hz=cfg.band.sweep_hz, frame_on_s=c.frame_on_s,
        sources={"tx_power_dbm": s_pt, "tx_backoff_db": s_bo, "tx_gain_dbi": s_gt}, occupied_band_hz=occupied_band_hz)


__all__ = ["RULE", "TIERS", "READINGS", "NOT_STATED", "TierResult", "ComplianceResult", "check", "check_emission", "frame_intervals",
           "merge_bursts", "on_bursts", "min_off_sum", "min_frame_period"]

"""TX-to-RX leakage: the self-interference budget (milestone 2).

The transmitter's own signal reaches the receiver through the antenna /
package isolation (``isolation_db`` below the TX power; the 60 GHz band's
figure is a board array's without an isolation structure, read through
mmw60_trx's sourced table) after ``path_delay_s``, and through a
near reflector (radome, bumper) at ``reflector_range_m``.  Both mix with
the same LO, so each is a beat tone at ``S tau`` -- a few kHz, inside the
first range bins -- carrying the LO's phase noise after range correlation
at a tau of a fraction of a nanosecond, which is nothing (``2 (1 - cos 2 pi
f tau)`` is -100 dB there).  What the leakage does is power: a hundred dB
more than a target, it drives the receiver into compression and the ADC
into clipping unless the IF high-pass (``rx.hpf_*``) takes it out before
the ADC.  This module is the closed form of that: levels at every stage,
the high-pass's attenuation at the leakage beats, the headroom left, and
the attenuation still needed; the time engine (``engine.timedomain``) puts
the tones into the waveform and clips.

Compression is two points, not one.  A term whose beat lies below the
high-pass corner is removed before the IF stages and loads only what is
ahead of the filter: the out-of-band point (``p1db_oob_dbm``; the radar
chip's datasheet measures it with a tone below the lowest corner).  With no
filter, or a beat above the corner, the term is an in-band signal like the
echo and meets the in-band point, which is lower and falls with the gain.
``p1db_margin_db`` is the worst term against the point it meets.

The high-pass has a transient of its own: the sawtooth restarts the
leakage beat's phase at every chirp (a jump of ``2 pi f_beat T_c``), and
that step goes through the filter at the tone's full amplitude before the
filter has attenuated anything -- the first microseconds of every chirp
clip whatever the steady-state headroom says.  The closed form here is the
step's size (every term's ``2 A |sin(d_phi / 2)|``, summed) and the time
its decay through a Butterworth of order k (slowest pole damping
``sin(pi / 2k)``) takes to fall under what the ADC has left above the
steady leakage (full scale less the terms' amplitudes after the filter),
plus one time constant: ``blank_recommended_s``, what ``rx.blank_s`` should
be.  When the steady leakage itself reaches full scale behind the filter
there is nothing a blank can do -- the samples clip for the whole chirp --
and the budget says so (``steady_clipping``) instead of naming a time; the
figure to read then is the attenuation still needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config.schema import RadarConfig
from ..processing.iffilter import hpf_attenuation_db
from ..processing.windows import enbw_bins, range_window, spectrum_db
from .budget import LinkBudget, link_budget


@dataclass(frozen=True)
class LeakageTerm:
    name: str
    delay_s: float
    beat_hz: float
    level_rx_dbm: float          # at the receiver input
    level_adc_dbm: float         # at the ADC, before the high-pass
    hpf_atten_db: float
    level_adc_hpf_dbm: float     # at the ADC, after the high-pass
    window_sidelobe_at_target_db: float   # the range window's response at the target's bin, relative to the tone


@dataclass(frozen=True)
class LeakageBudget:
    terms: tuple[LeakageTerm, ...]
    isolation_db: float
    isolation_source: str
    p1db_margin_db: float        # the worst term's margin to the compression point it meets (negative: compression)
    p1db_kind: str               # which point that is: "out of band" (beat below the high-pass corner) or "in band"
    adc_headroom_db: float       # full scale minus the strongest term after the high-pass (negative: clipping)
    adc_headroom_no_hpf_db: float
    required_hpf_atten_db: float   # to keep the strongest term 6 dB below full scale
    target_level_adc_dbm: float
    leakage_at_target_cell_dbc: float   # the strongest term's window sidelobe at the target's bin, relative to the target
    hpf_atten_at_target_db: float       # what the high-pass costs the target's own beat (noise and tone alike)
    transient_step_v: float = 0.0       # the leakage phase jump at the chirp start as a step at the ADC [V], worst case
    hpf_time_constant_s: float = 0.0    # 1 / (2 pi f_c sin(pi / 2k)): the high-pass's slowest decay
    blank_recommended_s: float = 0.0    # for the step to fall under the ADC's remaining range, plus one time constant
                                        # (0: nothing to blank -- no transient clips, or the leakage clips for good)
    blank_s: float = 0.0                # what the config blanks
    blank_loss_db: float = 0.0          # the window refitted to the remaining samples: its SNR loss against no blanking
    steady_clipping: bool = False       # the leakage is at or over full scale behind the high-pass: blanking cannot help

    def as_rows(self) -> list[tuple[str, float, str]]:
        rows = [("TX-RX isolation", self.isolation_db, f"dB (source: {self.isolation_source})")]
        for t in self.terms:
            rows += [(f"{t.name}: beat", t.beat_hz / 1e3, "kHz"), (f"{t.name}: level at the receiver", t.level_rx_dbm, "dBm"),
                     (f"{t.name}: level at the ADC", t.level_adc_dbm, "dBm"),
                     (f"{t.name}: high-pass attenuation", t.hpf_atten_db, "dB"),
                     (f"{t.name}: at the ADC after the high-pass", t.level_adc_hpf_dbm, "dBm")]
        rows += [(f"P1dB margin (input, worst term, {self.p1db_kind} point)", self.p1db_margin_db, "dB"),
                 ("ADC headroom without the high-pass", self.adc_headroom_no_hpf_db, "dB"),
                 ("ADC headroom after the high-pass", self.adc_headroom_db, "dB"),
                 ("high-pass attenuation still needed (6 dB below full scale)", self.required_hpf_atten_db, "dB"),
                 ("target at the ADC", self.target_level_adc_dbm, "dBm"),
                 ("leakage window sidelobe at the target's cell", self.leakage_at_target_cell_dbc, "dBc"),
                 ("high-pass at the target's beat", self.hpf_atten_at_target_db, "dB"),
                 ("chirp-start step at the ADC (leakage phase jump)", self.transient_step_v, "V"),
                 ("high-pass time constant", self.hpf_time_constant_s * 1e6, "us"),
                 ("blanking recommended: none, the steady leakage clips behind this high-pass" if self.steady_clipping else
                  "blanking recommended (step under the ADC's remaining range + 1 time constant)", self.blank_recommended_s * 1e6, "us"),
                 ("blanking configured", self.blank_s * 1e6, "us"),
                 ("blanking SNR loss (window on the remaining samples)", self.blank_loss_db, "dB")]
        return rows


def leakage_budget(cfg: RadarConfig, budget: LinkBudget | None = None) -> LeakageBudget | None:
    if not cfg.leakage.enabled:
        return None
    b = link_budget(cfg) if budget is None else budget
    iso, iso_src = cfg.leakage_value("isolation_db")
    pt, _ = cfg.frontend_value("tx_power_dbm")
    g_rx, _ = cfg.frontend_value("rx_gain_db")
    p1_oob, _ = cfg.frontend_value("p1db_oob_dbm")
    p1_in, _ = cfg.p1db_inband()
    fs = cfg.rx.adc_fs_hz
    n = cfg.n_samples
    df = fs / n
    bins, wspec = spectrum_db(range_window(cfg.processing.window_range, n, cfg.n_blank), 16)
    f_target = cfg.beat_hz()
    terms = []
    paths = [("direct leakage", cfg.leakage.path_delay_s, pt - iso)]
    if cfg.leakage.reflector_range_m is not None:
        paths.append(("near reflector", cfg.tau_s(cfg.leakage.reflector_range_m), pt - iso + cfg.leakage.reflector_level_db))
    for name, tau, lvl_rx in paths:
        f_beat = cfg.slope_hz_per_s * tau
        att = hpf_attenuation_db(f_beat, cfg.rx.hpf_corner_hz, cfg.rx.hpf_order)
        d_bins = (f_target - f_beat) / df
        side = float(np.interp(abs(d_bins), bins, wspec, right=-300.0)) if abs(d_bins) <= bins[-1] else -300.0
        terms.append(LeakageTerm(name, tau, f_beat, lvl_rx, lvl_rx + g_rx, att, lvl_rx + g_rx - att, side))
    strongest = max(terms, key=lambda t: t.level_rx_dbm)
    # which compression point a term meets: one beating below the high-pass corner is taken out before the
    # IF stages and only loads the stages ahead of the filter (the out-of-band point, how the radar chip's
    # datasheet measures it); without a filter, or above its corner, it is an in-band signal like the echo
    def p1db_margin(t: LeakageTerm) -> tuple[float, str]:
        oob = cfg.rx.hpf_corner_hz > 0.0 and t.beat_hz < cfg.rx.hpf_corner_hz
        return (p1_oob if oob else p1_in) - t.level_rx_dbm, "out of band" if oob else "in band"

    p1_margin, p1_kind = min((p1db_margin(t) for t in terms), key=lambda mk: mk[0])
    strongest_hpf = max(terms, key=lambda t: t.level_adc_hpf_dbm)
    fs_dbm = cfg.rx.adc_fullscale_dbm
    headroom = fs_dbm - strongest_hpf.level_adc_hpf_dbm
    headroom0 = fs_dbm - strongest.level_adc_dbm
    att_target = hpf_attenuation_db(f_target, cfg.rx.hpf_corner_hz, cfg.rx.hpf_order)
    # the strongest term's window sidelobe at the target's bin relative to the target's own level
    at_cell = max(t.level_adc_hpf_dbm + t.window_sidelobe_at_target_db for t in terms) - (b.ps_adc_dbm - att_target)
    # the chirp-start transient: every term's phase jumps by 2 pi f_beat T_c
    # when the sawtooth restarts, a step of 2 A |sin(d_phi / 2)| at the ADC
    # (before the high-pass, which passes a step whole), the terms in phase
    # in the worst case; through a Butterworth high-pass of order k the step
    # decays no faster than its slowest pole, damping sin(pi / 2k)
    a_fs = math.sqrt(10.0 ** ((fs_dbm - 30.0) / 10.0) * 50.0)
    step_v = 0.0
    for t in terms:
        amp = math.sqrt(10.0 ** ((t.level_adc_dbm - 30.0) / 10.0) * 50.0)
        step_v += 2.0 * amp * abs(math.sin(math.pi * t.beat_hz * cfg.chirp.duration_s))
    if cfg.rx.hpf_corner_hz > 0.0:
        tau_hpf = 1.0 / (2.0 * math.pi * cfg.rx.hpf_corner_hz * math.sin(math.pi / (2.0 * cfg.rx.hpf_order)))
        # what the filter leaves of every term in the steady state, in phase at worst: the transient has to
        # decay into the range the ADC has left above it.  Nothing left: the samples clip all chirp long
        a_ss = sum(math.sqrt(10.0 ** ((t.level_adc_hpf_dbm - 30.0) / 10.0) * 50.0) for t in terms)
        steady = a_ss >= a_fs
        room = a_fs - a_ss
        blank_rec = tau_hpf * (math.log(step_v / room) + 1.0) if (not steady and step_v > room) else 0.0
    else:
        tau_hpf, blank_rec, steady = 0.0, 0.0, False                 # no filter: the leakage itself clips, not a transient
    w_full = range_window(cfg.processing.window_range, n)
    w_blank = range_window(cfg.processing.window_range, n, cfg.n_blank)
    blank_loss = 10.0 * math.log10(enbw_bins(w_blank) / enbw_bins(w_full))
    return LeakageBudget(tuple(terms), iso, iso_src, p1_margin, p1_kind, headroom, headroom0,
                         max(0.0, 6.0 - headroom), b.ps_adc_dbm - att_target, at_cell, att_target,
                         step_v, tau_hpf, blank_rec, cfg.rx.blank_s, blank_loss, steady)


def leakage_tones(cfg: RadarConfig) -> list[tuple[float, float]]:
    """``(delay [s], amplitude at the ADC [V])`` of every leakage term for the time engine."""
    lb = leakage_budget(cfg)
    if lb is None:
        return []
    return [(t.delay_s, math.sqrt(10.0 ** ((t.level_adc_dbm - 30.0) / 10.0) * 50.0)) for t in lb.terms]


__all__ = ["LeakageBudget", "LeakageTerm", "leakage_budget", "leakage_tones"]

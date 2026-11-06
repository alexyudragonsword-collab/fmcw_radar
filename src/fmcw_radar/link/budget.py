"""The radar equation and the noise at the ADC, in closed form (invariant #3's main engine, link part).

Received power of a point target of RCS sigma at range R::

    P_r = P_t G_t G_r lambda^2 sigma / ((4 pi)^3 R^4) / L_atm / L_extra

``L_atm`` is the oxygen line's specific attenuation (dB/km, source: survey)
over the round trip 2R.  The noise the beat signal competes with is the
front end's thermal noise (``k T0 F``, referred to the ADC through the
receive gain) plus the ADC's quantisation noise (a full-scale sine's SQNR
``6.02 b + 1.76`` dB spread over the complex sample rate), summed in power.

The detection SNR per range-Doppler cell is then the carrier-to-noise
density times the coherent gain of the two windowed FFTs::

    SNR_cell = (P_s / N0) x (sum w_r)^2 / (f_s sum w_r^2) x (sum w_d)^2 / sum w_d^2

which for rectangular windows is ``P_s T_c N_c / N0``, the matched-filter
energy SNR.  Every input carries its source: the front-end numbers are
placeholders (``assumed``) until mmw60_trx's front end exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config.schema import K_BOLTZMANN, T0_K, RadarConfig
from ..processing.windows import coherent_gain_db, enbw_hz, window


def db(x: float) -> float:
    return 10.0 * math.log10(max(x, 1e-300))


def dbm_to_w(p_dbm: float) -> float:
    return 10.0 ** ((p_dbm - 30.0) / 10.0)


def w_to_dbm(p_w: float) -> float:
    return db(p_w) + 30.0


@dataclass(frozen=True)
class LinkBudget:
    """Every line of the budget, in dB(m), with the source of each input."""

    inputs: dict                        # name -> (value, source)
    eirp_dbm: float
    path_loss_db: float                 # (4 pi)^3 R^4 / lambda^2
    atmos_loss_db: float                # oxygen over 2R
    extra_loss_db: float
    rcs_dbsm: float
    pr_dbm: float                       # received power at the antenna
    ps_adc_dbm: float                   # ... at the ADC (after rx_gain_db)
    n0_thermal_dbm_hz: float            # k T0 F at the antenna
    n0_thermal_adc_dbm_hz: float
    n0_quant_adc_dbm_hz: float          # ADC quantisation noise density
    n0_total_adc_dbm_hz: float
    cn0_dbhz: float                     # P_s / N0_total
    snr_chirp_db: float                 # one chirp, the config's range window
    snr_cell_db: float                  # the range-Doppler cell, both windows
    snr_cell_rect_db: float             # the same with rectangular windows (matched filter)
    window_loss_db: float               # rect - windowed
    enbw_range_hz: float                # the range FFT's noise bandwidth per bin
    p1db_margin_db: float               # P1dB (input) - P_r
    quant_share_db: float               # how much the ADC adds to the thermal floor

    def as_rows(self) -> list[tuple[str, float, str]]:
        """``(label, value, unit)`` rows for the report."""
        return [("EIRP", self.eirp_dbm, "dBm"), ("free-space path loss (4pi)^3 R^4 / lambda^2", self.path_loss_db, "dB"),
                ("oxygen over 2R", self.atmos_loss_db, "dB"), ("extra two-way loss", self.extra_loss_db, "dB"),
                ("RCS", self.rcs_dbsm, "dBsm"), ("received power P_r", self.pr_dbm, "dBm"),
                ("signal at the ADC", self.ps_adc_dbm, "dBm"),
                ("thermal noise density at the antenna k T0 F", self.n0_thermal_dbm_hz, "dBm/Hz"),
                ("thermal noise density at the ADC", self.n0_thermal_adc_dbm_hz, "dBm/Hz"),
                ("ADC quantisation noise density", self.n0_quant_adc_dbm_hz, "dBm/Hz"),
                ("total noise density at the ADC", self.n0_total_adc_dbm_hz, "dBm/Hz"),
                ("C/N0", self.cn0_dbhz, "dBHz"),
                ("SNR, one chirp, one range bin", self.snr_chirp_db, "dB"),
                ("SNR, one range-Doppler cell", self.snr_cell_db, "dB"),
                ("SNR, rectangular windows (matched filter)", self.snr_cell_rect_db, "dB"),
                ("window loss", self.window_loss_db, "dB"),
                ("P1dB margin (input, target only)", self.p1db_margin_db, "dB")]


def link_budget(cfg: RadarConfig, range_m: float | None = None) -> LinkBudget:
    r = cfg.target.range_m if range_m is None else float(range_m)
    pt, s_pt = cfg.frontend_value("tx_power_dbm")
    gt, s_gt = cfg.frontend_value("tx_gain_dbi")
    gr, s_gr = cfg.frontend_value("rx_gain_dbi")
    g_rx, s_grx = cfg.frontend_value("rx_gain_db")
    nf, s_nf = cfg.frontend_value("nf_db")
    p1, s_p1 = cfg.frontend_value("p1db_dbm")
    alpha, s_alpha = cfg.oxygen_db_per_km()
    rcs, s_rcs = cfg.rcs_dbsm()
    lam = cfg.band.wavelength_m
    eirp = pt + gt
    path = 3.0 * db(4.0 * math.pi) + 4.0 * db(r) - 2.0 * db(lam)     # (4 pi)^3 R^4 / lambda^2 in dB
    atmos = alpha * 2.0 * r / 1000.0
    extra = cfg.channel.extra_loss_db
    pr = eirp + gr + rcs - path - atmos - extra
    ps_adc = pr + g_rx
    n0_th = w_to_dbm(K_BOLTZMANN * T0_K) + nf
    n0_th_adc = n0_th + g_rx
    fs = cfg.rx.adc_fs_hz
    n0_q = cfg.rx.adc_fullscale_dbm - (6.02 * cfg.rx.adc_bits + 1.76) - db(fs)
    n0_tot = w_to_dbm(dbm_to_w(n0_th_adc) + dbm_to_w(n0_q))
    cn0 = ps_adc - n0_tot
    n = cfg.n_samples
    wr = window(cfg.processing.window_range, n)
    wd = window(cfg.processing.window_doppler, cfg.chirp.n_chirps)
    enbw_r = enbw_hz(wr, fs)
    snr_chirp = cn0 - db(enbw_r)
    snr_cell = snr_chirp + coherent_gain_db(wd)
    snr_rect = cn0 + db(cfg.chirp.duration_s) + db(cfg.chirp.n_chirps)
    return LinkBudget(
        inputs={"tx_power_dbm": (pt, s_pt), "tx_gain_dbi": (gt, s_gt), "rx_gain_dbi": (gr, s_gr),
                "rx_gain_db": (g_rx, s_grx), "nf_db": (nf, s_nf), "p1db_dbm": (p1, s_p1),
                "oxygen_db_per_km": (alpha, s_alpha), "rcs_dbsm": (rcs, s_rcs), "range_m": (r, "config"),
                "wavelength_m": (lam, "config")},
        eirp_dbm=eirp, path_loss_db=path, atmos_loss_db=atmos, extra_loss_db=extra, rcs_dbsm=rcs, pr_dbm=pr,
        ps_adc_dbm=ps_adc, n0_thermal_dbm_hz=n0_th, n0_thermal_adc_dbm_hz=n0_th_adc, n0_quant_adc_dbm_hz=n0_q,
        n0_total_adc_dbm_hz=n0_tot, cn0_dbhz=cn0, snr_chirp_db=snr_chirp, snr_cell_db=snr_cell,
        snr_cell_rect_db=snr_rect, window_loss_db=snr_rect - snr_cell, enbw_range_hz=enbw_r,
        p1db_margin_db=p1 - pr, quant_share_db=n0_tot - n0_th_adc)


def snr_vs_range(cfg: RadarConfig, ranges_m) -> np.ndarray:
    """Cell SNR [dB] at each range (the radar equation's R^-4 and the oxygen line)."""
    return np.array([link_budget(cfg, r).snr_cell_db for r in ranges_m])


def adc_amplitudes(cfg: RadarConfig, budget: LinkBudget) -> tuple[float, float, float]:
    """``(signal amplitude, full-scale amplitude, thermal noise sigma per
    sample)`` in volts on 50 ohm for the time engine: a complex tone of
    amplitude A has power A^2 / 50; the noise sigma is the complex variance
    (I + Q) of white noise of the thermal density over the waveform's sample
    rate, taken by the caller."""
    a_s = math.sqrt(dbm_to_w(budget.ps_adc_dbm) * 50.0)
    a_fs = math.sqrt(dbm_to_w(cfg.rx.adc_fullscale_dbm) * 50.0)
    n0_w = dbm_to_w(budget.n0_thermal_adc_dbm_hz)
    return a_s, a_fs, n0_w * 50.0


__all__ = ["LinkBudget", "link_budget", "snr_vs_range", "adc_amplitudes", "db", "dbm_to_w", "w_to_dbm"]

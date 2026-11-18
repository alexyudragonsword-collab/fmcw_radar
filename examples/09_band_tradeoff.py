"""Example 09: which part of the 60 GHz band, at what EIRP -- 47 CFR 15.255(c)(2) as a trade-off table.

The default radar sweeps 58-62 GHz at 22 dBm EIRP.  The rule's radar tiers
tie the peak EIRP to the band the sweep stays inside and, for some, to a
transmitter off-time and to where the radar is used (link/compliance.py;
every limit is ``source: spec``, read through spec_sources).  The table
puts the same target (a human at 5 m) and the same frame (64 chirps of
100 us) in each band and holds the EIRP to the governing tier's limit:
bandwidth buys range resolution, the tier sets the SNR and the frame rate.

The second table is what the limit does to the open question of the
antenna gain (ROADMAP, "upstream" item 1): once the EIRP is held to a
limit, the transmit antenna's gain no longer moves the SNR -- the receive
antenna's still does, dB for dB.  The last block runs the check on the
other bundled configs.

Nothing here changes a configuration: the "at the limit" columns are
``min(configured EIRP, limit)`` with everything else as configured.
"""

from _common import CONFIG, CONFIGS

from fmcw_radar.config import apply_overrides, load_config
from fmcw_radar.link import compliance_check, link_budget
from fmcw_radar.processing.cfarstats import cfar_snr_for_pd, cfar_statistics
from fmcw_radar.processing.windows import mainlobe_width_bins

C0 = 299_792_458.0
base = load_config(CONFIG)
ROWS = [("58-62 GHz (the default)", 58.0, 62.0, None),
        ("57-59.4 GHz, indoor", 57.0, 59.4, "indoor"),
        ("57-61.56 GHz", 57.0, 61.56, None),
        ("57-64 GHz, the whole band", 57.0, 64.0, None),
        ("57-64 GHz, outdoors, fixed", 57.0, 64.0, "outdoor_fixed")]


def at(lo, hi, scenario, **ov):
    return apply_overrides(base, {"band.center_hz": 0.5e9 * (lo + hi), "band.sweep_hz": 1e9 * (hi - lo),
                                  "regulatory.scenario": scenario, **ov})


def detection_range_m(cfg, cap, snr_req):
    """Where the cell SNR at the capped EIRP falls to what the map's CA-CFAR
    needs for Pd 0.9 (the radar equation and the oxygen, no IF-band limit)."""
    lo, hi = 0.5, 5000.0
    for _ in range(60):
        mid = (lo * hi) ** 0.5
        lo, hi = (mid, hi) if link_budget(cfg, range_m=mid, eirp_cap_dbm=cap).snr_cell_db > snr_req else (lo, mid)
    return lo


res0 = compliance_check(base)
print(f"{res0.rule}; the transmitter as configured: {res0.conducted_dbm:g} dBm conducted (source: {res0.sources['tx_power_dbm']}) + "
      f"{res0.eirp_dbm - res0.conducted_dbm:g} dBi (source: {res0.sources['tx_gain_dbi']}) = {res0.eirp_dbm:g} dBm EIRP; "
      f"one frame is a {res0.frame_on_s * 1e3:g} ms burst; target: {base.target.kind} at {base.target.range_m:g} m")
print("\nband by band (EIRP held to the governing tier's limit; SNR: one range-Doppler cell, the link budget's):")
print("  sweep                        | governing tier                                             | limit [dBm] | configured is  | "
      "B [GHz] | resolution [cm] | SNR at the limit [dB] | detection range [m] | IF-band range [m] | off-time needed         | "
      "max frame rate [1/s]")
for label, lo, hi, scen in ROWS:
    cfg = at(lo, hi, scen)
    r = compliance_check(cfg)
    g = r.tier
    b = link_budget(cfg, eirp_cap_dbm=r.eirp_cap_dbm)
    need = cfar_snr_for_pd(0.9, cfar_statistics(cfg))
    res_cm = mainlobe_width_bins(cfg.processing.window_range) * C0 / (2.0 * cfg.band.sweep_hz) * 100.0
    over = f"{-g.eirp_margin_db:.1f} dB over" if g.eirp_margin_db < 0 else f"{g.eirp_margin_db:.1f} dB under"
    off = "none" if g.off_time_required_s is None else f">= {g.off_time_required_s * 1e3:g} ms in any 33 ms"
    rate = "no limit" if g.max_frame_rate_hz is None else f"{g.max_frame_rate_hz:.1f}"
    print(f"  {label:28s} | {g.label:58s} | {g.peak_eirp_limit_dbm:11g} | {over:14s} | {cfg.band.sweep_hz / 1e9:7.2f} | {res_cm:15.2f} | "
          f"{b.snr_cell_db:21.2f} | {detection_range_m(cfg, r.eirp_cap_dbm, need):19.1f} | {cfg.max_range_m:17.2f} | {off:23s} | {rate}")
print("  (detection range: where the SNR at the limit meets what the map's CA-CFAR needs for Pd 0.9; the IF band cuts the "
      "radar off before that, and the oxygen figure is the band's one value, not the sweep centre's)")

print("\nwhy 58-62 GHz gets 14 dBm: the tiers and whether the sweep lies inside their band")
print("  tier                                                       | band [GHz]  | limit [dBm] | 58-62 inside | scenario     | usable")
for t in res0.tiers:
    print(f"  {t.label:58s} | {t.band_ghz[0]:g}-{t.band_ghz[1]:<7g} | {t.peak_eirp_limit_dbm:11g} | {'yes' if t.in_band else 'no':12s} | "
          f"{t.scenario:12s} | {'yes' if t.usable else 'no'}")
print(f"  governing: {res0.tier.label}; {res0.verdict}")

print("\nthe transmit antenna's gain under a limit (58-62 GHz; SNR of one cell [dB], configured / at the limit):")
print("  tx_gain_dbi | rx_gain_dbi | configured EIRP [dBm] | EIRP at the limit [dBm] | SNR configured | SNR at the limit")
for gt, gr in ((2.0, 10.0), (6.0, 10.0), (10.0, 10.0), (10.0, 8.0), (10.0, 12.0)):
    cfg = apply_overrides(base, {"frontend.tx_gain_dbi": gt, "frontend.rx_gain_dbi": gr})
    r = compliance_check(cfg)
    print(f"  {gt:11g} | {gr:11g} | {r.eirp_dbm:21g} | {r.eirp_cap_dbm:23g} | {link_budget(cfg).snr_cell_db:14.2f} | "
          f"{link_budget(cfg, eirp_cap_dbm=r.eirp_cap_dbm).snr_cell_db:16.2f}")
print("  (2, 6 and 10 dBi all come down to the tier's 14 dBm: the same SNR; the receive antenna moves it dB for dB)")

print("\nthe other bundled configs:")
for name in ("radar_60g_sensing", "radar_60g_mimo", "radar_60g_x10lo", "radar_60g_dither", "radar_77g_automotive"):
    cfg = load_config(CONFIGS / f"{name}.yaml")
    r = compliance_check(cfg)
    tx = f"{r.n_tx} TX in turn (TDM), one on at a time" if r.n_tx > 1 else "1 TX"
    if not r.applies:
        print(f"  {name:22s} | {tx} | EIRP {r.eirp_dbm:g} dBm | not applicable: {r.why}")
    else:
        print(f"  {name:22s} | {tx} | EIRP {r.eirp_dbm:g} dBm | {r.tier.label}, {r.tier.peak_eirp_limit_dbm:g} dBm | {r.verdict}")

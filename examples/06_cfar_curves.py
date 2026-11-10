"""Example 06: false alarm and detection curves of the cell-averaging CFAR.

The statistical side: Pd against SNR for the ideal detector (known noise
level, Swerling 0 closed form), the CA-CFAR with 16 and 32 training cells
(Swerling 0 by Monte Carlo, Swerling 1 in closed form), and the CFAR loss
at Pd = 0.9 -- what the threshold's own fluctuation costs.  Then the same
CFAR on the range-Doppler map, whose cells are correlated by the windows
and the zero-padding: the training set's effective size, its correlation
with the cell under test (the guard is counted in padded cells), the exact
per-cell false-alarm probability those give, and the realised rate on
white noise through the same processing and on the time engine's
noise-only frames (the transmitter turned down 200 dB).
"""

import numpy as np
from _common import CONFIG, OUT, SMOKE, plt_or_none, rel

from fmcw_radar.config import load_config
from fmcw_radar.engine import run_statistical
from fmcw_radar.engine.timedomain import run_time
from fmcw_radar.processing import cfar_pd_monte_carlo, cfar_pd_swerling1, cfar_threshold_factor, pd_swerling0, snr_for_pd
from fmcw_radar.processing.cfar import ca_cfar_2d, threshold_factor
from fmcw_radar.processing.cfarstats import cfar_snr_for_pd, cfar_statistics, count_clusters, noise_map
from fmcw_radar.processing.windows import window

pfa = 1e-4
snr = np.arange(4.0, 20.1, 1.0)
trials = 20_000 if SMOKE else 200_000
ideal = pd_swerling0(snr, pfa)
curves = {"ideal (known noise)": ideal}
for n in (16, 32):
    curves[f"CA-CFAR N={n}, Swerling 0 (MC)"] = cfar_pd_monte_carlo(snr, pfa, n, trials, seed=3)
    curves[f"CA-CFAR N={n}, Swerling 1 (closed form)"] = cfar_pd_swerling1(snr, pfa, n)
print(f"Pd against cell SNR at Pfa = {pfa:g} (threshold factors: N=16 {cfar_threshold_factor(16, pfa):.2f}, "
      f"N=32 {cfar_threshold_factor(32, pfa):.2f}, ideal {-np.log(pfa):.2f}):")
print("  SNR [dB] | " + " | ".join(f"{k[:28]:28s}" for k in curves))
for i, s in enumerate(snr):
    if i % 2 == 0:
        print(f"  {s:8.0f} | " + " | ".join(f"{v[i]:28.4f}" for v in curves.values()))


def snr_at(curve, pd):
    return float(np.interp(pd, curve, snr))


s_ideal = snr_for_pd(0.9, pfa)
print(f"\nSNR for Pd = 0.9: ideal {s_ideal:.2f} dB; CA-CFAR N=16 {snr_at(curves['CA-CFAR N=16, Swerling 0 (MC)'], 0.9):.2f} dB "
      f"(loss {snr_at(curves['CA-CFAR N=16, Swerling 0 (MC)'], 0.9) - s_ideal:.2f} dB), N=32 "
      f"{snr_at(curves['CA-CFAR N=32, Swerling 0 (MC)'], 0.9):.2f} dB (loss "
      f"{snr_at(curves['CA-CFAR N=32, Swerling 0 (MC)'], 0.9) - s_ideal:.2f} dB); a Rayleigh target (Swerling 1) needs "
      f"{snr_at(curves['CA-CFAR N=16, Swerling 1 (closed form)'], 0.9):.1f} dB at N=16")
pfa_mc = float(cfar_pd_monte_carlo(np.array([-300.0]), pfa, 16, trials * 4, seed=5)[0])
print(f"realised Pfa, 1-D MC, N=16: {pfa_mc:.2e} for {pfa:g} asked")

# --- the same CFAR on the range-Doppler map: its cells are neither independent of each other nor of the cell under test
cfg = load_config(CONFIG, {"frontend.tx_power_dbm": -190.0, "chirp.n_chirps": 8 if SMOKE else 32})
P = cfg.processing
cs = run_statistical(cfg).cfar
print(f"\n2-D CA-CFAR on the map ({cfg.chirp.n_chirps} chirps, {P.window_range} / {P.window_doppler}, range pad x{P.range_pad}, guard {P.cfar_guard} + "
      f"train {P.cfar_train} padded cells each side): {cs['n_train']} training cells worth {cs['n_train_eff']:.1f} independent ones "
      f"(one look spans {cs['correlation_length_range']:.2f} x {cs['correlation_length_doppler']:.2f} padded cells); the guard is "
      f"{cs['guard_bins_range']:g} range bins, so the training cells correlate {cs['cut_correlation']:.4f} with the cell under test")
print(f"  design Pfa {cs['pfa_design']:g}: the noisier threshold alone -> {cs['pfa_training_only']:.2e}; the test cell lifting its own threshold "
      f"alone -> {cs['pfa_cut_only']:.2e}; both, exact -> {cs['pfa_cell']:.3e}")
print(f"  a noise-only frame: {cs['cells_in_band']} cells in the IF band = {cs['independent_looks']:.0f} independent looks; "
      f"{cs['false_alarm_cells_per_frame']:.1f} false-alarm cells expected")

wd = window(P.window_doppler, cfg.chirp.n_chirps)
wr = window(P.window_range, cfg.n_samples)
designs = (1e-2, 1e-3, 1e-4)
frames_mc = 6 if SMOKE else 120
rng = np.random.default_rng(11)
count = {d: [0, 0] for d in designs}
cells_mc = 0
for _ in range(frames_mc):
    pm = noise_map(wd, P.doppler_pad, wr, P.range_pad, rng)
    cells_mc += pm.size
    for d in designs:
        _, det = ca_cfar_2d(pm, P.cfar_guard, P.cfar_train, d)
        count[d][0] += int(det.sum())
        count[d][1] += count_clusters(det)

frames_te = 1 if SMOKE else 6
n_if = int(cfg.rx.if_bw_hz * cfg.chirp.duration_s * P.range_pad)
edge = P.cfar_guard + P.cfar_train
te = {d: [0, 0] for d in designs}
cells_te = 0
for seed in range(frames_te):
    tm = run_time(cfg, phase_noise=False, seed=seed)
    pw = 10.0 ** (tm.rd_db / 10.0)
    band = np.zeros(pw.shape[1], dtype=bool)                               # both beat signs, clear of the brick wall's edge
    band[:n_if - edge] = True
    band[pw.shape[1] - (n_if - edge):] = True
    cells_te += pw.shape[0] * int(band.sum())
    for d in designs:
        _, det = ca_cfar_2d(pw, P.cfar_guard, P.cfar_train, d)
        te[d][0] += int(det[:, band].sum())
        te[d][1] += count_clusters(det[:, band])
print(f"  realised per-cell Pfa: white noise through the same windows and padding ({frames_mc} maps, {cells_mc:.2e} cells) and the time "
      f"engine's noise-only frames ({frames_te} frames, {cells_te:.2e} in-band cells); clusters are 8-connected groups of detections")
print("  design Pfa | exact      | noise maps (cells / clusters)       | time engine (cells / clusters)")
for d in designs:
    ex = cfar_statistics(load_config(CONFIG, {"chirp.n_chirps": cfg.chirp.n_chirps, "processing.cfar_pfa": d}))["pfa_cell"]
    print(f"  {d:10g} | {ex:.3e}  | {count[d][0] / cells_mc:.3e} ({count[d][0]:6d} / {count[d][1]:5d})        | "
          f"{te[d][0] / cells_te:.3e} ({te[d][0]:5d} / {te[d][1]:4d})")
print(f"  detection on this map: a Pd of 0.9 takes {cs['snr_pd90_db']:.2f} dB (known noise level {s_ideal:.2f}: CFAR loss {cs['cfar_loss_db']:.2f} dB, "
      f"of which the target's own leak into its training cells, {cs['tone_leak']:.4f} of its power, is part)")
mimo = cfar_statistics(load_config(CONFIG, {"chirp.n_chirps": cfg.chirp.n_chirps, "mimo.n_tx": 2, "mimo.n_rx": 4}))
print(f"  the same frame as a 2 x 4 TDM-MIMO cube: {mimo['n_looks']} looks summed per cell, {cfg.chirp.n_chirps // 2} chirps per TX; threshold factor "
      f"{mimo['threshold_factor']:.2f} ({10 * np.log10(mimo['threshold_factor']):.1f} dB over the mean) where the single-look factor for its "
      f"{mimo['n_train']} training cells is {threshold_factor(mimo['n_train'], pfa):.2f} "
      f"({10 * np.log10(threshold_factor(mimo['n_train'], pfa)):.1f} dB) -- used on the sum it would give Pfa "
      f"{mimo['pfa_with_single_look_factor']:.1e} and cost {mimo['single_look_factor_penalty_db']:.1f} dB; exact per-cell Pfa {mimo['pfa_cell']:.2e}, "
      f"Pd 0.9 at {cfar_snr_for_pd(0.9, mimo):.2f} dB per look")
print("  what the guard does (exact per-cell Pfa at the design 1e-4, same windows and padding):")
for g in (0, 2, 4, 8, 12):
    s_g = cfar_statistics(load_config(CONFIG, {"chirp.n_chirps": cfg.chirp.n_chirps, "processing.cfar_guard": g}))
    print(f"    guard {g:2d} cells = {s_g['guard_bins_range']:4.2f} range bins: {s_g['n_train']:4d} training cells worth {s_g['n_train_eff']:5.1f}, "
          f"correlation with the test cell {s_g['cut_correlation']:.4f}, Pfa {s_g['pfa_cell']:.2e}")

plt = plt_or_none()
if plt is not None:
    fig, ax = plt.subplots(figsize=(6, 4))
    for k, v in curves.items():
        ax.plot(snr, v, label=k)
    ax.set_xlabel("cell SNR [dB]")
    ax.set_ylabel("Pd")
    ax.set_title(f"detection probability, Pfa = {pfa:g}")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = OUT / "06_cfar_curves.png"
    fig.savefig(p, dpi=120)
    print(f"  wrote {rel(p)}")

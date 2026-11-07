"""Example 06: false alarm and detection curves of the cell-averaging CFAR.

The statistical side: Pd against SNR for the ideal detector (known noise
level, Swerling 0 closed form), the CA-CFAR with 16 and 32 training cells
(Swerling 0 by Monte Carlo, Swerling 1 in closed form), and the CFAR loss
at Pd = 0.9 -- what the threshold's own fluctuation costs.  The time
engine side: the 2-D CA-CFAR on noise-only frames (the transmitter turned
down 200 dB), the realised false-alarm rate against the asked-for one.
"""

import numpy as np
from _common import CONFIG, OUT, SMOKE, plt_or_none, rel

from fmcw_radar.config import load_config
from fmcw_radar.engine.timedomain import run_time
from fmcw_radar.processing import cfar_pd_monte_carlo, cfar_pd_swerling1, cfar_threshold_factor, pd_swerling0, snr_for_pd

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

cfg = load_config(CONFIG, {"frontend.tx_power_dbm": -190.0, "chirp.n_chirps": 8 if SMOKE else 32})
tm = run_time(cfg, phase_noise=False)
n_cells = tm.rd_db.shape[0] * (tm.rd_db.shape[1] // 2)
n_train = (2 * (cfg.processing.cfar_guard + cfg.processing.cfar_train) + 1) ** 2 - (2 * cfg.processing.cfar_guard + 1) ** 2
print(f"time engine, noise only ({tm.n_chirps} chirps, 2-D CA-CFAR with {n_train} training cells, Pfa {cfg.processing.cfar_pfa:g}): "
      f"{len(tm.cfar_detections)} false alarms in {n_cells} cells = {len(tm.cfar_detections) / n_cells:.2e}")
print("  (the map is zero-padded x4 in range: neighbouring cells are correlated, so the count is not a free-sample estimate)")

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

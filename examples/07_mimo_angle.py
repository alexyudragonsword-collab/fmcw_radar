"""Example 07: TDM-MIMO angle estimation on the 2 x 4 virtual array.

The bundled MIMO config without its second target and leakage: a human at
5 m, 20 deg, receding at 2 m/s.  Statistical: the virtual array's
beamwidth, the Cramer-Rao bound at the per-element cell SNR, the bias the
receive array's mutual coupling leaves on a DBF estimate (array_tx's
survey-shaped matrix, source: assumed), the bias the TDM Doppler phase
would leave uncompensated, and what the 4 GHz sweep does to the manifold
(next to FR2's 400 MHz).  Time engine: the estimate over several noise
seeds against the bound, with the coupling off / on / calibrated and the
compensation on / off.
"""

import numpy as np
from _common import CONFIGS, OUT, SMOKE, plt_or_none, rel

from fmcw_radar.config import load_config
from fmcw_radar.engine import run_statistical
from fmcw_radar.engine.timedomain import run_time
from fmcw_radar.mimo import VirtualArray

MIMO = CONFIGS / "radar_60g_mimo.yaml"
n_chirps = 8
cfg = load_config(MIMO, {"extra_targets": [], "leakage.enabled": False, "rx.hpf_corner_hz": 0.0, "chirp.n_chirps": n_chirps,
                         "mimo.coupling.source": "none"})
st = run_statistical(cfg)
a = st.angle
va = VirtualArray(cfg)
print(f"2 TX x 4 RX, RX pitch {cfg.mimo.rx_spacing_lambda:g} lambda, TX pitch {cfg.mimo.tx_pitch_lambda:g} lambda -> {a['n_virtual']} virtual "
      f"elements, {'a filled line' if a['filled'] else 'not filled'}, aperture {a['aperture_m'] * 1e3:.1f} mm; element pattern "
      f"{cfg.mimo.element_pattern}; {n_chirps} chirps = {n_chirps // 2} per TX")
print(f"  target at {cfg.target.angle_deg:g} deg: beamwidth {a['beamwidth_deg']:.2f} deg, per-element cell SNR {a['snr_element_db']:.1f} dB, "
      f"Cramer-Rao bound {a['crlb_sigma_deg']:.3f} deg RMS; DBF estimate on the ideal snapshot {a['theta_est_deg']:+.3f} deg, "
      f"angle sidelobe {a['peak_sidelobe_db']:.1f} dB ({cfg.mimo.angle_window})")
print(f"  TDM: unambiguous velocity +-{a['max_velocity_mps']:.2f} m/s; the Doppler phase between the TX blocks would bias the "
      f"estimate by {a['tdm_bias_uncompensated_deg']:+.2f} deg at {cfg.target.velocity_mps:g} m/s if not compensated")
print(f"  the sweep: edge virtual element's beat {a['edge_shift_bins']:.3f} range bins off, window taper {a['edge_taper_db']:.3f} dB; "
      f"a phase-shifter-steered TX beam aligned at 60 GHz would squint {a['tx_beam_squint_deg'][0]:+.2f} / {a['tx_beam_squint_deg'][1]:+.2f} deg "
      f"at the sweep edges (FR2 28 GHz / 400 MHz: {a['fr2_400mhz_squint_deg'][0]:+.2f} / {a['fr2_400mhz_squint_deg'][1]:+.2f} deg)")

print("\nRX mutual coupling (array_tx's matrix at the carrier) and the DBF estimate, noiseless:")
print("  source   | adjacent [dB] | bias uncalibrated [deg] | angle sidelobe [dB] | bias calibrated [deg]")
for src in ("none", "analytic", "survey"):
    c = load_config(MIMO, {"extra_targets": [], "leakage.enabled": False, "rx.hpf_corner_hz": 0.0, "chirp.n_chirps": n_chirps,
                           "mimo.coupling.source": src})
    s = run_statistical(c).angle
    cc = load_config(MIMO, {"extra_targets": [], "leakage.enabled": False, "rx.hpf_corner_hz": 0.0, "chirp.n_chirps": n_chirps,
                            "mimo.coupling.source": src, "mimo.coupling.calibrated": True})
    adj = f"{s['coupling_max_offdiag_db']:.1f}" if s["coupling_max_offdiag_db"] is not None else "-"
    print(f"  {src:8s} | {adj:>13s} | {s['coupling_bias_deg']:+23.3f} | {s['peak_sidelobe_db']:19.1f} | "
          f"{run_statistical(cc).angle['coupling_bias_deg']:+21.4f}")

seeds = [1, 2] if SMOKE else [1, 2, 3, 4, 5, 6]
print(f"\ntime engine, {len(seeds)} noise seeds x {n_chirps} chirps, the estimate at the target's cell:")
print("  case                               | mean error [deg] | RMS error [deg] | bound [deg]")
cases = [("no coupling, compensated", {}),
         ("survey coupling, uncalibrated", {"mimo.coupling.source": "survey"}),
         ("survey coupling, calibrated", {"mimo.coupling.source": "survey", "mimo.coupling.calibrated": True}),
         ("no coupling, NOT compensated", {"mimo.tdm_doppler_compensation": False})]
for label, ov in cases:
    c = load_config(MIMO, {"extra_targets": [], "leakage.enabled": False, "rx.hpf_corner_hz": 0.0, "chirp.n_chirps": n_chirps,
                           "mimo.coupling.source": "none", **ov})
    errs = []
    for sd in seeds:
        tm = run_time(c, seed=sd)
        errs.append(tm.extras["angle_deg"] - c.target.angle_deg)
    errs = np.array(errs)
    bound = run_statistical(c).angle["crlb_sigma_deg"]
    print(f"  {label:34s} | {errs.mean():+16.3f} | {np.sqrt(np.mean(errs ** 2)):15.3f} | {bound:11.3f}")

two = load_config(MIMO, {"leakage.enabled": False, "rx.hpf_corner_hz": 0.0, "chirp.n_chirps": n_chirps, "mimo.coupling.source": "none"})
tm = run_time(two, seed=1)
print("\ntwo targets (the bundled config's human at 20 deg and car at -10 deg, 30 cm apart), angle at each one's cell:")
for t, f in zip(two.targets, tm.extras["targets_found"]):
    print(f"  {t.kind:6s} at {t.range_m:g} m, {t.angle_deg:+g} deg: " + (f"found {f[0]:.3f} m, estimate {f[3]:+.2f} deg" if f else "not found"))

plt = plt_or_none()
if plt is not None:
    u, p = tm.extras["angle_spectrum"]
    fig, ax = plt.subplots(figsize=(6, 3.8))
    ax.plot(np.degrees(np.arcsin(u)), p)
    ax.set_xlabel("angle [deg]")
    ax.set_ylabel("dB")
    ax.set_title("DBF spectrum at the strongest cell (the car at -10 deg)")
    ax.set_ylim(-60, 2)
    fig.tight_layout()
    pth = OUT / "07_mimo_angle.png"
    fig.savefig(pth, dpi=120)
    print(f"  wrote {rel(pth)}")

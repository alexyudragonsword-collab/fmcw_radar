"""Example 00: one target, the range-Doppler map, and the SNR against the radar equation.

The bundled 60 GHz config (``configs/radar_60g_sensing.yaml``): a human at
5 m receding at 2 m/s.  The statistical engine gives the cell SNR from the
radar equation and the windows' coherent gains; the time engine mixes a
real 4 GHz-envelope chirp with its delayed copy, filters, samples, quantises
and FFTs, and reads the peak off the map.  The two SNRs must agree within
1 dB (invariant #3); the peak must sit at the configured range and
velocity.  Every front-end number is a placeholder (source: assumed).
"""

from _common import CONFIG, OUT, SMOKE, plt_or_none, tag, rel

from fmcw_radar.config import apply_overrides, load_config
from fmcw_radar.engine import run_radar

cfg = load_config(CONFIG, {"sim.engine": "both"})
if SMOKE:
    cfg = apply_overrides(cfg, {"sim.time_n_chirps": 8})
res = run_radar(cfg)
st, tm = res.stat, res.time
b = st.budget

print(f"60 GHz sensing radar: {cfg.band.sweep_hz / 1e9:g} GHz sweep, {cfg.chirp.duration_s * 1e6:g} us chirps x "
      f"{cfg.chirp.n_chirps}, {cfg.rx.adc_fs_hz / 1e6:g} MS/s, {cfg.processing.window_range} windows")
print(f"  TX {tag(cfg, 'tx_power_dbm')} dBm + {tag(cfg, 'tx_gain_dbi')} dBi; RX {tag(cfg, 'rx_gain_dbi')} dBi, "
      f"NF {tag(cfg, 'nf_db')} dB")
print(f"  target: {cfg.target.kind} at {cfg.target.range_m:g} m, {cfg.target.velocity_mps:+g} m/s, "
      f"RCS {b.rcs_dbsm:g} dBsm (source: {b.inputs['rcs_dbsm'][1]})")
print("radar equation:")
for lab, v, u in b.as_rows():
    print(f"  {lab:48s} {v:9.2f} {u}")
print(f"  beat {st.beat_hz / 1e3:.1f} kHz = range bin {st.range_bin:.2f}; Doppler {st.doppler_hz:+.1f} Hz = bin "
      f"{st.doppler_bin:+.2f}")
print(f"  Pd {st.pd:.4f} at Pfa {cfg.processing.cfar_pfa:g} (Swerling 0, cell SNR {st.snr_cell_db:.2f} dB)")
print(f"time engine ({tm.n_chirps} chirps, {tm.extras['fs_wave_hz'] / 1e9:g} GS/s envelope, {tm.extras['n_wave']} "
      f"samples per chirp):")
print(f"  peak at {tm.peak_range_m:.3f} m (interpolated {tm.extras['peak_range_interp_m']:.3f} m), "
      f"{tm.peak_velocity_mps:+.3f} m/s; configured {cfg.target.range_m:g} m, {cfg.target.velocity_mps:+g} m/s")
snr_expect = st.extras["snr_cell_expected_db"] if tm.n_chirps == cfg.chirp.n_chirps else None
print(f"  measured cell SNR {tm.snr_cell_db:.2f} dB" + (f" vs statistical {snr_expect:.2f} dB expected on the grid "
      f"(scalloping {st.extras['scalloping_range_db']:.2f} + {st.extras['scalloping_doppler_db']:.2f} dB, LO noise "
      f"{st.extras['pn_cell_mean_dbc']:.1f} dBc per cell over the band): "
      f"difference {tm.snr_cell_db - snr_expect:+.2f} dB" if snr_expect is not None else " (smoke size)"))
print(f"  -3 dB width of the range response {tm.width_3db_m * 100:.2f} cm (window theory "
      f"{st.range_res_m * 100:.2f} cm, c/2B {st.range_res_rect_m * 100:.2f} cm)")
near = [(v, r) for v, r in tm.cfar_detections
        if abs(r - cfg.target.range_m) < 4 * cfg.range_resolution_m and abs(v - cfg.target.velocity_mps) < 3 * cfg.velocity_resolution_mps]
far = [(v, r) for v, r in tm.cfar_detections if (v, r) not in near]
print(f"  CA-CFAR (guard {cfg.processing.cfar_guard}, train {cfg.processing.cfar_train}, Pfa {cfg.processing.cfar_pfa:g}): "
      f"{len(tm.cfar_detections)} cells over threshold, {len(near)} in the target's lobe (the zero-padded grid's "
      f"neighbours), {len(far)} elsewhere" + (": " + ", ".join(f"{r:.2f} m / {v:+.2f} m/s" for v, r in far[:4])
                                               + " -- the cycle-accurate engine's quantisation spur (ROADMAP P1 #1)"
                                               if far else ""))

plt = plt_or_none()
if plt is not None:
    import numpy as np

    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    half = tm.rd_db.shape[1] // 2
    ext = [tm.range_axis_m[0], tm.range_axis_m[half - 1], tm.velocity_axis_mps[0], tm.velocity_axis_mps[-1]]
    top = tm.rd_db[:, :half].max()
    ax[0].imshow(tm.rd_db[:, :half], origin="lower", aspect="auto", extent=ext, vmin=top - 80, vmax=top, cmap="viridis")
    ax[0].set_xlabel("range [m]")
    ax[0].set_ylabel("velocity [m/s]")
    ax[0].set_title("range-Doppler map (time engine)")
    ax[1].plot(tm.range_profile_axis_m, tm.range_profile_db, lw=0.8)
    ax[1].axhline(-st.snr_chirp_db, color="k", ls="--", lw=0.8, label=f"thermal floor, one chirp ({-st.snr_chirp_db:.0f} dBc)")
    offs = np.array(sorted(st.pn_floor))
    ax[1].plot(cfg.target.range_m + offs, [st.pn_floor[o][0] for o in offs], "r.", label="LO phase noise after range correlation (closed form)")
    ax[1].set_xlim(0, cfg.max_range_m)
    ax[1].set_ylim(-110, 2)
    ax[1].set_xlabel("range [m]")
    ax[1].set_ylabel("dB rel. peak")
    ax[1].set_title("range profile, last chirp")
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    p = OUT / "00_single_target_rd_map.png"
    fig.savefig(p, dpi=120)
    print(f"  wrote {rel(p)}")

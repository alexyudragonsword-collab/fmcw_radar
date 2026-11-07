"""Example 05: several point targets and who hides whom.

Targets are inputs (invariant #5): the primary human at 5 m with a car
30 cm behind it at the same speed, a second human at 9.9 m closing, and a
weak reflector 12 cm from the car.  The statistical engine gives every
target its own radar-equation SNR and the strongest other target's skirt
at its cell -- the range window's sidelobe at the range offset, the Doppler
window's at the Doppler offset, or the LO's residual noise through range
correlation at the other's round trip, whichever is higher -- and calls a
target masked when that skirt is above its own level.  The time engine
superposes the four echoes and reads each one off the map.
"""

from _common import CONFIG, OUT, SMOKE, plt_or_none, rel

from fmcw_radar.config import load_config
from fmcw_radar.engine import run_radar

extra = [{"kind": "car", "range_m": 5.3, "velocity_mps": 2.0},
         {"kind": "human", "range_m": 9.9, "velocity_mps": -1.0},
         {"kind": "custom", "range_m": 5.42, "velocity_mps": 2.0, "rcs_dbsm": -20.0}]
cfg = load_config(CONFIG, {"extra_targets": extra, "sim.engine": "both", "chirp.n_chirps": 8 if SMOKE else 32})
res = run_radar(cfg)
st, tm = res.stat, res.time

print(f"{len(cfg.targets)} targets, {cfg.chirp.n_chirps} chirps, {cfg.processing.window_range} windows, range bin "
      f"{cfg.range_resolution_m * 100:.2f} cm, Doppler bin {cfg.velocity_resolution_mps:.3f} m/s")
print("  # | kind   | range [m] | v [m/s] | RCS [dBsm] | level at ADC [dBm] | cell SNR [dB] | strongest other's skirt here [dBc] | by | masked")
for i, t in enumerate(st.targets):
    skirt = f"{t['interference_dbc']:+7.1f} | {t['interference_kind']} (#{t['interferer']})" if t["interferer"] is not None else "      - | -"
    print(f"  {i} | {t['kind']:6s} | {t['range_m']:9.2f} | {t['velocity_mps']:+7.2f} | {t['rcs_dbsm']:10g} | {t['ps_adc_dbm']:18.2f} | "
          f"{t['snr_cell_db']:13.2f} | {skirt} | {'YES' if t['masked'] else 'no'}")

print(f"\ntime engine ({tm.n_chirps} chirps): each target's peak within +-3 range bins / +-2 Doppler bins of its place,"
      " level relative to the map's peak (None: no local maximum above the median floor + 6 dB there; a neighbour closer than the window keeps the bins nearer itself)")
ref = max(t["ps_adc_dbm"] for t in st.targets)
for i, (t, f) in enumerate(zip(st.targets, tm.extras["targets_found"])):
    expect = t["ps_adc_dbm"] - ref
    if f is None:
        print(f"  {i} {t['kind']:6s}: not found (statistical: {expect:+.1f} dB rel. the strongest, masked = {t['masked']})")
    else:
        print(f"  {i} {t['kind']:6s}: found at {f[0]:.3f} m, {f[1]:+.2f} m/s, {f[2]:+.1f} dB rel. the strongest "
              f"(statistical {expect:+.1f} dB; difference {f[2] - expect:+.1f} dB)")
print(f"  CA-CFAR cells over threshold: {len(tm.cfar_detections)}")

plt = plt_or_none()
if plt is not None:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    half = tm.rd_db.shape[1] // 2
    ext = [tm.range_axis_m[0], tm.range_axis_m[half - 1], tm.velocity_axis_mps[0], tm.velocity_axis_mps[-1]]
    top = tm.rd_db[:, :half].max()
    ax.imshow(tm.rd_db[:, :half], origin="lower", aspect="auto", extent=ext, vmin=top - 80, vmax=top, cmap="viridis")
    for t in cfg.targets:
        ax.plot(t.range_m, t.velocity_mps, "r+", ms=10)
    ax.set_xlim(0, 12)
    ax.set_xlabel("range [m]")
    ax.set_ylabel("velocity [m/s]")
    ax.set_title("four targets (+: configured)")
    fig.tight_layout()
    p = OUT / "05_multi_target_masking.png"
    fig.savefig(p, dpi=120)
    print(f"  wrote {rel(p)}")

"""Example 08: TX-to-RX leakage and the IF high-pass.

The transmitter's own signal reaches the receiver 25 dB down (source:
assumed, until mmw60_trx's package says otherwise) and a near reflector
at 2 cm adds another 10 dB lower; both beat at a few kHz, a hundred dB
above the target.  The statistical budget: levels at the receiver and the
ADC, the P1dB margin, the ADC headroom with and without the high-pass, the
attenuation still needed.  The time engine: the ADC clips without the
filter and the target is gone; with a second-order high-pass at 200 kHz
it is back, and the flyback's transient through the filter is what still
clips the first microseconds of every chirp -- the budget says how long,
``rx.blank_s`` blanks them and refits the range window to the rest, and
the far range floor drops back to where it is with no leakage at all.
"""
import numpy as np

from _common import CONFIGS, SMOKE

from fmcw_radar.config import load_config
from fmcw_radar.engine import run_statistical
from fmcw_radar.engine.timedomain import run_time

MIMO = CONFIGS / "radar_60g_mimo.yaml"
base = {"mimo.n_tx": 1, "mimo.n_rx": 1, "mimo.coupling.source": "none", "extra_targets": [], "chirp.n_chirps": 4 if SMOKE else 8}
cfg = load_config(MIMO, base)
st = run_statistical(cfg)
lb = st.leakage
print(f"leakage budget (TX {cfg.frontend_value('tx_power_dbm')[0]:g} dBm, isolation {lb.isolation_db:g} dB (source: {lb.isolation_source}), "
      f"reflector at {cfg.leakage.reflector_range_m:g} m {cfg.leakage.reflector_level_db:+g} dB; high-pass order {cfg.rx.hpf_order} "
      f"at {cfg.rx.hpf_corner_hz / 1e3:g} kHz):")
for lab, v, u in lb.as_rows():
    print(f"  {lab:62s} {v:9.2f} {u}")

def far_floor_db(tm):
    """The range profile's mean 2-4 m from the radar relative to the target's own level at 5 m [dB]:
    the leakage's transient spreads there, the targets do not."""
    ax, pr = tm.range_profile_axis_m, tm.range_profile_db
    return float(np.mean(pr[(ax > 2.0) & (ax < 4.0)]) - pr[int(np.argmin(np.abs(ax - 5.0)))])


print("\ntime engine: clipped ADC samples and the target, with and without the high-pass, with and without blanking;"
      " the far floor relative to the target with the thermal noise on (what a frame sees) and off (what the transient alone leaves)")
print("  high-pass                        | blank [us] | clipped [%] | after blanking [%] | floor 2-4 m rel. target, noise on / off [dB] | target found | at [m] | level rel. map peak [dB]")
cases = [("none", {"rx.hpf_corner_hz": 0.0}), ("1st order 200 kHz", {"rx.hpf_order": 1}),
         ("2nd order 200 kHz", {}), ("2nd order 50 kHz", {"rx.hpf_corner_hz": 50e3})]
for label, ov in list(cases):
    rec = run_statistical(load_config(MIMO, {**base, **ov})).leakage.blank_recommended_s
    if rec > 0.0:
        cases.append((f"{label}, blanked", {**ov, "rx.blank_s": round(rec * 1e7) / 1e7}))
for label, ov in cases:
    c = load_config(MIMO, {**base, **ov})
    tm = run_time(c)
    f = tm.extras["targets_found"][0]
    found = f"yes | {f[0]:6.3f} | {f[2]:+.1f}" if f else "no | - | -"
    quiet = run_time(c, noise=False, phase_noise=False)
    print(f"  {label:32s} | {c.rx.blank_s * 1e6:10.1f} | {100 * tm.extras['clipped_fraction']:11.2f} | "
          f"{100 * tm.extras['clipped_fraction_after_blanking']:18.2f} | {far_floor_db(tm):22.1f} / {far_floor_db(quiet):6.1f}"
          f"         | {found}")
ref = run_time(load_config(MIMO, base), leakage=False)
quiet_ref = run_time(load_config(MIMO, base), leakage=False, noise=False, phase_noise=False)
print(f"  (reference, no leakage at all: floor {far_floor_db(ref):.1f} / {far_floor_db(quiet_ref):.1f} dB rel. the target, noise on / off."
      f" With the filter the clipped samples are the flyback transient at each chirp's start and the budget's recommended blank covers"
      f" them; what remains after the blank is the chirp's last sample, where the engine's circular IF filter rings the next step back)")

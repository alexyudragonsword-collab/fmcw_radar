"""Example 08: TX-to-RX leakage and the IF high-pass.

The transmitter's own signal reaches the receiver 25 dB down (source:
assumed, until mmw60_trx's package says otherwise) and a near reflector
at 2 cm adds another 10 dB lower; both beat at a few kHz, a hundred dB
above the target.  The statistical budget: levels at the receiver and the
ADC, the P1dB margin, the ADC headroom with and without the high-pass, the
attenuation still needed.  The time engine: the ADC clips without the
filter and the target is gone; with a second-order high-pass at 200 kHz
it is back, and the flyback's transient through the filter is what still
clips the first microseconds of every chirp.
"""

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

print("\ntime engine: clipped ADC samples and the target, with and without the high-pass")
print("  high-pass            | clipped [%] | cell SNR [dB] | target found | at [m] | level rel. map peak [dB]")
for label, ov in (("none", {"rx.hpf_corner_hz": 0.0}), ("1st order 200 kHz", {"rx.hpf_order": 1}),
                  ("2nd order 200 kHz", {}), ("2nd order 50 kHz", {"rx.hpf_corner_hz": 50e3})):
    c = load_config(MIMO, {**base, **ov})
    tm = run_time(c)
    f = tm.extras["targets_found"][0]
    found = f"yes | {f[0]:6.3f} | {f[2]:+.1f}" if f else "no | - | -"
    print(f"  {label:20s} | {100 * tm.extras['clipped_fraction']:11.2f} | {tm.snr_cell_db:13.1f} | {found}")
print("  (with the filter the clipped samples are the flyback transient at each chirp's start, which the range window"
      " weights near zero; blanking them is a ROADMAP item)")

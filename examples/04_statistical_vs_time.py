"""Example 04: the statistical engine against the time engine (invariant #3).

Three checks on the same config: the cell SNR at three ranges (radar
equation vs a mixed, filtered, quantised waveform; < 1 dB), the phase-noise
sidelobe floor at three range offsets (closed form vs the averaged range
profiles of phase-noise-only chirps; < 0.5 dB where the noise dominates the
window's own sidelobes), and the chirp-nonlinearity range response (the
error curve fed into one FFT vs the full time engine on the same curve).
"""

import numpy as np
from _common import CONFIG, SMOKE

from fmcw_radar.chirp import ChirpEngine
from fmcw_radar.config import load_config
from fmcw_radar.engine import run_radar
from fmcw_radar.engine.statistical import nonlinearity_profile
from fmcw_radar.engine.timedomain import measured_pn_sidelobes, run_time

n_time = 8 if SMOKE else 32
print(f"cell SNR, {n_time} chirps, three ranges (statistical 'expected': the radar equation less the windows'\n"
      "scalloping at the target's fractional bins, over the thermal floor plus the LO's residual noise averaged\n"
      "over the band -- what the time engine's map-wide noise estimate sees):")
print("  range [m] | radar equation [dB] | on the grid [dB] | expected [dB] | time engine [dB] | difference [dB]")
for r in (2.0, 5.0, 10.0):
    cfg = load_config(CONFIG, {"target.range_m": r, "chirp.n_chirps": n_time, "sim.engine": "both"})
    res = run_radar(cfg)
    grid, exp = res.stat.extras["snr_cell_on_grid_db"], res.stat.extras["snr_cell_expected_db"]
    print(f"  {r:9g} | {res.stat.snr_cell_db:19.2f} | {grid:16.2f} | {exp:13.2f} | {res.time.snr_cell_db:16.2f} | "
          f"{res.time.snr_cell_db - exp:+15.2f}")

n_pn = 16 if SMOKE else 64
cfg = load_config(CONFIG)
offs = (1.0, 2.0, 5.0)
m = measured_pn_sidelobes(cfg, offs, n_chirps=n_pn, half_bins=5, window_name="blackman")
print(f"\nphase-noise floor around the target at {cfg.target.range_m:g} m, Blackman window, {n_pn} chirps averaged, "
      f"+-5 bins:")
print("  offset [m] | closed form [dBc/bin] | measured [dBc/bin] | difference [dB]")
for o in offs:
    d = m[o]
    print(f"  {o:10g} | {d['closed_form_dbc']:21.2f} | {d['measured_dbc']:18.2f} | {d['measured_dbc'] - d['closed_form_dbc']:+15.2f}")

print("\nchirp nonlinearity: the ADPLL curve fed into one FFT vs the time engine mixing the same curve "
      "(5 % mismatch, no calibration, no noise, target at rest so both lobes sit on the same bins):")
cfg = load_config(CONFIG, {"lo.dp_gain": 1.05, "lo.dp_cal": "none", "chirp.n_chirps": 3, "sim.time_n_chirps": 3,
                           "processing.range_pad": 8, "target.velocity_mps": 0.0})
chirp = ChirpEngine(cfg).run(noise=False)
nl = nonlinearity_profile(cfg, chirp, 2, pad=8)
tm = run_time(cfg, chirp, noise=False, phase_noise=False, quantise=False)
# the time engine's profile relative to its peak, on the same offset grid
prof_t = tm.range_profile_db
i = int(np.argmax(prof_t))
axis_t = (np.arange(prof_t.size) - i) * (cfg.range_resolution_m / cfg.processing.range_pad)
sel = (np.abs(axis_t) < 0.6)
sel_s = (np.abs(nl["axis_m"]) < 0.6)
print(f"  statistical: -3 dB width {nl['width_3db_m'] * 100:.2f} cm, peak sidelobe {nl['peak_sidelobe_db']:.1f} dB, "
      f"ISLR {nl['islr_db']:.1f} dB")
print(f"  time engine: -3 dB width {tm.width_3db_m * 100:.2f} cm, peak sidelobe {tm.peak_sidelobe_db:.1f} dB")
a = np.interp(axis_t[sel], nl["axis_m"][sel_s], nl["profile_db"][sel_s])
d = prof_t[sel] - a
above = prof_t[sel] > -60.0
print(f"  profiles within +-60 cm, where above -60 dB: max |difference| {np.max(np.abs(d[above])):.2f} dB, "
      f"RMS {np.sqrt(np.mean(d[above] ** 2)):.2f} dB")

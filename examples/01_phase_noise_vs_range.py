"""Example 01: LO phase noise after range correlation, 0.1 to 100 m.

One LO drives both mixers, so the beat signal carries ``phi(t) - phi(t -
tau)`` and sees ``2 (1 - cos 2 pi f tau) S_phi(f)``: nothing at zero
range, the LO's own noise doubled far out (invariant #2).  The range-FFT
sidelobe floor around a target follows: at a given range offset the beat
frequency offset is fixed, so the floor rises with the target's range
until ``1 / (6 tau)`` crosses that offset.  The closed form is checked
against synthesised sequences (band-averaged) at 1, 10 and 100 m.
"""

import numpy as np
from _common import CONFIG, OUT, SMOKE, plt_or_none

from fmcw_radar.config import load_config
from fmcw_radar.lo import LOProfile
from fmcw_radar.phase_noise import RangeCorrelation, correlation_factor
from fmcw_radar.processing.windows import enbw_bins, window

cfg = load_config(CONFIG)
prof = LOProfile.from_config(cfg)
print(f"LO: {prof.source}")
for f in (1e3, 1e4, 1e5, 1e6, 1e7):
    print(f"  L({f / 1e3:g} kHz) = {float(prof.l_dbc(f)):.1f} dBc/Hz at {cfg.band.center_hz / 1e9:g} GHz")

ranges = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
offsets_m = [0.25, 1.0, 5.0]
enbw = enbw_bins(window(cfg.processing.window_range, cfg.n_samples)) / cfg.chirp.duration_s
print(f"\nrange-FFT noise bandwidth per bin {enbw / 1e3:.1f} kHz ({cfg.processing.window_range}); the sidelobe floor "
      f"[dBc per bin, one chirp] at a range offset from the target -- exact Gaussian-phase spectrum, and in brackets\n"
      "the first-order S_res/2 where it differs by more than 1 dB (the in-band noise beating with itself fills in\n"
      "near the tone once the residual is no longer small):")
print("  target range [m] | tau [ns] | 1/(6 tau) [kHz] | " + " | ".join(f"{'+' + format(o, 'g') + ' m':>16s}" for o in offsets_m)
      + " | residual RMS [mrad] | carrier loss [dB]")
f1, f2 = 1.0 / cfg.chirp.duration_s, cfg.rx.if_bw_hz
for r in ranges:
    rc = RangeCorrelation(prof, cfg.tau_s(r))
    sb = rc.beat_sideband(4.0 * cfg.rx.if_bw_hz, 1 << 16, 0.5 * cfg.sim.time_osr * cfg.band.sweep_hz)
    cells = []
    for o in offsets_m:
        df = cfg.slope_hz_per_s * cfg.tau_s(o)
        ex, fo = float(sb.sidelobe_dbc(df, enbw)), float(rc.sidelobe_dbc(df, enbw))
        cells.append(f"{ex:6.1f}" + (f" ({fo:6.1f})" if abs(ex - fo) > 1.0 else " " * 9))
    print(f"  {r:16g} | {rc.tau_s * 1e9:8.2f} | {1 / (6 * rc.tau_s) / 1e3:15.0f} | " + " | ".join(cells)
          + f" | {rc.rms_residual_rad(f1, f2) * 1e3:19.2f} | {sb.carrier_loss_db:17.3f}")
print(f"  (the LO itself: {prof.rms_phase_rad(f1, f2) * 1e3:.1f} mrad RMS over [{f1 / 1e3:g} kHz, {f2 / 1e6:g} MHz])")

# closed form against synthesis, band-averaged, at the acceptance ranges
print("\nclosed form vs synthesised residual (one-sided PSD, averaged over octave bands):")
fs, n = cfg.rx.adc_fs_hz, 1 << 14
blocks = 4 if SMOKE else 24
edges = np.geomspace(2e4, 4e6, 9)
for r in (1.0, 10.0, 100.0):
    rc = RangeCorrelation(prof, cfg.tau_s(r))
    f, meas = rc.measured_residual_psd(n, fs, np.random.default_rng(7), blocks)
    closed = rc.residual_psd(f)
    worst = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (f >= lo) & (f < hi)
        d = 10.0 * np.log10(meas[m].mean() / closed[m].mean())
        worst = max(worst, abs(d))
    print(f"  {r:5g} m: worst band difference {worst:.3f} dB over {blocks} blocks of {n}")
rc0 = RangeCorrelation(prof, 0.0)
print(f"  tau = 0: residual max |phi| = {np.max(np.abs(rc0.synthesize_residual(n, fs, np.random.default_rng(1)))):g} rad")

plt = plt_or_none()
if plt is not None:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    f = np.geomspace(1e3, 5e6, 400)
    ax[0].semilogx(f, prof.l_dbc(f), "k", label="LO at the carrier")
    for r in (0.1, 1.0, 10.0, 100.0):
        rc = RangeCorrelation(prof, cfg.tau_s(r))
        ax[0].semilogx(f, rc.residual_l_dbc(f), label=f"residual, R = {r:g} m")
    ax[0].set_xlabel("offset [Hz]")
    ax[0].set_ylabel("dBc/Hz")
    ax[0].set_ylim(-150, -60)
    ax[0].legend(fontsize=7)
    ax[0].set_title("range correlation 2(1 - cos 2 pi f tau) S_phi")
    rr = np.geomspace(0.1, 100.0, 200)
    for o in offsets_m:
        df = cfg.slope_hz_per_s * cfg.tau_s(o)
        lv = [float(prof.l_dbc(df)) + 10 * np.log10(correlation_factor(df, cfg.tau_s(r))) + 10 * np.log10(enbw) for r in rr]
        ax[1].semilogx(rr, lv, label=f"offset {o:g} m ({df / 1e3:.0f} kHz)")
    ax[1].set_xlabel("target range [m]")
    ax[1].set_ylabel("sidelobe [dBc per bin]")
    ax[1].legend(fontsize=7)
    ax[1].set_title("phase-noise floor vs target range")
    fig.tight_layout()
    p = OUT / "01_phase_noise_vs_range.png"
    fig.savefig(p, dpi=120)
    print(f"  wrote {p}")

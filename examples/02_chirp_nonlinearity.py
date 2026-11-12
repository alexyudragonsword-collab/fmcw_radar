"""Example 02: chirp nonlinearity from the ADPLL loop, and what it does to range resolution and sidelobes.

The frequency error of the chirp comes from the vendored two-point ADPLL
driven by the ramp (invariant #4): the flyback's loop settling, the
two-point gain mismatch, the TDC's and the DCO's quantisation.  The
cycle-accurate engine and the linearised one are compared on the mismatch
transient; the offline calibration (polar_tx's least-squares two-point
estimator, one chirp per pass) takes a built-in mismatch out; and the
error curve is fed into one range FFT to read the width and the sidelobes
of a point target.  An analytic quadratic of the same RMS is the reference
group: it shows what an assumed term misses (the flyback transient is a
step, not a parabola).
"""

import numpy as np
from _common import CONFIG, OUT, SMOKE, plt_or_none, rel

from fmcw_radar.chirp import ChirpEngine, quadratic_reference
from fmcw_radar.config import load_config
from fmcw_radar.engine.statistical import coherent_spurs, ideal_profile, nonlinearity_profile
from fmcw_radar.lo import LOProfile

base = load_config(CONFIG, {"chirp.n_chirps": 4})
ideal = ideal_profile(base)
print(f"window alone ({base.processing.window_range}): -3 dB width {ideal['width_3db_m'] * 100:.2f} cm, peak sidelobe "
      f"{ideal['peak_sidelobe_db']:.1f} dB; c/2B = {base.range_resolution_m * 100:.2f} cm")
print(f"DCO {base.dco_center_hz / 1e9:g} GHz x{base.lo_mult}, ramp {base.dco_sweep_hz / 1e6:g} MHz at the DCO in "
      f"{base.chirp.duration_s * 1e6:g} us, fref {base.lo.fref_hz / 1e6:g} MHz, loop {base.lo.loop_bw_hz / 1e6:g} MHz")

rows = []
cases = [("matched, event (loop + quantisation)", {"lo.dp_gain": 1.0, "lo.dp_cal": "none"}),
         ("5 % mismatch, event, no cal", {"lo.dp_gain": 1.05, "lo.dp_cal": "none"}),
         ("5 % mismatch, response (linearised)", {"lo.dp_gain": 1.05, "lo.dp_cal": "none", "lo.engine": "response"}),
         ("5 % mismatch, event, offline cal x2", {"lo.dp_gain": 1.05, "lo.dp_cal": "offline"}),
         ("5 % mismatch, event, online cal", {"lo.dp_gain": 1.05, "lo.dp_cal": "online"})]
curves = {}
for label, ov in cases:
    cfg = load_config(CONFIG, {"chirp.n_chirps": 4, **ov})
    c = ChirpEngine(cfg).run(noise=False)
    m = c.metrics(2)
    nl = nonlinearity_profile(cfg, c, 2)
    curves[label] = (c, nl)
    extra = ""
    if c.dp_cal_passes:
        extra = " passes eps=" + ",".join(f"{p['eps_hat']:.4f}" for p in c.dp_cal_passes)
    if c.dp_cal_trace is not None:
        extra = (" online gain 1.05 -> " + " -> ".join(f"{c.dp_cal_trace[k * c.n_ramp - 1]:.4f}" for k in (1, 2, 3, 4))
                 + " over 4 chirps (post-flyback LMS)")
    print(f"\n{label} [{c.engine}, {c.cpu_s:.2f} s]{extra}")
    print(f"  ramp 2: initial error {m['initial_error_hz'] / 1e6:.3f} MHz settled to +-{m['settle_band_hz'] / 1e3:.0f} kHz "
          f"in {m['settle_s'] * 1e9:.0f} ns; peak {m['peak_hz'] / 1e6:.3f} MHz, RMS {m['rms_hz'] / 1e3:.1f} kHz, "
          f"floor {m['floor_rms_hz'] / 1e3:.1f} kHz RMS (carrier)")
    print(f"  range response: -3 dB width {nl['width_3db_m'] * 100:.2f} cm, peak sidelobe {nl['peak_sidelobe_db']:.1f} dB, "
          f"ISLR {nl['islr_db']:.1f} dB, beat phase perturbation {nl['phase_rms_rad'] * 1e3:.1f} mrad RMS")
    if nl["ghosts"]:
        print("  this ramp's pattern, undithered (offset m, dBc): " + ", ".join(f"{dr:+.2f} / {lvl:.1f}" for dr, lvl in nl["ghosts"][:4])
              + ("" if c.vouches_for_spurs else "  [linearised curve: not vouched for]"))
    rows.append((label, m, nl))

# event vs response on the mismatch transient, cycle by cycle
ce = curves["5 % mismatch, event, no cal"][0].ramp_carrier(2)
cr = curves["5 % mismatch, response (linearised)"][0].ramp_carrier(2)
k = np.arange(1, 40)
ratio = ce[k] / cr[k]
print(f"\nevent / response on the first 40 cycles after the flyback: ratio {ratio.mean():.4f} +- {ratio.std():.4f} "
      f"(event floor {np.std(ce[-2000:]) / 1e3:.0f} kHz RMS, response floor 0: the quantisation)")

# the reference group
ev = curves["5 % mismatch, event, no cal"][0]
rms = float(np.std(ev.ramp(2)))
q = quadratic_reference(base, rms, 4)
nlq = nonlinearity_profile(base, q, 2)
print(f"\nreference group: analytic quadratic of the same RMS ({rms * base.lo_mult / 1e3:.0f} kHz at the carrier): "
      f"-3 dB width {nlq['width_3db_m'] * 100:.2f} cm, peak sidelobe {nlq['peak_sidelobe_db']:.1f} dB, ISLR "
      f"{nlq['islr_db']:.1f} dB -- the loop's step-and-decay puts its energy elsewhere than a parabola would")

# the TDC's quantisation as a frame sees it: with the loop's noise on, what stays coherent over the ramps
n_frame = 8 if SMOKE else 32
print(f"\nthe pattern above is one noise-off ramp.  With the loop's noise on, over {n_frame} ramps, what stays coherent "
      f"(TDC {base.lo_value('tdc_res_s')[0] * 1e12:g} ps; its own jitter dithers the quantisation and is noise in the LO profile):")
print("  TDC jitter [ps RMS] | strongest coherent spurs (offset m / dBc)             | search limit [dBc] | LO L(1 MHz) [dBc/Hz]")
for jit in (0.0, 0.5e-12, 1e-12, 2e-12):
    c_j = load_config(CONFIG, {"lo.dp_cal": "none", "lo.tdc_jitter_s": jit, "chirp.n_chirps": n_frame})
    cs = coherent_spurs(c_j, ChirpEngine(c_j).run(noise=True, seed=c_j.sim.seed, n_chirps=n_frame + 1))
    top = ", ".join(f"{dr:+.2f} / {lvl:.1f}" for dr, lvl in cs["ghosts"][:3]) or "none above the limit"
    mark = "  <- the placeholder" if jit == base.lo_value("tdc_jitter_s")[0] else ""
    print(f"  {jit * 1e12:19.1f} | {top:52s} | {cs['limit_dbc']:18.1f} | {float(LOProfile.from_config(c_j).l_dbc(1e6)):20.1f}{mark}")

plt = plt_or_none()
if plt is not None:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    t = base.n_ref_cycles and (np.arange(base.n_ref_cycles) / base.lo.fref_hz * 1e6)
    for label, (c, _) in curves.items():
        ax[0].plot(t, c.ramp_carrier(2) / 1e6, lw=0.8, label=label)
    ax[0].plot(t, q.ramp_carrier(2) / 1e6, "k--", lw=0.8, label="quadratic reference (same RMS)")
    ax[0].set_xlabel("time in ramp [us]")
    ax[0].set_ylabel("frequency error at the carrier [MHz]")
    ax[0].set_xlim(0, 10)
    ax[0].legend(fontsize=6)
    ax[0].set_title("chirp frequency error, ramp 2 (first 10 us)")
    ax[1].plot(ideal["axis_m"] * 100, ideal["profile_db"], "k", lw=1.0, label="window alone")
    for label, (_, nl) in curves.items():
        ax[1].plot(nl["axis_m"] * 100, nl["profile_db"], lw=0.8, label=label)
    ax[1].plot(nlq["axis_m"] * 100, nlq["profile_db"], "k--", lw=0.8, label="quadratic reference")
    ax[1].set_xlim(-60, 60)
    ax[1].set_ylim(-90, 2)
    ax[1].set_xlabel("range offset [cm]")
    ax[1].set_ylabel("dB")
    ax[1].legend(fontsize=6)
    ax[1].set_title("point-target range response from the error curve")
    fig.tight_layout()
    p = OUT / "02_chirp_nonlinearity.png"
    fig.savefig(p, dpi=120)
    print(f"  wrote {rel(p)}")

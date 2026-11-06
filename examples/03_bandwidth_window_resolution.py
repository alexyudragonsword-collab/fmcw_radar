"""Example 03: sweep bandwidth x window -> the range-resolution table.

``c / 2B`` is one range bin; a window widens the lobe by its -3 dB mainlobe
width in bins (Harris 1978, Table I: rect 0.89, Hann 1.44, Hamming 1.30,
Blackman 1.68 -- source: survey) and buys its sidelobe level.  The table is
the window's own spectrum on the config's grid (statistical), checked on
the time engine's processed point target for the ideal chirp (measured):
the rectangular lobe at the Rayleigh level is one bin = c / 2B.
"""

from _common import CONFIG, OUT, SMOKE, plt_or_none

from fmcw_radar.config import load_config
from fmcw_radar.engine.statistical import ideal_profile
from fmcw_radar.engine.timedomain import run_time
from fmcw_radar.processing.windows import mainlobe_width_bins, peak_sidelobe_db
from fmcw_radar.sources import number

sweeps = [1e9, 2e9, 4e9, 7e9]
windows = ["rect", "hann", "hamming", "blackman"]
print("window | -3 dB width [bins] (own spectrum) | Harris 1978 (source: survey) | peak sidelobe [dB]")
for w in windows:
    print(f"  {w:8s} | {mainlobe_width_bins(w):6.3f} | {number(f'window.{w}_3db_bins').value:5.2f} | {peak_sidelobe_db(w):6.1f}")

print("\nrange resolution [cm], -3 dB width of the point-target response (statistical: window spectrum):")
print("  sweep [GHz] | c/2B [cm] | " + " | ".join(f"{w:8s}" for w in windows))
for b in sweeps:
    cfg = load_config(CONFIG, {"band.sweep_hz": b, "band.center_hz": 60.5e9 if b > 6e9 else 60e9})
    cells = []
    for w in windows:
        c = load_config(CONFIG, {"band.sweep_hz": b, "band.center_hz": 60.5e9 if b > 6e9 else 60e9,
                                 "processing.window_range": w})
        cells.append(ideal_profile(c)["width_3db_m"] * 100)
    print(f"  {b / 1e9:11g} | {cfg.range_resolution_m * 100:9.2f} | " + " | ".join(f"{v:8.2f}" for v in cells))

print("\nmeasured on the time engine (ideal chirp, no noise, no phase noise), 4 GHz sweep:")
print("  window   | Rayleigh width [cm] | c/2B [cm] | -3 dB width [cm] | theory [cm] | peak sidelobe [dB]")
for w in windows:
    c = load_config(CONFIG, {"lo.engine": "ideal", "processing.window_range": w, "chirp.n_chirps": 2,
                             "sim.time_n_chirps": 2, "processing.range_pad": 8})
    tm = run_time(c, noise=False, phase_noise=False, quantise=False)
    th = ideal_profile(c)
    print(f"  {w:8s} | {tm.width_rayleigh_m * 100:19.2f} | {c.range_resolution_m * 100:9.2f} | {tm.width_3db_m * 100:16.2f} | "
          f"{th['width_3db_m'] * 100:11.2f} | {tm.peak_sidelobe_db:18.1f}")

plt = plt_or_none()
if plt is not None and not SMOKE:
    fig, ax = plt.subplots(figsize=(6, 4))
    for w in windows:
        c = load_config(CONFIG, {"processing.window_range": w, "processing.range_pad": 16})
        pr = ideal_profile(c)
        ax.plot(pr["axis_m"] * 100, pr["profile_db"], label=f"{w}: {pr['width_3db_m'] * 100:.2f} cm, {pr['peak_sidelobe_db']:.0f} dB")
    ax.set_xlim(-40, 40)
    ax.set_ylim(-90, 2)
    ax.set_xlabel("range offset [cm]")
    ax.set_ylabel("dB")
    ax.set_title("point-target range response, B = 4 GHz")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = OUT / "03_bandwidth_window_resolution.png"
    fig.savefig(p, dpi=120)
    print(f"  wrote {p}")

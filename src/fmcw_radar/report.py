"""The radar's budget as a structured report: ``report`` (dict) and ``to_markdown``.

``tools/budget_report.py`` is the command line over these (d2d_link's
``report.py`` method).  Nothing here simulates beyond the statistical engine
(invariant #1: it reads the config and ``StatResult``); every number that
is not the config's own carries its source (invariant #5).
"""

from __future__ import annotations

from .config.schema import RadarConfig
from .engine.statistical import REPORT_OFFSETS_M, StatResult, run_statistical
from .sources import all_entries


def report(cfg: RadarConfig, st: StatResult) -> dict:
    b = st.budget
    placeholders = {k: {"value": v, "source": src} for k, (v, src) in b.inputs.items()}
    out = {
        "radar": {"band": cfg.band.kind, "center_ghz": cfg.band.center_hz / 1e9, "sweep_ghz": cfg.band.sweep_hz / 1e9,
                  "chirp_us": cfg.chirp.duration_s * 1e6, "idle_us": cfg.chirp.idle_s * 1e6,
                  "n_chirps": cfg.chirp.n_chirps, "slope_mhz_per_us": cfg.slope_hz_per_s / 1e12,
                  "lo_dco_ghz": cfg.dco_center_hz / 1e9, "lo_mult": cfg.lo_mult, "lo_fref_mhz": cfg.lo.fref_hz / 1e6,
                  "lo_loop_bw_mhz": cfg.lo.loop_bw_hz / 1e6, "lo_engine": cfg.lo.engine, "lo_source": st.extras.get("lo_source"),
                  "if_bw_mhz": cfg.rx.if_bw_hz / 1e6, "adc_fs_msps": cfg.rx.adc_fs_hz / 1e6, "adc_bits": cfg.rx.adc_bits,
                  "range_res_rect_m": st.range_res_rect_m, "range_res_m": st.range_res_m,
                  "range_window": cfg.processing.window_range, "window_sidelobe_db": st.window_sidelobe_db,
                  "max_range_m": st.extras["max_range_m"], "velocity_res_mps": st.velocity_res_mps,
                  "max_velocity_mps": st.extras["max_velocity_mps"]},
        "target": {"kind": cfg.target.kind, "range_m": cfg.target.range_m, "velocity_mps": cfg.target.velocity_mps,
                   "rcs_dbsm": b.rcs_dbsm, "rcs_source": b.inputs["rcs_dbsm"][1], "beat_khz": st.beat_hz / 1e3,
                   "doppler_hz": st.doppler_hz, "range_bin": st.range_bin, "doppler_bin": st.doppler_bin,
                   "in_if_band": st.extras["in_if_band"]},
        "inputs": placeholders,
        "budget": [{"term": lab, "value": v, "unit": u} for lab, v, u in b.as_rows()],
        "detection": {"snr_cell_db": st.snr_cell_db, "snr_chirp_db": st.snr_chirp_db, "pfa": cfg.processing.cfar_pfa,
                      "pd": st.pd, "quant_share_db": b.quant_share_db},
        "phase_noise": {"lo_rms_rad": st.lo_rms_rad, "residual_rms_rad": st.pn_rms_rad,
                        "floor": [{"offset_m": dr, "per_bin_dbc": v[0], "per_cell_dbc": v[1]} for dr, v in st.pn_floor.items()]},
        "chirp": st.chirp, "nonlinearity": st.nonlinearity,
    }
    return out


def to_markdown(rep: dict) -> str:
    R, T, D = rep["radar"], rep["target"], rep["detection"]
    lines = [f"# FMCW radar budget: {R['band']}, {R['center_ghz']:g} GHz, B = {R['sweep_ghz']:g} GHz, "
             f"T_c = {R['chirp_us']:g} us x {R['n_chirps']} chirps", "",
             f"Slope {R['slope_mhz_per_us']:g} MHz/us; LO: {R['lo_dco_ghz']:g} GHz ADPLL x{R['lo_mult']} "
             f"(fref {R['lo_fref_mhz']:g} MHz, loop {R['lo_loop_bw_mhz']:g} MHz, chirp engine `{R['lo_engine']}`); "
             f"IF {R['if_bw_mhz']:g} MHz, ADC {R['adc_fs_msps']:g} MS/s x {R['adc_bits']} bit.", "",
             f"Range resolution c/2B {R['range_res_rect_m'] * 100:.2f} cm, with the {R['range_window']} window "
             f"{R['range_res_m'] * 100:.2f} cm (-3 dB; sidelobe {R['window_sidelobe_db']:.1f} dB); max range "
             f"{R['max_range_m']:.2f} m (IF band); velocity resolution {R['velocity_res_mps']:.3f} m/s, "
             f"unambiguous +-{R['max_velocity_mps']:.2f} m/s.", "",
             f"Target: {T['kind']} at {T['range_m']:g} m, {T['velocity_mps']:+g} m/s, RCS {T['rcs_dbsm']:g} dBsm "
             f"(source: {T['rcs_source']}); beat {T['beat_khz']:.1f} kHz (bin {T['range_bin']:.1f}"
             f"{'' if T['in_if_band'] else ', OUTSIDE the IF band'}), Doppler {T['doppler_hz']:+.1f} Hz "
             f"(bin {T['doppler_bin']:+.2f}).", "",
             "## Link budget (radar equation)", "", "| term | value | unit |", "|---|---:|---|"]
    for row in rep["budget"]:
        lines.append(f"| {row['term']} | {row['value']:.2f} | {row['unit']} |")
    lines += ["", f"Detection: cell SNR {D['snr_cell_db']:.1f} dB -> Pd {D['pd']:.4f} at Pfa {D['pfa']:g} "
              f"(Swerling 0, known noise level; the ADC adds {D['quant_share_db']:.2f} dB to the thermal floor).", "",
              "## Inputs and their sources", "", "| input | value | source |", "|---|---:|---|"]
    for k, v in rep["inputs"].items():
        lines.append(f"| {k} | {v['value']:.4g} | {v['source']} |")
    P = rep["phase_noise"]
    lines += ["", "## LO phase noise after range correlation", "",
              f"LO {P['lo_rms_rad'] * 1e3:.1f} mrad RMS over [1/T_c, IF]; what the beat sees after the round trip "
              f"{P['residual_rms_rad'] * 1e3:.2f} mrad RMS. Sidelobe floor around the target:", "",
              "| offset [m] | per range bin, one chirp [dBc] | per range-Doppler cell [dBc] |", "|---:|---:|---:|"]
    for row in P["floor"]:
        lines.append(f"| {row['offset_m']:g} | {row['per_bin_dbc']:.1f} | {row['per_cell_dbc']:.1f} |")
    C, N = rep["chirp"], rep["nonlinearity"]
    if C:
        lines += ["", "## Chirp linearity (from the vendored ADPLL loop)", "",
                  f"Engine `{C['engine']}`{' (cycle-accurate: may vouch for spurs)' if C.get('vouches_for_spurs') else ' (linearised: cannot vouch for spurs)'}; "
                  f"direct-path gain used {C['dp_gain_used']:.5f}"
                  + (f" after offline passes eps = {', '.join(f'{e:.2e}' for e in C['dp_cal_passes'])}" if C.get('dp_cal_passes') else "")
                  + f"; polar_tx's event-validity metric {100 * C['ui_per_ref_cycle_p99']:.0f} % UI per reference cycle.",
                  "",
                  f"Frequency error at the carrier (ramp {N.get('ramp', '?')}): peak {C['peak_hz'] / 1e3:.1f} kHz, RMS "
                  f"{C['rms_hz'] / 1e3:.1f} kHz, floor {C['floor_rms_hz'] / 1e3:.1f} kHz RMS, initial error after the "
                  f"flyback {C['initial_error_hz'] / 1e3:.1f} kHz settled in {C['settle_s'] * 1e9:.0f} ns.", "",
                  f"Range response from that curve alone: -3 dB width {N['width_3db_m'] * 100:.2f} cm "
                  f"(window alone {R['range_res_m'] * 100:.2f} cm), peak sidelobe {N['peak_sidelobe_db']:.1f} dB "
                  f"(window alone {R['window_sidelobe_db']:.1f} dB), ISLR {N['islr_db']:.1f} dB, beat phase "
                  f"perturbation {N['phase_rms_rad'] * 1e3:.1f} mrad RMS."]
        ghosts = N.get("ghosts") or []
        if ghosts:
            lines += ["", "Ghost targets of the chirp's frequency error (local maxima of that response beyond the "
                      "window's sidelobes; "
                      + ("the cycle-accurate engine vouches for them" if N.get("ghosts_vouched") else
                         "from a linearised curve: NOT vouched for, invariant #6") + "):", "",
                      "| offset from the target [m] | level [dBc] |", "|---:|---:|"]
            lines += [f"| {dr:+.2f} | {lvl:.1f} |" for dr, lvl in ghosts]
    return "\n".join(lines) + "\n"


def sources_markdown() -> str:
    lines = ["## Every sourced number", "", "| key | value | unit | source |", "|---|---:|---|---|"]
    for k, e in all_entries().items():
        lines.append(f"| {k} | {e.value} | {e.unit} | {e.source} |")
    return "\n".join(lines) + "\n"


def build(cfg: RadarConfig) -> dict:
    return report(cfg, run_statistical(cfg))


__all__ = ["report", "to_markdown", "sources_markdown", "build", "REPORT_OFFSETS_M"]

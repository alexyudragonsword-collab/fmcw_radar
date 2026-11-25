"""The radar's budget as a structured report: ``report`` (dict) and ``to_markdown``.

``tools/budget_report.py`` is the command line over these (d2d_link's
``report.py`` method).  Nothing here simulates beyond the statistical engine
(invariant #1: it reads the config and ``StatResult``); every number that
is not the config's own carries its source (invariant #5).
"""

from __future__ import annotations

from .config.schema import RadarConfig
from .engine.statistical import REPORT_OFFSETS_M, StatResult, hpf_map_shift_db, run_statistical
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
                   "angle_deg": cfg.target.angle_deg,
                   "rcs_dbsm": b.rcs_dbsm, "rcs_source": b.inputs["rcs_dbsm"][1], "beat_khz": st.beat_hz / 1e3,
                   "doppler_hz": st.doppler_hz, "range_bin": st.range_bin, "doppler_bin": st.doppler_bin,
                   "in_if_band": st.extras["in_if_band"]},
        "inputs": placeholders,
        "budget": [{"term": lab, "value": v, "unit": u} for lab, v, u in b.as_rows()],
        # the same rows with the EIRP held to the governing regulatory tier's limit (None where no rule applies)
        "budget_capped": (None if st.budget_capped is None
                          else [{"term": lab, "value": v, "unit": u} for lab, v, u in st.budget_capped.as_rows()]),
        "compliance": st.compliance,
        "detection": {"snr_cell_db": st.snr_cell_db, "snr_chirp_db": st.snr_chirp_db, "pfa": cfg.processing.cfar_pfa,
                      "pd": st.pd, "quant_share_db": b.quant_share_db,
                      # how far the target can be at Pd 0.9: by SNR, by the IF band, and which of the two limits (0.2.33)
                      "range_at_pd": st.extras.get("range_at_pd")},
        "phase_noise": {"lo_rms_rad": st.lo_rms_rad, "residual_rms_rad": st.pn_rms_rad,
                        # the levels are the beat signal's ahead of the IF high-pass; ``map_shift_db`` is what the filter adds
                        # on the map, the sideband and the target each passing it at their own beat (0 without it)
                        "floor": [{"offset_m": dr, "per_bin_dbc": v[0], "per_cell_dbc": v[1],
                                   "map_shift_db": (shift := hpf_map_shift_db(cfg, cfg.target.range_m + dr)),
                                   "per_cell_map_dbc": v[1] + shift} for dr, v in st.pn_floor.items()],
                        "local_cell_dbc": st.extras.get("pn_cell_local_dbc"), "mean_cell_dbc": st.extras.get("pn_cell_mean_dbc"),
                        "notes": list(st.extras.get("lo_notes") or []), "parked": st.extras.get("lo_parked")},
        "chirp": st.chirp, "nonlinearity": st.nonlinearity,
        "targets": st.targets, "angle": st.angle, "cfar": {**st.cfar, "range_pad": cfg.processing.range_pad},
        "leakage": None if st.leakage is None else {"rows": [{"term": lab, "value": v, "unit": u} for lab, v, u in st.leakage.as_rows()],
                                                     "adc_headroom_db": st.leakage.adc_headroom_db,
                                                     "p1db_margin_db": st.leakage.p1db_margin_db, "p1db_kind": st.leakage.p1db_kind,
                                                     "required_hpf_atten_db": st.leakage.required_hpf_atten_db,
                                                     "blank_recommended_s": st.leakage.blank_recommended_s,
                                                     "steady_clipping": st.leakage.steady_clipping,
                                                     "blank_s": st.leakage.blank_s},
    }
    return out


def _compliance_lines(K: dict) -> list:
    """The transmitter against 47 CFR 15.255(c)(2): which tier governs, the
    limit, by how much it is met or missed, the off-time -- every number
    with its source tag, and what the rule leaves open."""
    if not K:
        return []
    lines = ["", f"## Regulatory check ({K['rule']})", ""]
    if not K["applies"]:
        return lines + [f"Not applicable: {K['why']} (band: source: {K['sources']['band']})."]
    src = K["sources"]
    period = "not declared" if K["frame_period_s"] is None else f"{K['frame_period_s'] * 1e3:g} ms"
    lines += [f"Applies: {K['why']} (source: {src['band']}). Transmitter as configured: peak EIRP {K['eirp_dbm']:.1f} dBm = "
              f"conducted {K['conducted_dbm']:.1f} dBm ({K['tx_power_dbm']:g} dBm, source: {src['tx_power_dbm']}, backed off "
              f"{K['tx_backoff_db']:g} dB, source: {src['tx_backoff_db']}) + antenna (source: {src['tx_gain_dbi']})"
              + (f", {K['n_tx']} transmitters in turn (TDM): one on at a time" if K["n_tx"] > 1 else "")
              + f"; one frame is a {K['frame_on_s'] * 1e3:.2f} ms burst, frame period {period}; scenario "
              f"{K['scenario'] or 'not declared'}.", ""]
    if K["governing"] is None:
        return lines + ["No tier of the rule fits this configuration."]
    g = next(t for t in K["tiers"] if t["tier"] == K["governing"])
    lines += [f"Governing tier (the highest limit among those this configuration can use): **{g['label']}**, peak EIRP "
              f"{g['peak_eirp_limit_dbm']:g} dBm (source: {g['sources']['peak_eirp_dbm']})"
              + (f", peak conducted {g['conducted_limit_dbm']:g} dBm (source: {g['sources']['peak_conducted_dbm']})"
                 if g["conducted_limit_dbm"] is not None else "") + ".", "",
              f"**{K['verdict']}.**" + (f" Held to the limit the EIRP is {K['eirp_cap_dbm']:.1f} dBm and the cell SNR "
                                        f"{K['snr_cell_capped_db']:.2f} dB (configured: {K['snr_cell_configured_db']:.2f} dB)."
                                        if "snr_cell_capped_db" in K else ""), "",
              "| tier | band [GHz] | peak EIRP limit [dBm] | sweep inside | scenario | off-time | margin [dB] | min frame period [ms] | usable |",
              "|---|---|---:|---|---|---|---:|---:|---|"]
    for t in K["tiers"]:
        need = "" if t["off_time_required_s"] is None else f" (>= {t['off_time_required_s'] * 1e3:g} ms)"
        tmin = "" if t["min_frame_period_s"] is None else f"{t['min_frame_period_s'] * 1e3:.2f}"
        lines.append(f"| {t['label']} | {t['band_ghz'][0]:g}-{t['band_ghz'][1]:g} | {t['peak_eirp_limit_dbm']:g} | "
                     f"{'yes' if t['in_band'] else 'no'} | {t['scenario']} | {t['off_time']}{need} | {t['eirp_margin_db']:+.1f} | "
                     f"{tmin} | {'yes' if t['usable'] else 'no'} |")
    lines += ["", "Every limit, band edge and off-time figure above is `source: spec` (the rule's current text, through "
              "spec_sources). What the rule leaves open, and how it is read here:", ""]
    return lines + [f"- {r}" for r in K["readings"]]


def _parked_lines(K: dict | None, notes: list) -> list:
    """The LO while it is not ramping (lo.parked_lo): where the profile above stops being the answer."""
    if not K:
        return []
    lines = ["", "### The LO while it is not ramping", ""]
    if not K["known"]:
        return lines + ["The profile is read from a file, so its loop is not analysed here: nothing in this report says whether it "
                        "holds while the LO is parked (CW, or `chirp.idle_s` between ramps)."]

    def where(dz: bool, fcw: float) -> str:
        if dz:
            return f"FCW {fcw:g}, an integer: **in the dead zone**"
        return f"FCW {fcw:g}: not in the dead zone (" + ("fractional-N" if abs(fcw - round(fcw)) >= 1e-9 else "enough dither") + ")"

    idle = (f"between ramps (`chirp.idle_s` = {K['idle_s'] * 1e6:g} us, {100 * K['idle_fraction']:.1f} % of the PRI, at the ramp's start "
            f"frequency) {where(K['dead_zone_idle'], K['fcw_idle'])}" if K["idle_s"] > 0 else "no idle time between ramps in this config")
    lines += [f"The profile above is the loop's linear analysis. On the ramp the sweep carries the TDC across its bins every reference "
              f"cycle and the cycle-accurate engine agrees with it. Parked, an integer-N loop with under half a TDC bin of RMS dither at "
              f"the TDC ({K['dither_bins']:.2f} bin here) sits inside one bin and reads more in-band phase noise than this profile: "
              f"at the carrier (CW) {where(K['dead_zone_center'], K['fcw_center'])}; {idle}."
              + (" No number in this report describes the LO there." if K["dead_zone_center"] or (K["idle_s"] > 0 and K["dead_zone_idle"]) else "")]
    if notes:
        lines += ["", "The loop's own analysis notes:", ""] + [f"> {n}" for n in notes]
    return lines


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
             "## Link budget (radar equation)", ""]
    capped = rep.get("budget_capped")
    if capped:
        lines += ["| term | as configured | at the regulatory limit | unit |", "|---|---:|---:|---|"]
        for row, cap in zip(rep["budget"], capped):
            lines.append(f"| {row['term']} | {row['value']:.2f} | {cap['value']:.2f} | {row['unit']} |")
        lines += ["", "\"At the regulatory limit\": the EIRP is min(configured, the governing tier's limit below) and nothing else is "
                  "changed."]
    else:
        lines += ["| term | value | unit |", "|---|---:|---|"]
        for row in rep["budget"]:
            lines.append(f"| {row['term']} | {row['value']:.2f} | {row['unit']} |")
    lines += ["", f"Detection: cell SNR {D['snr_cell_db']:.1f} dB -> Pd {D['pd']:.4f} at Pfa {D['pfa']:g} "
              f"(Swerling 0, known noise level; the ADC adds {D['quant_share_db']:.2f} dB to the thermal floor).", "",
              "## Inputs and their sources", "", "| input | value | source |", "|---|---:|---|"]
    for k, v in rep["inputs"].items():
        lines.append(f"| {k} | {v['value']:.4g} | {v['source']} |")
    lines += _compliance_lines(rep.get("compliance") or {})
    P = rep["phase_noise"]
    filtered = any(row.get("map_shift_db") for row in P["floor"])
    lines += ["", "## LO phase noise after range correlation", "",
              f"LO {P['lo_rms_rad'] * 1e3:.1f} mrad RMS over [1/T_c, IF]; what the beat sees after the round trip "
              f"{P['residual_rms_rad'] * 1e3:.2f} mrad RMS. Sidelobe floor around the target:", "",
              "| offset [m] | per range bin, one chirp [dBc] | per range-Doppler cell [dBc] |"
              + (" on the map, behind the IF high-pass [dBc] |" if filtered else ""), "|---:|---:|---:|" + ("---:|" if filtered else "")]
    for row in P["floor"]:
        lines.append(f"| {row['offset_m']:g} | {row['per_bin_dbc']:.1f} | {row['per_cell_dbc']:.1f} |"
                     + (f" {row['per_cell_map_dbc']:.1f} |" if filtered else ""))
    if filtered:
        lines += ["", "The levels in dBc are the beat signal's ahead of the IF high-pass. On the map a line and the target have each "
                  "passed the filter at their own beat, so a line farther out than the target stands higher against its peak and a "
                  "nearer one lower; the last column is that."]
    lines += _parked_lines(P.get("parked"), P.get("notes") or [])
    C, N = rep["chirp"], rep["nonlinearity"]
    if C:
        lines += ["", "## Chirp linearity (from the vendored ADPLL loop)", "",
                  f"Engine `{C['engine']}`{' (cycle-accurate: may vouch for spurs)' if C.get('vouches_for_spurs') else ' (linearised: cannot vouch for spurs)'}; "
                  f"direct-path gain used {C['dp_gain_used']:.5f}"
                  + (f" after offline passes eps = {', '.join(f'{e:.2e}' for e in C['dp_cal_passes'])}" if C.get('dp_cal_passes') else "")
                  + f"; the ramp advances the phase {100 * C['ui_per_ref_cycle_p99']:.0f} % of a UI per reference cycle (a description, "
                  f"not a limit: the TDC spans the DCO period) and takes the DCO {100 * C.get('dco_dev_frac_p99', 0.0):.1f} % off its centre "
                  "(the TDC reads the fraction of a cycle against the nominal period, so each reading is off by that share of it).",
                  "",
                  f"Frequency error at the carrier (ramp {N.get('ramp', '?')}): peak {C['peak_hz'] / 1e3:.1f} kHz, RMS "
                  f"{C['rms_hz'] / 1e3:.1f} kHz, floor {C['floor_rms_hz'] / 1e3:.1f} kHz RMS, initial error after the "
                  f"flyback {C['initial_error_hz'] / 1e3:.1f} kHz settled in {C['settle_s'] * 1e9:.0f} ns.", "",
                  f"Range response from that curve alone: -3 dB width {N['width_3db_m'] * 100:.2f} cm "
                  f"(window alone {R['range_res_m'] * 100:.2f} cm), peak sidelobe {N['peak_sidelobe_db']:.1f} dB "
                  f"(window alone {R['window_sidelobe_db']:.1f} dB), ISLR {N['islr_db']:.1f} dB, beat phase "
                  f"perturbation {N['phase_rms_rad'] * 1e3:.1f} mrad RMS."]
        ghosts = N.get("ghosts") or []
        quiet = N.get("ghosts_quiet") or []
        if "ghost_chirps" in N:
            dith = N.get("tdc_dither_lsb", 0.0)
            how = (f"TDC jitter {N['tdc_jitter_s'] * 1e12:g} ps RMS on a {N['tdc_res_s'] * 1e12:g} ps TDC, dithering its quantisation"
                   + (f", and {dith:g} LSB of subtractive TDC dither" if dith else ""))
            noise_on = N.get("ghost_noise_on", True)
            lines += ["", f"Ghost targets: what of the chirp's error stays coherent over {N['ghost_chirps']} ramps with the loop's noise "
                      + ("on " if noise_on else "off (the LO's noise is a file's; the subtractive dither is the loop's and stays on) ")
                      + f"({how}; the cycle-accurate engine vouches for them). A spur under about {N['ghost_limit_dbc']:.0f} dBc "
                      f"cannot be told from the LO's noise in that many ramps."
                      + (f" Undithered (the noise-off curve{', the dither off' if dith else ''}) the strongest is "
                         f"{quiet[0][1]:.1f} dBc at {quiet[0][0]:+.2f} m." if quiet else "")
                      + ("" if ghosts else " None found.")]
        elif ghosts and N.get("ghosts_vouched"):
            lines += ["", "Ghost targets of the chirp's frequency error: the undithered pattern of the cycle-accurate curve. The LO's "
                      "noise is a file's here, so the chirp generator runs with its own noise off and nothing is known to dither "
                      "its TDC; with the loop's own noise (no `lo.profile`) the frame's coherent spurs are what is listed instead:"]
        elif ghosts:
            lines += ["", "Ghost targets of the chirp's frequency error (local maxima of that response beyond the "
                      "window's sidelobes; from a linearised curve: NOT vouched for, invariant #6):"]
        if ghosts:
            lines += ["", "| offset from the target [m] | level [dBc] |", "|---:|---:|"]
            lines += [f"| {dr:+.2f} | {lvl:.1f} |" for dr, lvl in ghosts]
        if C.get("notes"):
            lines += ["", "The loop's own notes on this chirp run:", ""] + [f"> {n}" for n in C["notes"]]
    T2 = rep.get("targets") or []
    if len(T2) > 1:
        lines += ["", "## Targets (milestone 2)", "",
                  "| # | kind | range [m] | velocity [m/s] | angle [deg] | RCS [dBsm] | cell SNR [dB] | Pd | strongest other's skirt here [dBc] | by | masked |",
                  "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for i, t in enumerate(T2):
            lines.append(f"| {i} | {t['kind']} | {t['range_m']:g} | {t['velocity_mps']:+g} | {t['angle_deg']:g} | {t['rcs_dbsm']:g} | "
                         f"{t['snr_cell_db']:.1f} | {t['pd']:.4f} | "
                         + (f"{t['interference_dbc']:.1f} | {t['interference_kind']} (#{t['interferer']}) | {'yes' if t['masked'] else 'no'} |"
                            if t["interferer"] is not None else "- | - | no |"))
    A = rep.get("angle") or {}
    if A:
        lines += ["", "## Angle (TDM-MIMO virtual array)", "",
                  f"{A['n_virtual']} virtual elements ({'a filled line' if A['filled'] else 'not a filled line'}), aperture "
                  f"{A['aperture_m'] * 1e3:.1f} mm; beamwidth {A['beamwidth_deg']:.2f} deg at the target's {rep['target'].get('angle_deg', 0):g} deg; "
                  f"Cramer-Rao bound {A['crlb_sigma_deg']:.3f} deg RMS at {A['snr_element_db']:.1f} dB per element; estimate "
                  f"{A['theta_est_deg']:+.3f} deg (sidelobe {A['peak_sidelobe_db']:.1f} dB).", "",
                  *([f"Expected scatter of this estimator {A['sigma_expected_deg']:.3f} deg RMS = the bound x "
                     f"{A['factor_element_pattern']:.3f} (element pattern) x {A['factor_scalloping']:.3f} (range / Doppler cell scalloping) x "
                     f"{A['factor_angle_window']:.3f} (angle window against uniform weights) x {A['factor_doppler_estimate']:.3f} "
                     f"(the TDM compensation's Doppler estimate); per-element cell SNR as processed {A['snr_element_cell_db']:.1f} dB.", ""]
                    if "sigma_expected_deg" in A else []),
                  f"Biases: RX mutual coupling ({A['coupling_source']}"
                  + (f", {A['coupling_max_offdiag_db']:.1f} dB adjacent" if A['coupling_max_offdiag_db'] is not None else "")
                  + f", {'calibrated' if A['coupling_calibrated'] else 'uncalibrated'}) {A['coupling_bias_deg']:+.3f} deg; the TDM Doppler phase "
                  f"would give {A['tdm_bias_uncompensated_deg']:+.3f} deg uncompensated. Unambiguous velocity under TDM "
                  f"+-{A['max_velocity_mps']:.2f} m/s.", "",
                  f"The sweep: the edge virtual element's beat sits {A['edge_shift_bins']:.3f} range bins off (window taper "
                  f"{A['edge_taper_db']:.3f} dB); a phase-shifter-steered TX beam aligned at f_c would squint "
                  f"{A['tx_beam_squint_deg'][0]:+.2f} / {A['tx_beam_squint_deg'][1]:+.2f} deg at the sweep's edges "
                  f"(FR2 400 MHz: {A['fr2_400mhz_squint_deg'][0]:+.2f} / {A['fr2_400mhz_squint_deg'][1]:+.2f} deg)."]
    CF = rep.get("cfar") or {}
    if CF:
        lines += ["", "## CA-CFAR on this map", "",
                  f"{CF['n_train']} training cells are worth {CF['n_train_eff']:.1f} independent ones (the range window and x{CF['range_pad']} "
                  f"padding span {CF['correlation_length_range']:.1f} padded cells per look, the Doppler window {CF['correlation_length_doppler']:.1f}); "
                  f"the guard is {CF['guard_bins_range']:g} range bins / {CF['guard_bins_doppler']:g} Doppler bins, and the training cells' mean "
                  f"power correlation with the cell under test is {CF['cut_correlation']:.4f}.", "",
                  f"Design Pfa {CF['pfa_design']:g} -> per cell {CF['pfa_cell']:.3g} (exact; the noisier threshold alone would give "
                  f"{CF['pfa_training_only']:.2g}, the test cell lifting its own threshold alone {CF['pfa_cut_only']:.2g}). "
                  f"A noise-only frame: {CF['cells_in_band']} cells in the IF band = {CF['independent_looks']:.0f} independent looks, "
                  f"{CF['false_alarm_cells_per_frame']:.1f} false-alarm cells expected.", "",
                  (f"The map is a sum of {CF['n_looks']} looks: threshold factor {CF['threshold_factor']:.2f} "
                   f"(the single-look factor would cost {CF['single_look_factor_penalty_db']:.1f} dB). " if CF.get("n_looks", 1) > 1 else "")
                  + f"The target at {CF['snr_look_db']:.1f} dB per look: Pd {CF['pd_target']:.3f}; a Pd of 0.9 takes {CF['snr_pd90_db']:.2f} dB per look"
                  + (f" (CFAR loss {CF['cfar_loss_db']:.2f} dB, the target's own leak into its training cells included)" if "cfar_loss_db" in CF else "")
                  + f". The chirp's ghost targets add {CF['ghost_detections_per_frame']:.2f} detections per frame"
                  + ("" if CF.get("ghosts_vouched") or not CF.get("ghosts") else " (not vouched: linearised chirp engine)") + "."]
        RP = D.get("range_at_pd")
        if RP:
            lines += ["", f"How far at Pd {RP['pd']:g}: the SNR of one look falls to the {RP['snr_required_db']:.2f} dB the CA-CFAR needs at "
                      + (f"{RP['snr_limited_range_m']:.2f} m" if RP["snr_limited_range_m"] > 0.0 else "no range (it is under it from the nearest range on)")
                      + f"; the IF band holds targets out to {RP['if_band_range_m']:.2f} m. The radar reaches **{RP['range_m']:.2f} m**, limited by "
                      + ("the IF band (past it the echo is filtered out whatever its SNR)" if RP["limited_by"] == "if_band" else "the SNR")
                      + ". The SNR here is the link budget's as the target moves out (the radar equation, the oxygen, the IF high-pass at "
                      "each range's beat); not in it: " + ", ".join(RP["not_included"]) + "."]
        if CF.get("ghosts"):
            lines += ["", "| ghost at [m] | level [dBc] | on the map [dBc] | floor where it sits [dBc] | SNR [dB] | Pd | in view |",
                      "|---:|---:|---:|---:|---:|---:|---|"]
            lines += [f"| {g['range_m']:.2f} | {g['level_dbc']:.1f} | {g['level_map_dbc']:.1f} | {g['floor_dbc']:.1f} | {g['snr_db']:.1f} | "
                      f"{g['pd']:.3f} | {'yes' if g['in_view'] else 'no'} |" for g in CF["ghosts"]]
            lines += ["", "A ghost's SNR is its level on the map (behind the IF high-pass, where one is on) over the floor where it sits: "
                      "the target's own floor moved to the ghost's beat, plus the target's LO-noise sideband at the ghost's offset."]
    LK = rep.get("leakage")
    if LK:
        lines += ["", "## TX-RX leakage", "", "| term | value | unit |", "|---|---:|---|"]
        lines += [f"| {row['term']} | {row['value']:.2f} | {row['unit']} |" for row in LK["rows"]]
    return "\n".join(lines) + "\n"


def sources_markdown() -> str:
    lines = ["## Every sourced number", "", "| key | value | unit | source |", "|---|---:|---|---|"]
    for k, e in all_entries().items():
        lines.append(f"| {k} | {e.value} | {e.unit} | {e.source} |")
    return "\n".join(lines) + "\n"


def build(cfg: RadarConfig) -> dict:
    return report(cfg, run_statistical(cfg))


__all__ = ["report", "to_markdown", "sources_markdown", "build", "REPORT_OFFSETS_M"]

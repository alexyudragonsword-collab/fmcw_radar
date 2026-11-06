"""Form-field declarations for the GUI that is not built yet (d2d_link
``config/form.py`` / Halo_Serdes ``config_bridge.SECTIONS`` method).

Milestone 1 ships no GUI and no Android app; what it ships is this
declaration, so the config layer already says what a form would show: every
``RadarConfig`` field, by dotted path, with a label, a kind and (where the
config stores SI units) a display scale.  ``tests/test_config.py`` keeps
``SECTIONS`` and the schema's field inventory identical in both directions,
so a new config field cannot appear without its form row and a form row
cannot outlive its field.  The GUI, when it comes, reads the config through
this and adds no simulation logic (invariant #1).
"""

from __future__ import annotations

import dataclasses
import typing

from .schema import RadarConfig


def _f(path: str, label: str, kind: str, **kw) -> dict:
    """One form field: dotted path, label, kind (bool | enum | float | int |
    opt_float | opt_int | opt_str), plus ``options`` for enums and ``scale``
    for display units."""
    d = {"path": path, "label": label, "kind": kind}
    d.update(kw)
    return d


SECTIONS: list[tuple[str, str, list[dict]]] = [
    ("band", "Band", [
        _f("band.kind", "Band preset", "enum", options=["60g_sensing", "77g_automotive"]),
        _f("band.center_hz", "Sweep centre [GHz]", "float", scale=1e9),
        _f("band.sweep_hz", "Sweep bandwidth B [GHz]", "float", scale=1e9),
    ]),
    ("chirp", "Chirp", [
        _f("chirp.shape", "Shape", "enum", options=["sawtooth"]),
        _f("chirp.duration_s", "Ramp duration [us]", "float", scale=1e-6),
        _f("chirp.idle_s", "Idle between ramps [us]", "float", scale=1e-6),
        _f("chirp.n_chirps", "Chirps per frame", "int"),
    ]),
    ("lo", "LO (ADPLL x N)", [
        _f("lo.mult", "Multiplier N (empty = placeholder, source: assumed)", "opt_int"),
        _f("lo.fref_hz", "Reference [MHz]", "float", scale=1e6),
        _f("lo.loop_bw_hz", "Loop bandwidth [MHz]", "float", scale=1e6),
        _f("lo.phase_margin_deg", "Phase margin [deg]", "float"),
        _f("lo.kdco_hz", "Kdco [kHz/LSB]", "float", scale=1e3),
        _f("lo.dco_pn_dbchz", "DCO spot phase noise [dBc/Hz] (empty = placeholder)", "opt_float"),
        _f("lo.dco_pn_offset_hz", "... at offset [MHz]", "float", scale=1e6),
        _f("lo.dco_pn_f1f3_hz", "1/f^3 corner [kHz]", "float", scale=1e3),
        _f("lo.dco_pn_floor_dbchz", "DCO floor [dBc/Hz] (empty = placeholder)", "opt_float"),
        _f("lo.ref_pn_dbchz", "Reference floor [dBc/Hz]", "float"),
        _f("lo.tdc_res_s", "TDC resolution [ps] (empty = placeholder)", "opt_float", scale=1e-12),
        _f("lo.dp_gain", "Direct-path gain as built (1 + eps)", "float"),
        _f("lo.dp_cal", "Two-point gain calibration", "enum", options=["none", "offline", "online"]),
        _f("lo.dp_cal_iterations", "Offline passes", "int"),
        _f("lo.dp_cal_mu", "Online LMS gain [1/UI]", "float"),
        _f("lo.dp_cal_window_cycles", "Online window after the flyback [cycles]", "int"),
        _f("lo.settle_cycles", "Settle cycles before the first chirp", "int"),
        _f("lo.engine", "Chirp engine", "enum", options=["event", "response", "ideal"]),
        _f("lo.profile", "Clock profile file (empty = the ADPLL's own analysis)", "opt_str"),
        _f("lo.profile_shift_db", "Profile shift [dB]", "float"),
    ]),
    ("frontend", "Front end (placeholders until mmw60_trx)", [
        _f("frontend.tx_power_dbm", "TX power [dBm] (empty = placeholder)", "opt_float"),
        _f("frontend.tx_gain_dbi", "TX antenna gain [dBi]", "opt_float"),
        _f("frontend.rx_gain_dbi", "RX antenna gain [dBi]", "opt_float"),
        _f("frontend.rx_gain_db", "RX chain gain to the ADC [dB]", "opt_float"),
        _f("frontend.nf_db", "Noise figure [dB]", "opt_float"),
        _f("frontend.p1db_dbm", "Input P1dB [dBm]", "opt_float"),
    ]),
    ("channel", "Channel", [
        _f("channel.oxygen_db_per_km", "Oxygen attenuation [dB/km] (empty = survey)", "opt_float"),
        _f("channel.extra_loss_db", "Extra two-way loss [dB]", "float"),
    ]),
    ("target", "Target", [
        _f("target.kind", "Kind", "enum", options=["human", "car", "corner_reflector", "custom"]),
        _f("target.range_m", "Range [m]", "float"),
        _f("target.velocity_mps", "Radial velocity [m/s] (positive receding)", "float"),
        _f("target.angle_deg", "Angle [deg] (milestone 2)", "float"),
        _f("target.rcs_dbsm", "RCS [dBsm] (empty = survey value for the kind)", "opt_float"),
    ]),
    ("rx", "Receiver", [
        _f("rx.if_bw_hz", "IF bandwidth [MHz]", "float", scale=1e6),
        _f("rx.adc_fs_hz", "ADC sample rate [MS/s]", "float", scale=1e6),
        _f("rx.adc_bits", "ADC bits", "int"),
        _f("rx.adc_fullscale_dbm", "ADC full scale [dBm]", "float"),
    ]),
    ("processing", "Processing", [
        _f("processing.window_range", "Range window", "enum", options=["rect", "hann", "hamming", "blackman"]),
        _f("processing.window_doppler", "Doppler window", "enum", options=["rect", "hann", "hamming", "blackman"]),
        _f("processing.range_pad", "Range FFT zero-padding factor", "int"),
        _f("processing.doppler_pad", "Doppler FFT zero-padding factor", "int"),
        _f("processing.cfar_guard", "CFAR guard cells", "int"),
        _f("processing.cfar_train", "CFAR training cells", "int"),
        _f("processing.cfar_pfa", "CFAR false-alarm probability", "float"),
    ]),
    ("sim", "Simulation", [
        _f("sim.seed", "Seed", "int"),
        _f("sim.engine", "Engine", "enum", options=["statistical", "time", "both"]),
        _f("sim.time_osr", "Time engine: envelope oversampling of the sweep", "float"),
        _f("sim.time_n_chirps", "Time engine: chirps synthesised (empty = all)", "opt_int"),
        _f("sim.pn_bins_per_decade", "Closed-form grid density", "int"),
    ]),
]


def form_paths() -> list[str]:
    return [f["path"] for _, _, fields in SECTIONS for f in fields]


def schema_paths(cls: type = RadarConfig, prefix: str = "") -> list[str]:
    """Every leaf field of the config as a dotted path."""
    out = []
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        tp = hints[f.name]
        if typing.get_origin(tp) is typing.Union:
            args = [a for a in typing.get_args(tp) if a is not type(None)]
            tp = args[0] if len(args) == 1 else tp
        if dataclasses.is_dataclass(tp):
            out.extend(schema_paths(tp, prefix + f.name + "."))
        else:
            out.append(prefix + f.name)
    return out


__all__ = ["SECTIONS", "form_paths", "schema_paths"]

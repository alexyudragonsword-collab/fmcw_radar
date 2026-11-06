"""Single-source-of-truth configuration schema (invariant #1).

Band, sweep, chirp timing, the LO's ADPLL, the front end, the receiver, the
processing chain and the target all live here, in one frozen ``RadarConfig``;
examples, tools and the future GUI only read it.  The dataclasses are frozen:
derive variants with ``dataclasses.replace`` or ``loader.apply_overrides``.
Every field is validated at construction so a bad value fails here with its
name, not deep inside an engine as a NaN.

Numbers that are not the user's design decision are *not* hard-coded here:
the ``FrontEndConfig`` fields, the LO's noise figures, the oxygen attenuation
and the target's RCS default to ``None``, which means "the entry in
``src/fmcw_radar/data/sources.yaml`` for this band" (invariant #5: every such
number carries its ``source``).  Setting a field overrides it and is then the
config's own claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

SCHEMA_VERSION = 1
C0 = 299_792_458.0
K_BOLTZMANN = 1.380649e-23
T0_K = 290.0

#: the band presets: the window the centre frequency and sweep must stay in,
#: and the key prefix of the front-end placeholders in sources.yaml
BANDS: dict[str, tuple[float, float]] = {"60g_sensing": (57.0e9, 64.0e9), "77g_automotive": (76.0e9, 81.0e9)}
WINDOWS = ("rect", "hann", "hamming", "blackman")


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _require_in(value, allowed, name: str) -> None:
    _require(value in allowed, f"{name} must be one of {sorted(allowed)}, got {value!r}")


def _finite_nonneg(value: float, name: str) -> None:
    _require(math.isfinite(value) and value >= 0.0, f"{name} must be finite and >= 0, got {value!r}")


def _finite_pos(value: float, name: str) -> None:
    _require(math.isfinite(value) and value > 0.0, f"{name} must be finite and > 0, got {value!r}")


def _finite(value: float, name: str) -> None:
    _require(math.isfinite(value), f"{name} must be finite, got {value!r}")


# ---------------------------------------------------------------------------
# band and chirp
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BandConfig:
    """Where the sweep sits.  ``kind`` picks the allowed window and the
    front-end placeholder set; centre and sweep are the design's own."""

    kind: Literal["60g_sensing", "77g_automotive"] = "60g_sensing"
    center_hz: float = 60.0e9           # sweep centre [Hz]
    sweep_hz: float = 4.0e9             # sweep bandwidth B [Hz] (up to 7 GHz in the 60 GHz band)

    def __post_init__(self):
        _require_in(self.kind, set(BANDS), "band.kind")
        _finite_pos(self.center_hz, "band.center_hz")
        _finite_pos(self.sweep_hz, "band.sweep_hz")
        lo, hi = BANDS[self.kind]
        _require(lo <= self.center_hz - 0.5 * self.sweep_hz and self.center_hz + 0.5 * self.sweep_hz <= hi,
                 f"band: the sweep {self.start_hz / 1e9:.3f}-{self.stop_hz / 1e9:.3f} GHz leaves the "
                 f"{self.kind} window {lo / 1e9:g}-{hi / 1e9:g} GHz")

    @property
    def start_hz(self) -> float:
        return self.center_hz - 0.5 * self.sweep_hz

    @property
    def stop_hz(self) -> float:
        return self.center_hz + 0.5 * self.sweep_hz

    @property
    def wavelength_m(self) -> float:
        return C0 / self.center_hz


@dataclass(frozen=True)
class ChirpConfig:
    """A sawtooth chirp train: ``n_chirps`` up-ramps of ``duration_s`` each,
    ``idle_s`` of flyback between them (the LO sits at the start frequency)."""

    shape: Literal["sawtooth"] = "sawtooth"
    duration_s: float = 100.0e-6        # T_c, the ramp [s]
    idle_s: float = 0.0                 # flyback / idle between ramps [s]
    n_chirps: int = 64                  # chirps per frame (the Doppler FFT length)

    def __post_init__(self):
        _require_in(self.shape, {"sawtooth"}, "chirp.shape")
        _finite_pos(self.duration_s, "chirp.duration_s")
        _finite_nonneg(self.idle_s, "chirp.idle_s")
        _require(self.n_chirps >= 1, f"chirp.n_chirps must be >= 1, got {self.n_chirps}")

    @property
    def pri_s(self) -> float:
        """Pulse repetition interval: ramp plus idle."""
        return self.duration_s + self.idle_s


# ---------------------------------------------------------------------------
# the LO: a vendored ADPLL behind a multiplier (invariants #2 and #4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LOConfig:
    """The chirp generator: polar_tx's two-point ADPLL (TDC mode, Staszewski)
    at ``center_hz / mult``, fed the frequency ramp at both injection points,
    behind an ideal ``mult`` multiplier (phase x mult, phase noise +20 log mult).
    ``None`` fields take the band's placeholder from sources.yaml (source:
    assumed).  The transmit and receive mixers share this one LO: there is no
    field for a receive-side oscillator on purpose (invariant #2).

    ``engine`` picks how the chirp's frequency error is produced:
    ``event`` -- the cycle-accurate vendored loop (loop settling at the
    flyback, two-point gain mismatch, TDC and DCO quantisation, the noise
    truth; the only engine a spur claim may come from, invariant #6);
    ``response`` -- the linearised z-domain composite (fast; cannot show
    quantisation, cannot vouch for spurs); ``ideal`` -- no error at all (the
    reference the resolution acceptance is measured against).
    """

    mult: Optional[int] = None          # LO multiplier N; None -> placeholder
    fref_hz: float = 100.0e6            # reference clock [Hz]
    loop_bw_hz: float = 1.0e6           # unity-gain bandwidth of the loop [Hz]
    phase_margin_deg: float = 60.0
    kdco_hz: float = 50.0e3             # DCO gain [Hz/LSB]
    dco_pn_dbchz: Optional[float] = None        # DCO spot phase noise at pn_offset_hz [dBc/Hz]; None -> placeholder
    dco_pn_offset_hz: float = 1.0e6
    dco_pn_f1f3_hz: float = 300.0e3     # 1/f^3 corner [Hz]
    dco_pn_floor_dbchz: Optional[float] = None  # None -> placeholder
    ref_pn_dbchz: float = -155.0        # reference floor [dBc/Hz]
    tdc_res_s: Optional[float] = None   # TDC resolution [s]; None -> placeholder
    dp_gain: float = 1.0                # direct-path gain as built: 1 + eps is a two-point mismatch of eps
    dp_cal: Literal["none", "offline", "online"] = "offline"   # two-point gain calibration (chirp linearity)
    dp_cal_iterations: int = 2          # offline: least-squares passes, one chirp each
    dp_cal_mu: float = 1.0e-4           # online: sign-sign step per reference cycle
    settle_cycles: int = 40_000         # event engine: cycles before the first chirp
    engine: Literal["event", "response", "ideal"] = "event"
    profile: Optional[str] = None       # a pll_simulator clock profile (YAML) for the LO phase noise instead of
                                        # the vendored ADPLL's own analysis; scaled by (center / mult / f0)^2 to the DCO
    profile_shift_db: float = 0.0       # uniform dB shift of that profile

    def __post_init__(self):
        if self.mult is not None:
            _require(int(self.mult) >= 1, f"lo.mult must be >= 1, got {self.mult}")
        _finite_pos(self.fref_hz, "lo.fref_hz")
        _finite_pos(self.loop_bw_hz, "lo.loop_bw_hz")
        _require(self.loop_bw_hz <= self.fref_hz / 6.0, "lo.loop_bw_hz must be <= fref / 6 (no stable PI set above)")
        _require(0.0 < self.phase_margin_deg < 90.0, "lo.phase_margin_deg must be in (0, 90)")
        _finite_pos(self.kdco_hz, "lo.kdco_hz")
        for name in ("dco_pn_dbchz", "dco_pn_floor_dbchz"):
            v = getattr(self, name)
            if v is not None:
                _finite(v, f"lo.{name}")
        _finite_pos(self.dco_pn_offset_hz, "lo.dco_pn_offset_hz")
        _finite_pos(self.dco_pn_f1f3_hz, "lo.dco_pn_f1f3_hz")
        _finite(self.ref_pn_dbchz, "lo.ref_pn_dbchz")
        if self.tdc_res_s is not None:
            _finite_pos(self.tdc_res_s, "lo.tdc_res_s")
        _finite_pos(self.dp_gain, "lo.dp_gain")
        _require_in(self.dp_cal, {"none", "offline", "online"}, "lo.dp_cal")
        _require(self.dp_cal_iterations >= 1, "lo.dp_cal_iterations must be >= 1")
        _finite_pos(self.dp_cal_mu, "lo.dp_cal_mu")
        _require(self.settle_cycles >= 1000, "lo.settle_cycles must be >= 1000 (the loop has to lock first)")
        _require_in(self.engine, {"event", "response", "ideal"}, "lo.engine")
        _finite(self.profile_shift_db, "lo.profile_shift_db")


# ---------------------------------------------------------------------------
# front end, channel, target
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontEndConfig:
    """The analytic front-end placeholder (one number each, source: assumed)
    standing in for mmw60_trx's PA / LNA / array / package objects.  Every
    ``None`` takes the band's entry from sources.yaml; a set value is the
    config's own claim."""

    tx_power_dbm: Optional[float] = None
    tx_gain_dbi: Optional[float] = None
    rx_gain_dbi: Optional[float] = None
    rx_gain_db: Optional[float] = None      # LNA + mixer + IF gain to the ADC [dB]
    nf_db: Optional[float] = None
    p1db_dbm: Optional[float] = None        # input-referred 1 dB compression [dBm]

    def __post_init__(self):
        for name in ("tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "rx_gain_db", "nf_db", "p1db_dbm"):
            v = getattr(self, name)
            if v is not None:
                _finite(v, f"frontend.{name}")


@dataclass(frozen=True)
class ChannelConfig:
    """Free space plus atmospheric oxygen plus a point target; nothing else
    (no multipath, no clutter).  ``oxygen_db_per_km`` None -> the band's
    survey value (ITU-R P.676, unverified)."""

    oxygen_db_per_km: Optional[float] = None
    extra_loss_db: float = 0.0              # radome, cabling: a flat two-way loss [dB]

    def __post_init__(self):
        if self.oxygen_db_per_km is not None:
            _finite_nonneg(self.oxygen_db_per_km, "channel.oxygen_db_per_km")
        _finite_nonneg(self.extra_loss_db, "channel.extra_loss_db")


@dataclass(frozen=True)
class TargetConfig:
    """One point target (invariant #5: an input, not a model).  ``rcs_dbsm``
    None -> the survey value for ``kind`` (``rcs.<kind>_dbsm``)."""

    kind: Literal["human", "car", "corner_reflector", "custom"] = "human"
    range_m: float = 5.0
    velocity_mps: float = 2.0           # radial, positive receding
    angle_deg: float = 0.0              # declared for milestone 2 (MIMO); unused by the single-channel engines
    rcs_dbsm: Optional[float] = None

    def __post_init__(self):
        _require_in(self.kind, {"human", "car", "corner_reflector", "custom"}, "target.kind")
        _finite_pos(self.range_m, "target.range_m")
        _finite(self.velocity_mps, "target.velocity_mps")
        _finite(self.angle_deg, "target.angle_deg")
        if self.rcs_dbsm is not None:
            _finite(self.rcs_dbsm, "target.rcs_dbsm")
        _require(self.kind != "custom" or self.rcs_dbsm is not None, "target.kind 'custom' needs target.rcs_dbsm")


# ---------------------------------------------------------------------------
# receiver, processing, simulation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RxConfig:
    """The beat path: a brick-wall IF (anti-alias) filter of ``if_bw_hz`` and
    a complex (I/Q) ADC at ``adc_fs_hz`` with ``adc_bits`` over the full
    scale ``adc_fullscale_dbm`` (a full-scale sine's power into 50 ohm)."""

    if_bw_hz: float = 4.0e6             # one-sided beat bandwidth [Hz]
    adc_fs_hz: float = 10.0e6           # complex sample rate [Hz]
    adc_bits: int = 12
    adc_fullscale_dbm: float = 4.0      # 1 Vpp into 50 ohm

    def __post_init__(self):
        _finite_pos(self.if_bw_hz, "rx.if_bw_hz")
        _finite_pos(self.adc_fs_hz, "rx.adc_fs_hz")
        _require(self.if_bw_hz <= 0.5 * self.adc_fs_hz, "rx.if_bw_hz must be <= adc_fs_hz / 2 (anti-alias)")
        _require(1 <= self.adc_bits <= 24, f"rx.adc_bits must be in 1..24, got {self.adc_bits}")
        _finite(self.adc_fullscale_dbm, "rx.adc_fullscale_dbm")


@dataclass(frozen=True)
class ProcessingConfig:
    """Window + range FFT + Doppler FFT + a cell-averaging CFAR."""

    window_range: Literal["rect", "hann", "hamming", "blackman"] = "hann"
    window_doppler: Literal["rect", "hann", "hamming", "blackman"] = "hann"
    range_pad: int = 4                  # zero-padding factor of the range FFT (profile interpolation)
    doppler_pad: int = 1
    cfar_guard: int = 2                 # guard cells each side (range dimension)
    cfar_train: int = 8                 # training cells each side
    cfar_pfa: float = 1.0e-4

    def __post_init__(self):
        _require_in(self.window_range, set(WINDOWS), "processing.window_range")
        _require_in(self.window_doppler, set(WINDOWS), "processing.window_doppler")
        _require(self.range_pad >= 1 and self.doppler_pad >= 1, "processing pad factors must be >= 1")
        _require(self.cfar_guard >= 0 and self.cfar_train >= 1, "processing.cfar_guard >= 0, cfar_train >= 1")
        _require(0.0 < self.cfar_pfa < 1.0, f"processing.cfar_pfa must be in (0, 1), got {self.cfar_pfa!r}")


@dataclass(frozen=True)
class SimConfig:
    seed: int = 1
    engine: Literal["statistical", "time", "both"] = "statistical"
    time_osr: float = 1.25              # time engine: waveform sample rate = time_osr x sweep (complex envelope)
    time_n_chirps: Optional[int] = None  # time engine: chirps actually synthesised (None = all)
    pn_bins_per_decade: int = 60        # grid density of the closed-form residual integrals

    def __post_init__(self):
        _require_in(self.engine, {"statistical", "time", "both"}, "sim.engine")
        _require(self.time_osr >= 1.0, "sim.time_osr must be >= 1 (the envelope must hold the sweep)")
        if self.time_n_chirps is not None:
            _require(self.time_n_chirps >= 1, "sim.time_n_chirps must be >= 1")
        _require(self.pn_bins_per_decade >= 10, "sim.pn_bins_per_decade must be >= 10")


# ---------------------------------------------------------------------------
# the radar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RadarConfig:
    band: BandConfig = field(default_factory=BandConfig)
    chirp: ChirpConfig = field(default_factory=ChirpConfig)
    lo: LOConfig = field(default_factory=LOConfig)
    frontend: FrontEndConfig = field(default_factory=FrontEndConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    rx: RxConfig = field(default_factory=RxConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    sim: SimConfig = field(default_factory=SimConfig)

    def __post_init__(self):
        n = self.chirp.duration_s * self.rx.adc_fs_hz
        _require(abs(n - round(n)) < 1e-6 and round(n) >= 16,
                 f"chirp.duration_s x rx.adc_fs_hz = {n:g} must be a whole number of samples >= 16")
        n_ref = self.chirp.duration_s * self.lo.fref_hz
        _require(abs(n_ref - round(n_ref)) < 1e-6, f"chirp.duration_s x lo.fref_hz = {n_ref:g} must be a whole number")
        n_idle = self.chirp.idle_s * self.lo.fref_hz
        _require(abs(n_idle - round(n_idle)) < 1e-6, f"chirp.idle_s x lo.fref_hz = {n_idle:g} must be a whole number")
        dco = self.band.center_hz / self.lo_mult
        _require(self.lo.loop_bw_hz < dco, "lo: loop bandwidth above the DCO frequency")

    # -- sourced placeholders ----------------------------------------------
    @property
    def lo_mult(self) -> int:
        from ..sources import frontend_placeholder

        return int(self.lo.mult if self.lo.mult is not None else frontend_placeholder(self.band.kind, "lo_mult").value)

    def frontend_value(self, name: str) -> tuple[float, str]:
        """``(value, source)`` of a front-end number: the config's own
        (``config``) or the band's placeholder (``assumed``)."""
        from ..sources import frontend_placeholder

        v = getattr(self.frontend, name)
        if v is not None:
            return float(v), "config"
        e = frontend_placeholder(self.band.kind, name)
        return float(e.value), e.source

    def lo_value(self, name: str) -> tuple[float, str]:
        from ..sources import frontend_placeholder

        v = getattr(self.lo, name)
        if v is not None:
            return float(v), "config"
        e = frontend_placeholder(self.band.kind, name)
        return float(e.value), e.source

    def oxygen_db_per_km(self) -> tuple[float, str]:
        from ..sources import number

        if self.channel.oxygen_db_per_km is not None:
            return float(self.channel.oxygen_db_per_km), "config"
        e = number("oxygen.60g_db_per_km" if self.band.kind == "60g_sensing" else "oxygen.77g_db_per_km")
        return float(e.value), e.source

    def rcs_dbsm(self) -> tuple[float, str]:
        from ..sources import number

        if self.target.rcs_dbsm is not None:
            return float(self.target.rcs_dbsm), "config"
        e = number(f"rcs.{self.target.kind}_dbsm")
        return float(e.value), e.source

    # -- derived -------------------------------------------------------------
    @property
    def slope_hz_per_s(self) -> float:
        return self.band.sweep_hz / self.chirp.duration_s

    @property
    def dco_center_hz(self) -> float:
        return self.band.center_hz / self.lo_mult

    @property
    def dco_sweep_hz(self) -> float:
        return self.band.sweep_hz / self.lo_mult

    @property
    def n_samples(self) -> int:
        """Beat samples per chirp."""
        return int(round(self.chirp.duration_s * self.rx.adc_fs_hz))

    @property
    def n_ref_cycles(self) -> int:
        """Reference cycles per chirp ramp."""
        return int(round(self.chirp.duration_s * self.lo.fref_hz))

    @property
    def n_idle_cycles(self) -> int:
        return int(round(self.chirp.idle_s * self.lo.fref_hz))

    @property
    def range_resolution_m(self) -> float:
        """c / 2B: one range bin (rectangular window)."""
        return C0 / (2.0 * self.band.sweep_hz)

    @property
    def max_range_m(self) -> float:
        """The range whose beat frequency reaches the IF bandwidth."""
        return self.rx.if_bw_hz * C0 / (2.0 * self.slope_hz_per_s)

    @property
    def velocity_resolution_mps(self) -> float:
        """lambda / (2 N_c PRI): one Doppler bin."""
        return self.band.wavelength_m / (2.0 * self.chirp.n_chirps * self.chirp.pri_s)

    @property
    def max_velocity_mps(self) -> float:
        """lambda / (4 PRI): the unambiguous radial velocity."""
        return self.band.wavelength_m / (4.0 * self.chirp.pri_s)

    def tau_s(self, range_m: float | None = None) -> float:
        """Round-trip delay 2R / c."""
        r = self.target.range_m if range_m is None else range_m
        return 2.0 * r / C0

    def beat_hz(self, range_m: float | None = None) -> float:
        """Beat frequency S tau of a target at ``range_m`` (the config's target by default)."""
        return self.slope_hz_per_s * self.tau_s(range_m)

    def doppler_hz(self, velocity_mps: float | None = None) -> float:
        """The beat's chirp-to-chirp phase rate ``2 v / lambda``: the beat is
        TX x conj(RX), whose carrier term ``2 pi f_c tau`` grows as the target
        recedes, so a receding target (v > 0) reads a positive Doppler bin."""
        v = self.target.velocity_mps if velocity_mps is None else velocity_mps
        return 2.0 * v / self.band.wavelength_m

    def time_chirps(self) -> int:
        n = self.sim.time_n_chirps
        return self.chirp.n_chirps if n is None else min(n, self.chirp.n_chirps)


__all__ = ["SCHEMA_VERSION", "C0", "K_BOLTZMANN", "T0_K", "BANDS", "WINDOWS", "BandConfig", "ChirpConfig",
           "LOConfig", "FrontEndConfig", "ChannelConfig", "TargetConfig", "RxConfig", "ProcessingConfig",
           "SimConfig", "RadarConfig"]

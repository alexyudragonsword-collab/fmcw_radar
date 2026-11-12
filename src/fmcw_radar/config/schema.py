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
    tdc_jitter_s: Optional[float] = None   # TDC input-referred jitter [s RMS]; None -> placeholder.  It is noise, and it is
                                           # what dithers the TDC's quantisation (0: an undithered quantiser, ghost targets)
    dp_gain: float = 1.0                # direct-path gain as built: 1 + eps is a two-point mismatch of eps
    dp_cal: Literal["none", "offline", "online"] = "offline"   # two-point gain calibration (chirp linearity)
    dp_cal_iterations: int = 2          # offline: least-squares passes, one chirp each
    dp_cal_mu: float = 1.0e-2           # online: LMS gain in the post-flyback window [1 / UI]
    dp_cal_window_cycles: int = 20      # online: reference cycles after each flyback the LMS updates on
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
        if self.tdc_jitter_s is not None:
            _finite_nonneg(self.tdc_jitter_s, "lo.tdc_jitter_s")
        _finite_pos(self.dp_gain, "lo.dp_gain")
        _require_in(self.dp_cal, {"none", "offline", "online"}, "lo.dp_cal")
        _require(self.dp_cal_iterations >= 1, "lo.dp_cal_iterations must be >= 1")
        _finite_pos(self.dp_cal_mu, "lo.dp_cal_mu")
        _require(self.dp_cal_window_cycles >= 1, "lo.dp_cal_window_cycles must be >= 1")
        _require(self.settle_cycles >= 1000, "lo.settle_cycles must be >= 1000 (the loop has to lock first)")
        _require_in(self.engine, {"event", "response", "ideal"}, "lo.engine")
        _finite(self.profile_shift_db, "lo.profile_shift_db")


# ---------------------------------------------------------------------------
# front end, channel, target
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontEndConfig:
    """The analytic front end: one number each.  Every ``None`` takes the
    band's entry from sources.yaml -- for the 60 GHz band the transmit power,
    the noise figure and the two compression points are a radar chip's
    figures read through mmw60_trx's sourced table, the rest placeholders
    (source: assumed); a set value is the config's own claim.

    The receiver has two input compression points.  ``p1db_oob_dbm`` is the
    stages ahead of the IF high-pass: what a signal beating below the
    high-pass corner meets, the TX leakage first of all.  ``p1db_inband_dbm``
    is what the echo and the IF / ADC meet; the placeholder is given at the
    band's ``rx_gain_db`` and falls 1 dB per dB of gain above it
    (:meth:`RadarConfig.p1db_inband`).  With ``compression`` on, both points
    are Rapp limiters of smoothness ``rx_rapp_p`` in the statistical and the
    time engine (``link/compression.py``)."""

    tx_power_dbm: Optional[float] = None
    tx_gain_dbi: Optional[float] = None
    rx_gain_dbi: Optional[float] = None
    rx_gain_db: Optional[float] = None      # LNA + mixer + IF gain to the ADC [dB]
    nf_db: Optional[float] = None
    p1db_oob_dbm: Optional[float] = None    # input 1 dB compression ahead of the IF high-pass [dBm]
    p1db_inband_dbm: Optional[float] = None  # input 1 dB compression in band, at this config's gain [dBm]
    rx_rapp_p: Optional[float] = None       # knee smoothness of both compression stages (Rapp p, link/compression.py)
    compression: bool = True                # model the two stages (False: a linear receiver, the 0.2.8 behaviour)

    def __post_init__(self):
        for name in ("tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "rx_gain_db", "nf_db", "p1db_oob_dbm", "p1db_inband_dbm",
                     "rx_rapp_p"):
            v = getattr(self, name)
            if v is not None:
                _finite(v, f"frontend.{name}")
        if self.rx_rapp_p is not None:
            _require(self.rx_rapp_p > 0.0, "frontend.rx_rapp_p must be > 0")


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
    """The beat path: an optional IF high-pass (``hpf_corner_hz``, Butterworth
    of ``hpf_order``, the leakage notch: 0 = none), a brick-wall IF
    (anti-alias) filter of ``if_bw_hz`` and a complex (I/Q) ADC at
    ``adc_fs_hz`` with ``adc_bits`` over the full scale ``adc_fullscale_dbm``
    (a full-scale sine's power into 50 ohm)."""

    if_bw_hz: float = 4.0e6             # one-sided beat bandwidth [Hz]
    adc_fs_hz: float = 10.0e6           # complex sample rate [Hz]
    adc_bits: int = 12
    adc_fullscale_dbm: float = 4.0      # 1 Vpp into 50 ohm
    hpf_corner_hz: float = 0.0          # IF high-pass corner [Hz]; 0 = none (milestone 2: the leakage notch)
    hpf_order: int = 1                  # Butterworth order of that high-pass
    blank_s: float = 0.0                # beat samples blanked at the start of every chirp [s] (the flyback transient
                                        # through the high-pass); the range window is fitted to the samples that remain

    def __post_init__(self):
        _finite_pos(self.if_bw_hz, "rx.if_bw_hz")
        _finite_nonneg(self.blank_s, "rx.blank_s")
        _finite_pos(self.adc_fs_hz, "rx.adc_fs_hz")
        _require(self.if_bw_hz <= 0.5 * self.adc_fs_hz, "rx.if_bw_hz must be <= adc_fs_hz / 2 (anti-alias)")
        _require(1 <= self.adc_bits <= 24, f"rx.adc_bits must be in 1..24, got {self.adc_bits}")
        _finite(self.adc_fullscale_dbm, "rx.adc_fullscale_dbm")
        _finite_nonneg(self.hpf_corner_hz, "rx.hpf_corner_hz")
        _require(self.hpf_corner_hz < self.if_bw_hz, "rx.hpf_corner_hz must be below the IF bandwidth")
        _require(1 <= self.hpf_order <= 4, f"rx.hpf_order must be in 1..4, got {self.hpf_order}")


# ---------------------------------------------------------------------------
# milestone 2: MIMO, leakage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CouplingConfig:
    """Mutual coupling of the receive array, through the vendored array_tx
    matrix (three sources, one object): ``analytic`` (flat c1 on the
    adjacent pair, c1 x c2_rel on the next), ``survey`` (the same magnitudes
    with the free-space delay's linear phase), ``touchstone`` (an .sNp file
    with n_rx ports).  ``c1_db`` None -> the band's placeholder (source:
    assumed, like array_tx's: the papers give no mmWave patch coupling
    phase).  ``calibrated`` applies the known matrix's inverse before the
    angle estimate (what a factory calibration does); off, the estimate
    carries the coupling's bias."""

    source: Literal["none", "analytic", "survey", "touchstone"] = "none"
    c1_db: Optional[float] = None
    c1_deg: float = 180.0
    c2_rel_db: float = -6.0
    path_delay: bool = True             # survey: linear phase from the pair's free-space delay
    touchstone: Optional[str] = None
    calibrated: bool = False

    def __post_init__(self):
        _require_in(self.source, {"none", "analytic", "survey", "touchstone"}, "mimo.coupling.source")
        if self.c1_db is not None:
            _require(math.isfinite(self.c1_db) and self.c1_db < 0.0, "mimo.coupling.c1_db must be a negative dB figure")
        _finite(self.c1_deg, "mimo.coupling.c1_deg")
        _require(math.isfinite(self.c2_rel_db) and self.c2_rel_db <= 0.0, "mimo.coupling.c2_rel_db must be <= 0 dB")
        _require(self.source != "touchstone" or bool(self.touchstone), "mimo.coupling.source touchstone needs a file")


@dataclass(frozen=True)
class MimoConfig:
    """TDM-MIMO: ``n_tx`` transmitters take the chirps in turn, ``n_rx``
    receivers sample every chirp; the virtual array is the sum of the two
    linear arrays' positions and is a uniform line of ``n_tx x n_rx``
    elements when the TX pitch is ``n_rx`` RX pitches (the default, None).
    The angle is estimated by a windowed FFT across the virtual elements at
    the target's range-Doppler cell (digital beamforming); the TX switching
    puts a Doppler phase of ``2 pi f_d PRI`` between the TX blocks that
    ``tdm_doppler_compensation`` removes with the estimated Doppler.  One
    TX, one RX is the single-channel radar of milestone 1, bit for bit."""

    n_tx: int = 1
    n_rx: int = 1
    rx_spacing_lambda: float = 0.5      # RX pitch in carrier wavelengths
    tx_spacing_lambda: Optional[float] = None   # TX pitch; None -> n_rx x rx_spacing (a filled virtual line)
    element_pattern: Literal["isotropic", "cos"] = "isotropic"
    angle_window: Literal["rect", "hann", "hamming", "blackman"] = "hann"
    angle_pad: int = 8                  # zero-padding factor of the angle FFT
    tdm_doppler_compensation: bool = True
    coupling: CouplingConfig = field(default_factory=CouplingConfig)

    def __post_init__(self):
        _require(self.n_tx >= 1 and self.n_rx >= 1, "mimo.n_tx and n_rx must be >= 1")
        _finite_pos(self.rx_spacing_lambda, "mimo.rx_spacing_lambda")
        if self.tx_spacing_lambda is not None:
            _finite_pos(self.tx_spacing_lambda, "mimo.tx_spacing_lambda")
            k = self.tx_spacing_lambda / self.rx_spacing_lambda
            _require(abs(k - round(k)) < 1e-9 and round(k) >= 1,
                     "mimo.tx_spacing_lambda must be a whole number of RX pitches (the virtual array stays a line)")
        _require_in(self.element_pattern, {"isotropic", "cos"}, "mimo.element_pattern")
        _require_in(self.angle_window, set(WINDOWS), "mimo.angle_window")
        _require(self.angle_pad >= 1, "mimo.angle_pad must be >= 1")

    @property
    def n_virtual(self) -> int:
        return self.n_tx * self.n_rx

    @property
    def tx_pitch_lambda(self) -> float:
        return self.tx_spacing_lambda if self.tx_spacing_lambda is not None else self.n_rx * self.rx_spacing_lambda


@dataclass(frozen=True)
class LeakageConfig:
    """TX-to-RX self-interference (milestone 2): the direct antenna /
    on-chip leakage at ``isolation_db`` below the TX power (None -> the
    band's placeholder, source: assumed) delayed by ``path_delay_s``, plus
    an optional near reflector (radome, bumper) at ``reflector_range_m``
    whose return is ``reflector_level_db`` relative to the direct leakage.
    Both share the one LO, so their phase noise is range-correlated at a
    tiny tau; what they do is sit at a beat of a few kHz with a hundred dB
    more power than the target, which the IF high-pass (``rx.hpf_*``) has
    to take out before the ADC."""

    enabled: bool = False
    isolation_db: Optional[float] = None
    path_delay_s: float = 0.2e-9
    reflector_range_m: Optional[float] = None
    reflector_level_db: float = -10.0

    def __post_init__(self):
        if self.isolation_db is not None:
            _finite_pos(self.isolation_db, "leakage.isolation_db")
        _finite_nonneg(self.path_delay_s, "leakage.path_delay_s")
        if self.reflector_range_m is not None:
            _finite_pos(self.reflector_range_m, "leakage.reflector_range_m")
        _finite(self.reflector_level_db, "leakage.reflector_level_db")


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
    target: TargetConfig = field(default_factory=TargetConfig)          # the primary target (every milestone-1 metric)
    extra_targets: tuple[TargetConfig, ...] = ()                         # milestone 2: more point targets, same model
    mimo: MimoConfig = field(default_factory=MimoConfig)
    leakage: LeakageConfig = field(default_factory=LeakageConfig)
    rx: RxConfig = field(default_factory=RxConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    sim: SimConfig = field(default_factory=SimConfig)

    def __post_init__(self):
        for i, t in enumerate(self.extra_targets):
            _require(isinstance(t, TargetConfig), f"extra_targets[{i}] must be a target mapping")
        _require(self.chirp.n_chirps % self.mimo.n_tx == 0,
                 f"chirp.n_chirps ({self.chirp.n_chirps}) must be a multiple of mimo.n_tx ({self.mimo.n_tx}): TDM blocks")
        n = self.chirp.duration_s * self.rx.adc_fs_hz
        _require(abs(n - round(n)) < 1e-6 and round(n) >= 16,
                 f"chirp.duration_s x rx.adc_fs_hz = {n:g} must be a whole number of samples >= 16")
        _require(self.rx.blank_s <= 0.25 * self.chirp.duration_s,
                 f"rx.blank_s = {self.rx.blank_s:g} s must be at most a quarter of the chirp ({self.chirp.duration_s:g} s)")
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
        (``config``) or the band's entry in sources.yaml with its tag."""
        from ..sources import frontend_placeholder

        v = getattr(self.frontend, name)
        if v is not None:
            return float(v), "config"
        e = frontend_placeholder(self.band.kind, name)
        return float(e.value), e.source

    def p1db_inband(self) -> tuple[float, str]:
        """``(value, source)`` of the in-band input compression point at this
        config's receive gain.  The band's entry is the figure at the band's
        own ``rx_gain_db``; a config that sets another gain moves it 1 dB
        down per dB of gain (the radar chip's Figure 7-2 is that straight
        line: the in-band compression is a fixed level at the output).  A
        config that sets ``frontend.p1db_inband_dbm`` is taken at its word."""
        from ..sources import frontend_placeholder

        if self.frontend.p1db_inband_dbm is not None:
            return float(self.frontend.p1db_inband_dbm), "config"
        e = frontend_placeholder(self.band.kind, "p1db_inband_dbm")
        g_ref = float(frontend_placeholder(self.band.kind, "rx_gain_db").value)
        g, _ = self.frontend_value("rx_gain_db")
        return float(e.value) - (g - g_ref), e.source

    def lo_value(self, name: str) -> tuple[float, str]:
        from ..sources import frontend_placeholder

        v = getattr(self.lo, name)
        if v is not None:
            return float(v), "config"
        e = frontend_placeholder(self.band.kind, name)
        return float(e.value), e.source

    @property
    def targets(self) -> tuple[TargetConfig, ...]:
        """Every point target, the primary first."""
        return (self.target,) + tuple(self.extra_targets)

    def rcs_of(self, t: TargetConfig) -> tuple[float, str]:
        from ..sources import number

        if t.rcs_dbsm is not None:
            return float(t.rcs_dbsm), "config"
        e = number(f"rcs.{t.kind}_dbsm")
        return float(e.value), e.source

    def leakage_value(self, name: str) -> tuple[float, str]:
        from ..sources import frontend_placeholder

        v = getattr(self.leakage, name)
        if v is not None:
            return float(v), "config"
        e = frontend_placeholder(self.band.kind, "tx_rx_isolation_db" if name == "isolation_db" else name)
        return float(e.value), e.source

    def coupling_c1(self) -> tuple[float, str]:
        from ..sources import frontend_placeholder

        if self.mimo.coupling.c1_db is not None:
            return float(self.mimo.coupling.c1_db), "config"
        e = frontend_placeholder(self.band.kind, "rx_coupling_c1_db")
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
    def n_blank(self) -> int:
        """Beat samples blanked at the start of every chirp (``rx.blank_s``)."""
        return int(round(self.rx.blank_s * self.rx.adc_fs_hz))

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
        """lambda / (2 N_c PRI): one Doppler bin (the whole frame; with TDM
        each transmitter's own Doppler FFT has n_chirps / n_tx chirps at
        n_tx x PRI, the same resolution)."""
        return self.band.wavelength_m / (2.0 * self.chirp.n_chirps * self.chirp.pri_s)

    @property
    def max_velocity_mps(self) -> float:
        """lambda / (4 PRI_tx): the unambiguous radial velocity, PRI_tx = n_tx x PRI under TDM."""
        return self.band.wavelength_m / (4.0 * self.chirp.pri_s * self.mimo.n_tx)

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
           "SimConfig", "RadarConfig", "MimoConfig", "CouplingConfig", "LeakageConfig"]

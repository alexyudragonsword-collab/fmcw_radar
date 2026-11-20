"""The front-end contract: what a page may turn and what it reads back.

polar_tx / array_tx's layering (their ``cairn/gui-redesign.md`` and
``cairn/gui.md``): **describe** here, **compute** in ``guiutil``, dispatch
and queue in the hosts, **draw** in the page.  This module only describes.

Invariant #1 of the repository (the config is the one truth) is what it
enforces for a GUI:

* **Every control is a config field.**  The list is ``config/form.py``'s
  ``SECTIONS`` -- which ``tests/test_config.py`` already keeps identical to
  the schema -- with what a page needs on top: a Chinese and an English
  label, the display unit, a display range and step, where the number used
  when the field is left empty comes from, and under which settings the
  control acts at all.
* **Defaults are read, never typed.**  A control's default is
  ``RadarConfig()``'s; the number behind an empty field is the one the
  library resolves (``frontend_value`` and its siblings) with its source
  tag.  ``tests/test_guispec.py`` builds the config from the form's
  defaults and requires it to equal ``RadarConfig()``.
* **A control must act.**  The same tests turn every control one step, in
  the settings ``when`` declares, and require the output named by ``seen``
  to change: the statistical report, the time engine's frame, or what a run
  holds.  A field that nothing reads is in ``HIDDEN`` with the reason, and
  a test holds that it still moves nothing.
* **What the config refuses, a page shows.**  ``values_to_config`` goes
  through the loader a YAML file goes through, so an edit the schema does
  not take raises its ``ValueError`` -- the sentence a page puts beside the
  control (two virtual elements under a Hann angle window, say).
* **A number edited on the page is ``assumed``.**  ``tags`` gives the tag a
  page shows: the source table's while the field is empty (or holds the
  very number the table gives), ``assumed`` once it holds another one.

Nothing here computes physics.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import RadarConfig, apply_overrides, config_from_dict, config_to_dict
from .config.form import SECTIONS
from .config.schema import BANDS
from .sources import frontend_placeholder

# ---------------------------------------------------------------- groups and labels

#: control groups in display order (the form's sections): id -> (zh, en)
GROUPS: dict[str, tuple[str, str]] = {
    "band": ("频段与扫频", "Band & sweep"),
    "chirp": ("Chirp", "Chirp"),
    "lo": ("本振 / ADPLL", "LO / ADPLL"),
    "frontend": ("前端", "Front end"),
    "channel": ("信道", "Channel"),
    "target": ("目标", "Target"),
    "extra_targets": ("更多目标", "More targets"),
    "mimo": ("TDM-MIMO", "TDM-MIMO"),
    "leakage": ("收发泄漏", "TX-RX leakage"),
    "rx": ("接收机", "Receiver"),
    "processing": ("处理", "Processing"),
    "regulatory": ("法规", "Regulatory"),
    "sim": ("仿真", "Simulation"),
}

#: Chinese labels (the English ones are the form's own, cleaned of their bracketed unit and notes)
ZH: dict[str, str] = {
    "band.kind": "频段预设", "band.center_hz": "扫频中心", "band.sweep_hz": "扫频带宽 B",
    "chirp.shape": "波形", "chirp.duration_s": "斜坡时长", "chirp.idle_s": "斜坡间空闲", "chirp.n_chirps": "每帧 chirp 数",
    "chirp.frame_period_s": "帧周期",
    "lo.mult": "倍频 N", "lo.fref_hz": "参考频率", "lo.loop_bw_hz": "环路带宽", "lo.phase_margin_deg": "相位裕度", "lo.kdco_hz": "Kdco",
    "lo.dco_pn_dbchz": "DCO 点相噪", "lo.dco_pn_offset_hz": "DCO 点相噪的偏移", "lo.dco_pn_f1f3_hz": "1/f³ 拐点",
    "lo.dco_pn_floor_dbchz": "DCO 底噪", "lo.ref_pn_dbchz": "参考底噪", "lo.tdc_res_s": "TDC 分辨率", "lo.tdc_jitter_s": "TDC 抖动",
    "lo.tdc_dither_lsb": "扣除式 TDC dither", "lo.tdc_dither_gain_error": "dither 的 DTC 增益误差", "lo.dp_gain": "直通路增益(1 + ε)",
    "lo.dp_cal": "两点增益校准", "lo.dp_cal_iterations": "离线校准遍数", "lo.dp_cal_mu": "在线 LMS 增益",
    "lo.dp_cal_window_cycles": "在线校准窗(飞回后)", "lo.settle_cycles": "首个 chirp 前的建立周期", "lo.engine": "chirp 引擎",
    "lo.profile": "时钟剖面文件", "lo.profile_shift_db": "剖面平移",
    "frontend.tx_power_dbm": "发射功率", "frontend.tx_backoff_db": "发射回退", "frontend.tx_gain_dbi": "发射天线增益",
    "frontend.rx_gain_dbi": "接收天线增益", "frontend.rx_gain_db": "接收链增益(到 ADC)", "frontend.nf_db": "噪声系数",
    "frontend.p1db_oob_dbm": "IF 高通之前的输入 P1dB", "frontend.p1db_inband_dbm": "带内输入 P1dB",
    "frontend.rx_rapp_p": "压缩拐点平滑度(Rapp p)", "frontend.compression": "建模接收机压缩",
    "channel.oxygen_db_per_km": "氧气衰减", "channel.extra_loss_db": "额外往返损耗",
    "target.kind": "类型", "target.range_m": "距离", "target.velocity_mps": "径向速度", "target.angle_deg": "角度", "target.rcs_dbsm": "RCS",
    "extra_targets": "更多点目标",
    "mimo.n_tx": "发射通道数(TDM)", "mimo.n_rx": "接收通道数", "mimo.rx_spacing_lambda": "RX 间距", "mimo.tx_spacing_lambda": "TX 间距",
    "mimo.element_pattern": "阵元方向图", "mimo.angle_window": "角度窗", "mimo.angle_pad": "角度 FFT 零填充",
    "mimo.tdm_doppler_compensation": "补偿 TDM 多普勒相位", "mimo.coupling.source": "RX 互耦", "mimo.coupling.c1_db": "相邻耦合",
    "mimo.coupling.c1_deg": "相邻耦合相位", "mimo.coupling.c2_rel_db": "次邻相对相邻", "mimo.coupling.path_delay": "按自由空间延迟给相位",
    "mimo.coupling.touchstone": "Touchstone 文件", "mimo.coupling.calibrated": "测角前用已知矩阵的逆",
    "leakage.enabled": "建模收发泄漏", "leakage.isolation_db": "收发隔离", "leakage.path_delay_s": "直接路径延迟",
    "leakage.reflector_range_m": "近端反射体距离", "leakage.reflector_level_db": "近端反射体相对电平",
    "rx.if_bw_hz": "IF 带宽", "rx.adc_fs_hz": "ADC 采样率", "rx.adc_bits": "ADC 位数", "rx.adc_fullscale_dbm": "ADC 满幅",
    "rx.hpf_corner_hz": "IF 高通截止", "rx.hpf_order": "IF 高通阶数", "rx.blank_s": "chirp 起始消隐",
    "processing.window_range": "距离窗", "processing.window_doppler": "多普勒窗", "processing.range_pad": "距离 FFT 零填充",
    "processing.doppler_pad": "多普勒 FFT 零填充", "processing.cfar_guard": "CFAR 保护格", "processing.cfar_train": "CFAR 训练格",
    "processing.cfar_pfa": "CFAR 虚警概率",
    "regulatory.scenario": "使用场景",
    "sim.seed": "随机种子", "sim.engine": "引擎", "sim.time_osr": "时域引擎:包络过采样", "sim.time_n_chirps": "时域引擎:合成的 chirp 数",
    "sim.pn_bins_per_decade": "闭式网格密度",
}
#: English labels where the form's own does not stand alone (its "... " continuation rows)
EN: dict[str, str] = {
    "lo.dco_pn_offset_hz": "Offset of the DCO spot phase noise", "lo.tdc_dither_gain_error": "Gain error of the dither's DTC",
    "rx.blank_s": "Blanked at each chirp's start", "extra_targets": "Extra point targets",
}
#: display units the form writes in ASCII
_UNIT = {"us": "µs", "deg": "°", "lambda": "λ", "1/UI": "1/UI"}

#: the controls a page shows open; the others sit folded in their group
COMMON: tuple[str, ...] = (
    "band.kind", "band.center_hz", "band.sweep_hz", "chirp.duration_s", "chirp.n_chirps", "chirp.frame_period_s",
    "lo.engine", "lo.mult", "lo.fref_hz", "lo.loop_bw_hz", "lo.dco_pn_dbchz", "lo.tdc_res_s", "lo.tdc_jitter_s", "lo.tdc_dither_lsb",
    "frontend.tx_power_dbm", "frontend.tx_backoff_db", "frontend.tx_gain_dbi", "frontend.rx_gain_dbi", "frontend.rx_gain_db",
    "frontend.nf_db", "frontend.p1db_inband_dbm", "channel.oxygen_db_per_km",
    "target.kind", "target.range_m", "target.velocity_mps", "target.rcs_dbsm",
    "rx.if_bw_hz", "rx.adc_fs_hz", "rx.adc_bits", "processing.window_range", "processing.cfar_pfa",
    "regulatory.scenario", "sim.seed", "sim.engine",
)

#: display range and step of the numeric controls, in display units: (lo, hi, step).  Display only -- the config
#: validates, and a value outside the range is still a legal YAML value.  ``tests/test_guispec.py`` holds every
#: default (or resolved placeholder) inside its range and one step from it a valid config.
RANGES: dict[str, tuple[float, float, float]] = {
    "band.center_hz": (57.0, 81.0, 0.1), "band.sweep_hz": (0.2, 7.0, 0.1),
    "chirp.duration_s": (10.0, 2000.0, 10.0), "chirp.idle_s": (0.0, 1000.0, 1.0), "chirp.n_chirps": (2, 1024, 2),
    "chirp.frame_period_s": (1.0, 1000.0, 0.5),
    "lo.mult": (1, 16, 1), "lo.fref_hz": (10.0, 500.0, 10.0), "lo.loop_bw_hz": (0.05, 10.0, 0.05), "lo.phase_margin_deg": (30.0, 80.0, 1.0),
    "lo.kdco_hz": (1.0, 500.0, 1.0), "lo.dco_pn_dbchz": (-130.0, -70.0, 1.0), "lo.dco_pn_offset_hz": (0.1, 10.0, 0.1),
    "lo.dco_pn_f1f3_hz": (10.0, 3000.0, 10.0), "lo.dco_pn_floor_dbchz": (-170.0, -120.0, 1.0), "lo.ref_pn_dbchz": (-175.0, -130.0, 1.0),
    "lo.tdc_res_s": (1.0, 30.0, 0.1), "lo.tdc_jitter_s": (0.0, 20.0, 0.1), "lo.tdc_dither_lsb": (0.0, 4.0, 1.0),
    "lo.tdc_dither_gain_error": (-0.2, 0.2, 0.01), "lo.dp_gain": (0.8, 1.2, 0.01), "lo.dp_cal_iterations": (1, 6, 1),
    "lo.dp_cal_mu": (0.001, 0.1, 0.001), "lo.dp_cal_window_cycles": (5, 200, 5), "lo.settle_cycles": (1000, 200000, 1000),
    "lo.profile_shift_db": (-20.0, 20.0, 1.0),
    "frontend.tx_power_dbm": (-10.0, 20.0, 0.5), "frontend.tx_backoff_db": (0.0, 26.0, 0.5), "frontend.tx_gain_dbi": (0.0, 25.0, 0.5),
    "frontend.rx_gain_dbi": (0.0, 25.0, 0.5), "frontend.rx_gain_db": (10.0, 60.0, 1.0), "frontend.nf_db": (3.0, 20.0, 0.5),
    "frontend.p1db_oob_dbm": (-30.0, 0.0, 1.0), "frontend.p1db_inband_dbm": (-50.0, -10.0, 1.0), "frontend.rx_rapp_p": (0.5, 5.0, 0.5),
    "channel.oxygen_db_per_km": (0.0, 20.0, 0.5), "channel.extra_loss_db": (0.0, 20.0, 0.5),
    "target.range_m": (0.2, 100.0, 0.1), "target.velocity_mps": (-30.0, 30.0, 0.1), "target.angle_deg": (-60.0, 60.0, 1.0),
    "target.rcs_dbsm": (-30.0, 30.0, 1.0),
    "mimo.n_tx": (1, 4, 1), "mimo.n_rx": (1, 8, 1), "mimo.rx_spacing_lambda": (0.25, 2.0, 0.05), "mimo.tx_spacing_lambda": (0.5, 8.0, 0.5),
    "mimo.angle_pad": (1, 32, 1), "mimo.coupling.c1_db": (-40.0, -3.0, 1.0), "mimo.coupling.c1_deg": (-180.0, 180.0, 5.0),
    "mimo.coupling.c2_rel_db": (-30.0, 0.0, 1.0),
    "leakage.isolation_db": (10.0, 60.0, 1.0), "leakage.path_delay_s": (0.0, 2.0, 0.05), "leakage.reflector_range_m": (0.01, 1.0, 0.01),
    "leakage.reflector_level_db": (-40.0, 0.0, 1.0),
    "rx.if_bw_hz": (0.5, 20.0, 0.5), "rx.adc_fs_hz": (2.5, 100.0, 2.5), "rx.adc_bits": (6, 16, 1), "rx.adc_fullscale_dbm": (-10.0, 13.0, 1.0),
    "rx.hpf_corner_hz": (0.0, 2000.0, 50.0), "rx.hpf_order": (1, 4, 1), "rx.blank_s": (0.0, 25.0, 0.5),
    "processing.range_pad": (1, 8, 1), "processing.doppler_pad": (1, 8, 1), "processing.cfar_guard": (0, 8, 1),
    "processing.cfar_train": (2, 32, 1), "processing.cfar_pfa": (1e-8, 1e-2, 1e-5),
    "sim.seed": (0, 2**31 - 1, 1), "sim.time_osr": (1.0, 4.0, 0.25), "sim.time_n_chirps": (1, 1024, 1),
    "sim.pn_bins_per_decade": (10, 240, 10),
}

# ---------------------------------------------------------------- when a control acts, and where it shows

#: one atom of a condition: {"path", "op", "value"}; op is "in" (value: allowed values), "gt" (number), "set" (not empty)
def _in(path: str, *values) -> dict:
    return {"path": path, "op": "in", "value": list(values)}


def _gt(path: str, value: float) -> dict:
    return {"path": path, "op": "gt", "value": value}


def _set(path: str) -> dict:
    return {"path": path, "op": "set", "value": None}


_LEAK = [_in("leakage.enabled", True)]
_COUPLED = [_gt("mimo.n_rx", 1), _in("mimo.coupling.source", "analytic", "survey")]
_ARRAY = [_gt("mimo.n_rx", 1)]

#: settings without which a control changes nothing (all atoms must hold).  A page greys such a control out and says
#: why; the knob test turns it with these settings on.  Measured, not assumed: see cairn/gui.md.
WHEN: dict[str, list[dict]] = {
    "lo.tdc_dither_gain_error": [_gt("lo.tdc_dither_lsb", 0.0)],
    "lo.dp_cal_iterations": [_in("lo.dp_cal", "offline")],
    "lo.dp_cal_mu": [_in("lo.dp_cal", "online"), _in("lo.engine", "event")],
    "lo.dp_cal_window_cycles": [_in("lo.dp_cal", "online"), _in("lo.engine", "event")],
    "lo.settle_cycles": [_in("lo.engine", "event")],
    "lo.profile_shift_db": [_set("lo.profile")],
    "frontend.p1db_oob_dbm": _LEAK, "frontend.rx_rapp_p": _LEAK, "frontend.compression": _LEAK,
    "mimo.rx_spacing_lambda": _ARRAY, "mimo.element_pattern": _ARRAY, "mimo.angle_window": _ARRAY, "mimo.angle_pad": _ARRAY,
    "mimo.tx_spacing_lambda": [_gt("mimo.n_tx", 1)], "mimo.tdm_doppler_compensation": [_gt("mimo.n_tx", 1)],
    "mimo.coupling.source": _ARRAY,
    "mimo.coupling.c1_db": _COUPLED, "mimo.coupling.c1_deg": _COUPLED, "mimo.coupling.c2_rel_db": _COUPLED,
    "mimo.coupling.path_delay": [_gt("mimo.n_rx", 1), _in("mimo.coupling.source", "survey")],
    "mimo.coupling.touchstone": [_gt("mimo.n_rx", 1), _in("mimo.coupling.source", "touchstone")],
    "mimo.coupling.calibrated": [_gt("mimo.n_rx", 1), _in("mimo.coupling.source", "analytic", "survey", "touchstone")],
    "leakage.isolation_db": _LEAK, "leakage.path_delay_s": _LEAK, "leakage.reflector_range_m": _LEAK,
    "leakage.reflector_level_db": _LEAK + [_set("leakage.reflector_range_m")],
    "rx.hpf_order": [_gt("rx.hpf_corner_hz", 0.0)],
}

#: a choice the config refuses unless a condition holds: (path, option) -> atoms.  Online calibration exists in the
#: cycle-accurate engine only: the config layer refuses ``lo.dp_cal: online`` with ``lo.engine: response`` (0.2.22;
#: before that the library ran uncalibrated and said nothing).  Declared from both sides, so a page can grey the
#: option out instead of letting the user run into the refusal.
CHOICE_WHEN: dict[tuple[str, Any], list[dict]] = {
    ("lo.dp_cal", "online"): [_in("lo.engine", "event", "ideal")],
    ("lo.engine", "response"): [_in("lo.dp_cal", "none", "offline")],
}

#: where a turned control shows: the statistical report (the default), the time engine's frame, or what a run holds.
SEEN: dict[str, str] = {
    "sim.seed": "frame", "sim.time_osr": "frame", "sim.time_n_chirps": "frame",
    "sim.engine": "run",
}

#: fields the schema declares and nothing reads: not offered.  A test holds that they still move nothing.
HIDDEN: dict[str, str] = {
    "sim.pn_bins_per_decade": "declared in the schema, read by no engine (found by turning it: 20, 60 and 120 give the same report)",
}

#: the engines a run uses and what the conclusions of each cover (the page's engine row)
ENGINES: dict[str, dict[str, str]] = {
    "statistical": {
        "zh": "统计引擎(主)", "en": "statistical engine (main)",
        "does_zh": "SNR、旁瓣、检测概率解析算。", "does_en": "SNR, sidelobes and detection probability, analytically.",
        "covers_zh": "链路预算、合规、检测概率、相噪底、鬼目标的期望检出数。",
        "covers_en": "link budget, compliance, detection probability, phase-noise floor, expected ghost detections."},
    "time": {
        "zh": "时域引擎(只做一致性检查)", "en": "time engine (a consistency check only)",
        "does_zh": "真波形 → 真混频 → 真 FFT。", "does_en": "real waveform → real mixing → real FFT.",
        "covers_zh": "距离-多普勒图这一帧和它的 CFAR 过门限格;与统计引擎 1 dB 内的对照只在线性 + 高斯噪声下成立。",
        "covers_en": "this one range-Doppler frame and its CFAR cells; the 1 dB agreement with the statistical engine holds for "
                     "LTI + Gaussian noise only."},
    "chirp:event": {
        "zh": "chirp 引擎 event(逐周期)", "en": "chirp engine: event (cycle-accurate)",
        "does_zh": "逐周期仿真环路,给出 chirp 的频率误差曲线。", "does_en": "simulates the loop cycle by cycle; gives the chirp's error curve.",
        "covers_zh": "杂散 / 鬼目标的结论只认它。", "covers_en": "the only engine that can vouch for spurs / ghosts."},
    "chirp:response": {
        "zh": "chirp 引擎 response(线性化)", "en": "chirp engine: response (linearised)",
        "does_zh": "线性化的环路响应。", "does_en": "the linearised loop response.",
        "covers_zh": "不能为杂散背书(vouches_for_spurs = False);在线校准在这个引擎里不做。",
        "covers_en": "cannot vouch for spurs (vouches_for_spurs = False); no online calibration in this engine."},
    "chirp:ideal": {
        "zh": "chirp 引擎 ideal", "en": "chirp engine: ideal",
        "does_zh": "理想斜坡,没有环路的误差曲线。", "does_en": "an ideal ramp, no loop error curve.",
        "covers_zh": "没有鬼目标的结论;相噪剖面仍在。", "covers_en": "no conclusion on ghosts; the phase-noise profile is still there."},
}

#: the headline numbers a page reads from the statistical report: id -> where it is and how to show it.
#: ``better`` says which way is an improvement (None: neither).  ``report`` is a path into ``report.report()``.
#: ``chirp_engine``: the number is the chirp engine's own (the others are the same whichever engine made the error curve),
#: so a preview run on the linearised engine does not have it yet.
METRICS: dict[str, dict[str, Any]] = {
    "eirp_margin_db": {"zh": "EIRP 裕度", "en": "EIRP margin", "unit": "dB", "digits": 1, "better": "higher",
                       "report": "compliance.eirp_margin_db"},
    "compliant": {"zh": "合规", "en": "compliant", "unit": "", "digits": 0, "better": "higher", "report": "compliance.compliant"},
    "max_frame_rate_hz": {"zh": "最高帧率", "en": "max frame rate", "unit": "1/s", "digits": 2, "better": None,
                          "report": "compliance.max_frame_rate_hz"},
    "snr_cell_db": {"zh": "格点 SNR", "en": "cell SNR", "unit": "dB", "digits": 2, "better": "higher", "report": "detection.snr_cell_db"},
    "pd_target": {"zh": "检测概率(图上 CA-CFAR)", "en": "Pd (CA-CFAR on the map)", "unit": "", "digits": 3, "better": "higher",
                  "report": "cfar.pd_target"},
    "snr_pd90_db": {"zh": "Pd 0.9 所需 SNR", "en": "SNR for Pd 0.9", "unit": "dB", "digits": 2, "better": "lower",
                    "report": "cfar.snr_pd90_db"},
    "ghost_detections_per_frame": {"chirp_engine": True, "zh": "鬼目标每帧期望检出", "en": "ghost detections per frame", "unit": "", "digits": 2, "better": "lower",
                                   "report": "cfar.ghost_detections_per_frame"},
    "false_alarm_cells_per_frame": {"zh": "噪声虚警格 / 帧", "en": "noise false-alarm cells per frame", "unit": "", "digits": 2,
                                    "better": None, "report": "cfar.false_alarm_cells_per_frame"},
    "range_res_m": {"zh": "距离分辨率", "en": "range resolution", "unit": "m", "digits": 4, "better": "lower", "report": "radar.range_res_m"},
    "velocity_res_mps": {"zh": "速度分辨率", "en": "velocity resolution", "unit": "m/s", "digits": 3, "better": "lower",
                         "report": "radar.velocity_res_mps"},
    "max_range_m": {"zh": "最大距离(IF 带限)", "en": "max range (IF band)", "unit": "m", "digits": 2, "better": "higher",
                    "report": "radar.max_range_m"},
    "pn_residual_rms_rad": {"chirp_engine": True, "zh": "相噪残余(目标处)", "en": "phase-noise residual at the target", "unit": "rad", "digits": 4,
                            "better": "lower", "report": "phase_noise.residual_rms_rad"},
    "chirp_rms_hz": {"chirp_engine": True, "zh": "chirp 频率误差 RMS", "en": "chirp frequency error RMS", "unit": "Hz", "digits": 0, "better": "lower",
                     "report": "chirp.rms_hz"},
}


# ---------------------------------------------------------------- the system diagram, the band rows, the sweep

#: the diagram's lanes: what the lane is and which engine computes it
LANES: dict[str, dict[str, str]] = {
    "gen": {"zh": "① chirp 发生器:两点调制 ADPLL(vendored polar_tx / pllsim)", "en": "① Chirp generator: two-point ADPLL (vendored polar_tx / pllsim)",
            "by_zh": "chirp 引擎;两个引擎都读它的误差曲线", "by_en": "chirp engine; both engines read its error curve"},
    "rf": {"zh": "② 发射 → 信道 → 目标 → 接收", "en": "② Transmit → channel → target → receive",
           "by_zh": "统计:雷达方程与噪声预算 · 时域:真波形混频", "by_en": "statistical: radar equation and noise budget · time: real waveform and mixing"},
    "reg": {"zh": "合规检查", "en": "Compliance check", "by_zh": "合规检查:限值全读来源表", "by_en": "compliance check: every limit read from the source table"},
    "dsp": {"zh": "③ 处理:距离 / 多普勒 FFT、CA-CFAR", "en": "③ Processing: range / Doppler FFT, CA-CFAR",
            "by_zh": "统计:窗与 CFAR 的闭式 · 时域:真 FFT 与 CFAR", "by_en": "statistical: closed forms of windows and CFAR · time: real FFTs and CFAR"},
}


def _c(path: str, zh: str, en: str) -> dict:
    """A stage line that is a control: its value, unit and tag are the control's."""
    return {"kind": "control", "path": path, "zh": zh, "en": en}


def _r(read: str, zh: str, en: str, unit: str = "", digits: int = 2, scale: float = 1.0) -> dict:
    """A stage line read from the run (``report.…`` / ``plots.…``; ``[term]``
    picks the row of a list whose ``term`` -- or ``offset_m`` -- is that)."""
    return {"kind": "read", "read": read, "zh": zh, "en": en, "unit": unit, "digits": digits, "scale": scale}


def _n(zh: str, en: str) -> dict:
    return {"kind": "note", "zh": zh, "en": en}


_BUD = "report.budget[{}].value"
#: the chain from the chirp generator to the detections, in signal order.  Every line is a control (shown with the tag
#: the parameter panel shows), a number read from the run, or a note; ``out`` is the quantity after the stage;
#: ``active`` names what must be truthy in the run for the stage to be in play (otherwise it is drawn as an option).
STAGES: tuple[dict[str, Any], ...] = (
    {"id": "ramp", "lane": "gen", "zh": "斜坡发生(FCW)", "en": "Ramp generator (FCW)", "lines": [
        _c("band.sweep_hz", "带宽 B", "sweep B"), _c("chirp.duration_s", "斜坡", "ramp"), _c("chirp.n_chirps", "每帧 chirp", "chirps / frame"),
        _r("report.radar.slope_mhz_per_us", "斜率", "slope", "MHz/µs", 1)]},
    {"id": "ref", "lane": "gen", "zh": "参考", "en": "Reference", "lines": [
        _c("lo.fref_hz", "频率", "frequency"), _c("lo.ref_pn_dbchz", "底噪", "floor")]},
    {"id": "tdc", "lane": "gen", "zh": "TDC(鉴相)", "en": "TDC (phase detector)", "lines": [
        _c("lo.tdc_res_s", "分辨率", "resolution"), _c("lo.tdc_jitter_s", "抖动", "jitter"), _c("lo.tdc_dither_lsb", "扣除式 dither", "subtr. dither")]},
    {"id": "lf", "lane": "gen", "zh": "数字环路滤波", "en": "Digital loop filter", "lines": [
        _c("lo.loop_bw_hz", "带宽", "bandwidth"), _c("lo.phase_margin_deg", "相位裕度", "phase margin")]},
    {"id": "dco", "lane": "gen", "zh": "DCO", "en": "DCO", "lines": [
        _r("report.radar.lo_dco_ghz", "频率", "frequency", "GHz", 2), _c("lo.kdco_hz", "Kdco", "Kdco"),
        _c("lo.dco_pn_dbchz", "点相噪", "spot PN"), _c("lo.dco_pn_floor_dbchz", "底", "floor")]},
    {"id": "mult", "lane": "gen", "zh": "倍频 ×N", "en": "Multiplier ×N", "lines": [
        _c("lo.mult", "N", "N"), _n("相噪 +20 log N", "PN +20 log N")]},
    {"id": "lo", "lane": "gen", "zh": "LO 输出", "en": "LO output", "lines": [
        _c("band.center_hz", "中心", "centre"), _r("plots.pn.l_1mhz_dbc_hz", "L(1 MHz)", "L(1 MHz)", "dBc/Hz", 2),
        _r("report.chirp.rms_hz", "频率误差 RMS", "freq. error RMS", "MHz", 3, 1e6), _c("lo.engine", "chirp 引擎", "chirp engine")]},
    {"id": "split", "lane": "rf", "zh": "功分", "en": "Splitter", "lines": [
        _n("TX 与 RX 用同一条 LO", "one LO for TX and RX"), _n("(铁律 2)", "(invariant 2)")]},
    {"id": "pa", "lane": "rf", "zh": "发射机(PA)", "en": "Transmitter (PA)", "lines": [
        _c("frontend.tx_power_dbm", "能发", "can deliver"), _c("frontend.tx_backoff_db", "回退", "backoff")],
     "out": _r("report.compliance.conducted_dbm", "传导", "conducted", "dBm", 2)},
    {"id": "txant", "lane": "rf", "zh": "发射天线", "en": "TX antenna", "lines": [_c("frontend.tx_gain_dbi", "增益", "gain")],
     "out": _r("report.compliance.eirp_dbm", "EIRP", "EIRP", "dBm", 2)},
    {"id": "comp", "lane": "reg", "zh": "合规 §15.255(c)(2)", "en": "Compliance §15.255(c)(2)", "verdict": "report.compliance.compliant",
     "active": "report.compliance.applies", "lines": [
        _r("report.compliance.limit_dbm", "上限", "limit", "dBm", 0), _r("report.compliance.eirp_margin_db", "裕度", "margin", "dB", 1),
        _r("report.compliance.max_frame_rate_hz", "最高帧率", "max frame rate", "1/s", 1)]},
    {"id": "leak", "lane": "rf", "zh": "TX→RX 泄漏", "en": "TX→RX leakage", "active": "values.leakage.enabled", "lines": [
        _c("leakage.isolation_db", "隔离", "isolation"), _c("leakage.path_delay_s", "延迟", "delay")]},
    {"id": "chan", "lane": "rf", "zh": "信道(往返)", "en": "Channel (two-way)", "lines": [
        _r(_BUD.format("free-space path loss (4pi)^3 R^4 / lambda^2"), "路径损耗", "path loss", "dB", 2),
        _c("channel.oxygen_db_per_km", "氧气", "oxygen"), _r(_BUD.format("oxygen over 2R"), "氧气往返", "oxygen, 2R", "dB", 2),
        _c("channel.extra_loss_db", "额外损耗", "extra loss"), _r("report.inputs.wavelength_m.value", "λ", "λ", "mm", 3, 1e-3)]},
    {"id": "tgt", "lane": "rf", "zh": "目标(输入)", "en": "Target (an input)", "lines": [
        _c("target.kind", "类型", "kind"), _c("target.rcs_dbsm", "RCS", "RCS"), _c("target.range_m", "距离", "range"),
        _c("target.velocity_mps", "径向速度", "radial velocity"), _r("plots.pn.tau_s", "往返延迟 τ", "round trip τ", "ns", 2, 1e-9),
        _r("report.target.doppler_hz", "多普勒", "Doppler", "Hz", 1)]},
    {"id": "rxant", "lane": "rf", "zh": "接收天线", "en": "RX antenna", "lines": [_c("frontend.rx_gain_dbi", "增益", "gain")],
     "out": _r(_BUD.format("received power P_r"), "P_r", "P_r", "dBm", 2)},
    {"id": "mix", "lane": "rf", "zh": "LNA + 混频", "en": "LNA + mixer", "lines": [
        _c("frontend.nf_db", "NF", "NF"), _c("frontend.p1db_oob_dbm", "带外 P1dB", "OOB P1dB"),
        _r("report.phase_noise.residual_rms_rad", "相噪残余", "PN residual", "rad", 4)],
     "out": _r("report.target.beat_khz", "拍频", "beat", "kHz", 1)},
    {"id": "hpf", "lane": "rf", "zh": "IF 高通", "en": "IF high-pass", "active": "values.rx.hpf_corner_hz", "lines": [
        _c("rx.hpf_corner_hz", "截止", "corner"), _c("rx.hpf_order", "阶数", "order")]},
    {"id": "ifa", "lane": "rf", "zh": "IF 放大 + 低通", "en": "IF gain + low-pass", "lines": [
        _c("frontend.rx_gain_db", "到 ADC 增益", "gain to ADC"), _c("frontend.p1db_inband_dbm", "带内 P1dB", "in-band P1dB"),
        _c("rx.if_bw_hz", "带宽", "bandwidth")]},
    {"id": "adc", "lane": "rf", "zh": "ADC", "en": "ADC", "lines": [
        _c("rx.adc_fs_hz", "采样率", "sample rate"), _c("rx.adc_bits", "位数", "bits"), _c("rx.adc_fullscale_dbm", "满幅", "full scale")],
     "out": _r(_BUD.format("signal at the ADC"), "信号", "signal", "dBm", 2)},
    {"id": "rfft", "lane": "dsp", "zh": "距离 FFT", "en": "Range FFT", "lines": [
        _c("processing.window_range", "窗", "window"), _c("processing.range_pad", "零填充 ×", "zero-pad ×"),
        _r("report.radar.range_res_m", "分辨率", "resolution", "cm", 2, 1e-2), _r("report.radar.max_range_m", "最大距离", "max range", "m", 2)]},
    {"id": "dfft", "lane": "dsp", "zh": "多普勒 FFT", "en": "Doppler FFT", "lines": [
        _c("processing.window_doppler", "窗", "window"), _c("processing.doppler_pad", "零填充 ×", "zero-pad ×"),
        _r("report.radar.velocity_res_mps", "速度分辨率", "velocity res.", "m/s", 3), _r("report.radar.max_velocity_mps", "不模糊速度 ±", "unambiguous ±", "m/s", 2)]},
    {"id": "rd", "lane": "dsp", "zh": "距离-多普勒图", "en": "Range-Doppler map", "lines": [
        _r("report.detection.snr_cell_db", "格点 SNR", "cell SNR", "dB", 2),
        _r("report.phase_noise.floor[1.0].per_cell_dbc", "相噪底 / 格,+1 m", "PN floor / cell, +1 m", "dBc", 1),
        _r("plots.ghosts.strongest_dbc", "最强鬼目标", "strongest ghost", "dBc", 2)]},
    {"id": "cfar", "lane": "dsp", "zh": "CA-CFAR", "en": "CA-CFAR", "lines": [
        _c("processing.cfar_guard", "保护格", "guard cells"), _c("processing.cfar_train", "训练格", "training cells"),
        _c("processing.cfar_pfa", "Pfa", "Pfa"), _r("report.cfar.snr_pd90_db", "Pd 0.9 需", "for Pd 0.9", "dB", 2)]},
    {"id": "det", "lane": "dsp", "zh": "检测结果", "en": "Detections", "lines": [
        _r("report.cfar.pd_target", "真目标 Pd", "target Pd", "", 3),
        _r("report.cfar.ghost_detections_per_frame", "鬼目标 / 帧", "ghosts / frame", "", 2),
        _r("report.cfar.false_alarm_cells_per_frame", "噪声虚警格 / 帧", "noise FA cells / frame", "", 2)]},
    {"id": "dbf", "lane": "dsp", "zh": "测角 DBF", "en": "Angle (DBF)", "active": "report.angle", "lines": [
        _c("mimo.n_tx", "TX", "TX"), _c("mimo.n_rx", "RX", "RX"),
        _r("report.angle.beamwidth_deg", "波束宽", "beamwidth", "°", 2), _r("report.angle.theta_est_deg", "读出角度", "angle read", "°", 2),
        _r("report.angle.sigma_expected_deg", "期望 σ", "expected σ", "°", 3)]},
)

#: the rows of the band trade-off: the sweep as configured first, then the alternatives example 09 tabulates
#: (band edges in GHz and the scenario the tier needs).  The limits are not here: they come from the source table.
BAND_ROWS: tuple[dict[str, Any], ...] = (
    {"id": "current", "zh": "当前扫频", "en": "the sweep as configured", "lo_ghz": None, "hi_ghz": None, "scenario": "as_configured"},
    {"id": "57_59p4_indoor", "zh": "57–59.4 GHz,室内", "en": "57–59.4 GHz, indoor", "lo_ghz": 57.0, "hi_ghz": 59.4, "scenario": "indoor"},
    {"id": "57_61p56", "zh": "57–61.56 GHz", "en": "57–61.56 GHz", "lo_ghz": 57.0, "hi_ghz": 61.56, "scenario": None},
    {"id": "57_64", "zh": "57–64 GHz,整段", "en": "57–64 GHz, the whole band", "lo_ghz": 57.0, "hi_ghz": 64.0, "scenario": None},
    {"id": "57_64_outdoor_fixed", "zh": "57–64 GHz,室外固定", "en": "57–64 GHz, outdoors, fixed", "lo_ghz": 57.0, "hi_ghz": 64.0,
     "scenario": "outdoor_fixed"},
)

#: the antenna-gain table of the band page: (transmit, receive) gain steps in dB around the configured pair
ANTENNA_STEPS: tuple[tuple[float, float], ...] = ((-8.0, 0.0), (-4.0, 0.0), (0.0, 0.0), (0.0, -2.0), (0.0, 2.0))

#: the most points one sweep may ask for (each is a full statistical run)
SWEEP_MAX_POINTS = 41


def sweepable() -> list[str]:
    """The controls a sweep can step: the numeric ones with a display range."""
    return [c.path for c in controls() if c.path in RANGES and c.kind in ("float", "opt_float", "int", "opt_int")]


# ---------------------------------------------------------------- the controls

@dataclass(frozen=True)
class Control:
    path: str                       # the config's dotted path
    kind: str                       # the form's: bool | enum | float | int | opt_float | opt_int | opt_str | table
    group: str
    zh: str
    en: str
    unit: str                       # display unit
    scale: float                    # config (SI) value = display value x scale
    default: Any                    # RadarConfig()'s value (SI); None = left empty
    choices: tuple | None = None
    columns: tuple | None = None    # a table's columns
    lo: float | None = None         # display range and step (display units)
    hi: float | None = None
    step: float | None = None
    common: bool = False            # shown open
    when: tuple = ()                # atoms that must all hold for the control to act
    choice_when: tuple = ()         # ((option, atoms), ...)
    seen: str = "report"            # report | frame | run
    resolved: Any = None            # the number the library uses when the field is empty (SI), for RadarConfig()
    source: str | None = None       # ... and its source tag; None = a design decision, no tag
    sources_key: str | None = None  # ... and its key in data/sources.yaml


def _label(path: str, raw: str) -> tuple[str, str]:
    """The form's label split into its English text and its display unit."""
    m = re.search(r"\[([^\]]+)\]", raw)
    unit = m.group(1) if m else ""
    unit = _UNIT.get(unit, unit)
    for word, sym in (("us", "µs"), ("lambda", "λ"), ("deg", "°")):
        unit = re.sub(rf"\b{word}\b", sym, unit)
    en = re.sub(r"\s*\[[^\]]+\]", "", raw)
    en = re.sub(r"\s*\((empty|0) = [^)]*\)", "", en)
    en = re.sub(r"\s*\(milestone 2\)", "", en)
    en = re.sub(r"\s*\(table: [^)]*\)", "", en)
    return EN.get(path, en.strip()), unit


def _get(d: dict, path: str) -> Any:
    for k in path.split("."):
        d = d[k]
    return d


#: the fields with a number behind them when left empty: path -> (the library's own lookup, its key in sources.yaml)
_FRONTEND = ("tx_power_dbm", "tx_backoff_db", "tx_gain_dbi", "rx_gain_dbi", "rx_gain_db", "nf_db", "p1db_oob_dbm", "rx_rapp_p")
_LOOKUPS: dict[str, tuple[Any, Any]] = {
    **{f"frontend.{n}": ((lambda c, n=n: c.frontend_value(n)), (lambda c, n=n: f"{c.band.kind}.{n}")) for n in _FRONTEND},
    # the in-band point follows the receive gain (schema.RadarConfig.p1db_inband): the lookup, not the bare table entry
    "frontend.p1db_inband_dbm": ((lambda c: c.p1db_inband()), (lambda c: f"{c.band.kind}.p1db_inband_dbm")),
    **{f"lo.{n}": ((lambda c, n=n: c.lo_value(n)), (lambda c, n=n: f"{c.band.kind}.{n}"))
       for n in ("dco_pn_dbchz", "dco_pn_floor_dbchz", "tdc_res_s", "tdc_jitter_s")},
    "lo.mult": ((lambda c: (c.lo_mult, frontend_placeholder(c.band.kind, "lo_mult").source)), (lambda c: f"{c.band.kind}.lo_mult")),
    "leakage.isolation_db": ((lambda c: c.leakage_value("isolation_db")), (lambda c: f"{c.band.kind}.tx_rx_isolation_db")),
    "mimo.coupling.c1_db": ((lambda c: c.coupling_c1()), (lambda c: f"{c.band.kind}.rx_coupling_c1_db")),
    "channel.oxygen_db_per_km": ((lambda c: c.oxygen_db_per_km()),
                                 (lambda c: "oxygen.60g_db_per_km" if c.band.kind == "60g_sensing" else "oxygen.77g_db_per_km")),
    "target.rcs_dbsm": ((lambda c: c.rcs_dbsm()), (lambda c: f"rcs.{c.target.kind}_dbsm")),
}


def resolve(cfg: RadarConfig, path: str) -> tuple[Any, str, str] | None:
    """``(value, source, sources_key)`` of the number the library uses for
    ``path`` when the field is left empty, read through the library's own
    lookups (so it follows the band, the target kind and, for the in-band
    compression point, the receive gain) -- or None when an empty field
    means "not set" (no placeholder behind it)."""
    if path not in _LOOKUPS or (path == "target.rcs_dbsm" and cfg.target.kind == "custom"):
        return None
    lookup, key = _LOOKUPS[path]
    if _get(config_to_dict(cfg), path) is not None:
        cfg = apply_overrides(cfg, {path: None})
    value, source = lookup(cfg)
    return value, source, key(cfg)


def bundled_profiles() -> list[str]:
    """Clock-profile files shipped with the package, as a config would write them."""
    root = Path(__file__).resolve().parent
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in (root / "vendor").rglob("clock_profiles/*.yaml"))


def controls(cfg: RadarConfig | None = None) -> list[Control]:
    """Every config field as a control, in the form's order (``HIDDEN`` ones
    left out).  The placeholder behind an empty field is resolved for
    ``cfg`` (``RadarConfig()`` by default): it follows the band and the
    target kind."""
    cfg = RadarConfig() if cfg is None else cfg
    d0 = config_to_dict(RadarConfig())
    out = []
    for sec, _, items in SECTIONS:
        for it in items:
            path = it["path"]
            if path in HIDDEN:
                continue
            en, unit = _label(path, it["label"])
            lo, hi, step = RANGES.get(path, (None, None, None))
            choices = tuple(it["options"]) if it.get("options") else None
            if path == "lo.profile":
                choices = (None,) + tuple(bundled_profiles())
            r = resolve(cfg, path)
            out.append(Control(
                path=path, kind=it["kind"], group=sec, zh=ZH[path], en=en, unit=unit, scale=float(it.get("scale") or 1.0),
                default=_get(d0, path), choices=choices, columns=tuple(it["columns"]) if it.get("columns") else None,
                lo=lo, hi=hi, step=step, common=path in COMMON, when=tuple(WHEN.get(path, ())),
                choice_when=tuple((opt, tuple(atoms)) for (p, opt), atoms in CHOICE_WHEN.items() if p == path),
                seen=SEEN.get(path, "report"),
                resolved=None if r is None else r[0], source=None if r is None else r[1], sources_key=None if r is None else r[2]))
    return out


def spec(cfg: RadarConfig | None = None) -> dict:
    """The whole contract as JSON-ready data (what a host serves the page)."""
    return {"groups": [{"id": g, "zh": zh, "en": en} for g, (zh, en) in GROUPS.items()],
            "controls": [asdict(c) for c in controls(cfg)],
            "hidden": dict(HIDDEN), "engines": ENGINES, "metrics": METRICS,
            "bands": {k: list(v) for k, v in BANDS.items()},
            "lanes": LANES, "stages": [dict(st) for st in STAGES], "band_rows": [dict(r) for r in BAND_ROWS],
            "sweepable": sweepable(), "sweep_max_points": SWEEP_MAX_POINTS, "antenna_steps": [list(x) for x in ANTENNA_STEPS],
            "tags": {"spec": ["原文已读", "read in the original"], "survey": ["文献转述", "survey, not checked against the original"],
                     "assumed": ["占位 / 设计取舍 / 在界面上改过", "placeholder / design choice / edited on the page"],
                     "derived": ["由 spec 推算", "derived from spec numbers"]}}


# ---------------------------------------------------------------- values <-> config

def to_display(c: Control, value: Any) -> Any:
    """A config (SI) value in the control's display unit."""
    if value is None or isinstance(value, (bool, str, list, tuple)) or c.scale == 1.0:
        return value
    return value / c.scale


def from_display(c: Control, value: Any) -> Any:
    """A display value back in the config's unit, in the field's own type."""
    if value is None or value == "":
        return None
    if c.kind in ("int", "opt_int"):
        return int(round(float(value)))
    if c.kind in ("float", "opt_float"):
        return float(value) * c.scale
    return value


def values_from_config(cfg: RadarConfig) -> dict[str, Any]:
    """The flat ``{path: value}`` a page edits, in config (SI) units, every
    field included (the hidden ones too, so a round trip loses nothing)."""
    d = config_to_dict(cfg)
    return {it["path"]: _get(d, it["path"]) for _, _, items in SECTIONS for it in items}


def _nest(flat: dict[str, Any]) -> dict:
    out: dict = {}
    for path, v in flat.items():
        d = out
        parts = path.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = v
    return out


def values_to_config(values: dict[str, Any], canonical: bool = True) -> RadarConfig:
    """Flat values -> ``RadarConfig`` through ``config_from_dict``, the loader
    a YAML file goes through (validated; a bad value raises ``ValueError``
    with the schema's message).

    ``canonical``: a field that holds the very number the source table gives
    for it is written empty, so the library keeps reading the table and the
    number keeps its citation -- typing 12 into a field whose placeholder is
    12 changes nothing, the config's hash included."""
    flat = dict(values_from_config(RadarConfig()))
    flat.update(values)
    cfg = config_from_dict(_nest(flat))
    if canonical:
        back = {}
        for path, v in flat.items():
            if v is None or isinstance(v, (bool, str, list, tuple)):
                continue
            r = resolve(cfg, path)
            if r is not None and float(v) == float(r[0]):
                back[path] = None
        if back:
            flat.update(back)
            cfg = config_from_dict(_nest(flat))
    return cfg


def tags(values: dict[str, Any]) -> dict[str, str]:
    """The source tag a page shows beside each control: the source table's
    while the field is empty or holds the table's own number, ``assumed``
    once it holds another one.  Controls with no placeholder behind them
    are design decisions and carry no tag."""
    flat = dict(values_from_config(RadarConfig()))
    flat.update(values)
    cfg = config_from_dict(_nest(flat))
    out = {}
    for path, v in flat.items():
        r = resolve(cfg, path)
        if r is None:
            if path == "target.rcs_dbsm" and v is not None:
                out[path] = "assumed"          # a custom target's RCS is the user's number
            continue
        out[path] = r[1] if v is None or float(v) == float(r[0]) else "assumed"
    return out


def _holds(atom: dict, flat: dict[str, Any]) -> bool:
    v = flat.get(atom["path"])
    if atom["op"] == "in":
        return v in atom["value"]
    if atom["op"] == "gt":
        return v is not None and v > atom["value"]
    return v not in (None, "")              # "set"


def inert(values: dict[str, Any]) -> dict[str, list[dict]]:
    """Controls that change nothing under ``values``, each with the atoms of
    its condition that do not hold (what a page shows as the reason), and
    chosen options that do not act (``"path=option"``)."""
    flat = dict(values_from_config(RadarConfig()))
    flat.update(values)
    out: dict[str, list[dict]] = {}
    for path, atoms in WHEN.items():
        miss = [a for a in atoms if not _holds(a, flat)]
        if miss:
            out[path] = miss
    for (path, opt), atoms in CHOICE_WHEN.items():
        if flat.get(path) == opt:
            miss = [a for a in atoms if not _holds(a, flat)]
            if miss:
                out[f"{path}={opt}"] = miss
    return out


def refused_choices(values: dict[str, Any]) -> dict[str, list]:
    """Options the config would refuse under ``values``: ``{path: [options]}``
    for a page to grey out in its menus (``CHOICE_WHEN``, read forwards)."""
    flat = dict(values_from_config(RadarConfig()))
    flat.update(values)
    out: dict[str, list] = {}
    for (path, opt), atoms in CHOICE_WHEN.items():
        if flat.get(path) != opt and not all(_holds(a, flat) for a in atoms):
            out.setdefault(path, []).append(opt)
    return out


def band_switch(values: dict[str, Any], kind: str) -> dict[str, Any]:
    """The values after choosing another band: the sweep is kept if the new
    band's window holds it and narrowed to the window otherwise, and centred
    in the window -- ``band.kind`` alone is not a valid edit (the 60 GHz
    sweep lies outside the 77 GHz window).  Fields left empty then resolve
    to the new band's placeholders by themselves."""
    lo, hi = BANDS[kind]
    flat = dict(values)
    sweep = min(float(flat.get("band.sweep_hz", RadarConfig().band.sweep_hz)), hi - lo)
    flat.update({"band.kind": kind, "band.sweep_hz": sweep, "band.center_hz": 0.5 * (lo + hi)})
    return flat


def diff(a: RadarConfig, b: RadarConfig) -> list[dict[str, Any]]:
    """Fields that differ between two configs: ``[{path, a, b}]``."""
    va, vb = values_from_config(a), values_from_config(b)
    return [{"path": p, "a": va[p], "b": vb[p]} for p in va if va[p] != vb[p]]


__all__ = ["GROUPS", "ZH", "EN", "COMMON", "RANGES", "WHEN", "CHOICE_WHEN", "SEEN", "HIDDEN", "ENGINES", "METRICS", "Control",
           "controls", "spec", "resolve", "bundled_profiles", "to_display", "from_display", "values_from_config",
           "values_to_config", "tags", "inert", "refused_choices", "band_switch", "diff"]

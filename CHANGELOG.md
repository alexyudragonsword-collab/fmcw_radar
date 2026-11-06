# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.1.1] — 2026-11-06 — 鬼目标与在线校准(里程碑 1 的 P1 余项)

- `StatResult.nonlinearity["ghosts"]`:chirp 频率误差曲线的确定性杂散,从单 ramp 的距离响应里提(主瓣外、−70 dBc 以上的局部极大),
  `ghosts_vouched` 只在 event 引擎下为真(铁律 6);报表多一张表。默认 5 ps TDC 在 ±4.85 m 处 −45.3 dBc,2 ps 时 −54.9 dBc,与时域图 3 dB 内一致。
- 在线两点校准换成飞回后 20 周期的幅值加权 LMS(`ChirpFlybackLMS`):±5 % 四个 chirp 内到 ±0.05 %,无偏;新字段 `lo.dp_cal_window_cycles`,
  `lo.dp_cal_mu` 改为窗口内增益(默认 1e-2)。四条弯路记在 `cairn/chirp-engine.md`。
- CI:单提交历史上的 fingerprint base、依赖下限的 `np.trapezoid`。指纹:在线用例与新 ghost 键动了,其余逐位不变(numbers-move)。

---

## [0.1.0] — 2026-11-06 — 里程碑 1:单 chirp、单目标

- **配置层**(`fmcw_radar.config`):frozen `RadarConfig`(频段 / chirp / LO / 前端 / 信道 / 目标 / 接收 / 处理 / 仿真),YAML 严格加载、
  dotted 覆盖、表单字段声明;两个 bundled 配置(60 GHz 感知、77 GHz 车载一档,后者只换数)。
- **来源表**(`data/sources.yaml`):前端占位 20 条 `assumed`、氧气吸收 / RCS / Harris 窗表 9 条 `survey`;`grep -c "source:"` 一次列全。
- **LO**(`lo.py`):vendored polar_tx(main 7057738)两点 ADPLL,PI 环按 (UGB, PM) 综合;相噪剖面 = analyze() ×N²(fref/2 以上取 DCO 自身),
  或 pll_simulator 剖面文件;`tools/export_lo_profile.py` 导出。
- **range correlation**(`phase_noise`):残余 PSD = 2(1 − cos 2πfτ)·S_φ;τ = 0 逐位为零;闭式与合成 0.1 dB 内;旁瓣 = 残余 L(f) + 窗每格噪声带宽,
  以及高斯相位的精确谱(`beat_sideband`:exp(R(t) − R(0)) 的变换,含各阶、拍频音相干损失 e^{−σ²})—— 残余不小时(100 m,0.3 rad)一阶在近目标处低估 8–20 dB。
- **chirp 引擎**(`chirp`):event(逐周期,`ADPLL.simulate` 直驱)、response(线性化参照)、ideal;离线 LS 两点校准(默认,两次到 1e-4)与
  差分 sign-sign 在线校准;解析二次项只作参照组。polar_tx 的 event 有效域指标在 chirp 上 495 %,判断见 `cairn/chirp-engine.md`。
- **雷达方程**(`link`):EIRP、(4π)³R⁴/λ²、氧气按 2R、RCS、NF、ADC 量化噪声、窗的相干增益、P1dB 裕量、Swerling 0 检测概率。
- **处理**(`processing`):rect / Hann / Hamming / Blackman、距离 FFT + 多普勒 FFT、峰值读数、CA-CFAR(1-D / 2-D)最简版。
- **引擎**:统计(主)与时域(5 GS/s 包络真混频 → 砖墙 IF → ADC 量化 → FFT);`run_radar(cfg)` 一个入口。
- **验收**(示例 00–04,`tests/` 120 项):矩形窗 Rayleigh 宽 3.73 cm 对 c/2B 3.75 cm(0.5 %);Hann / Hamming / Blackman 的 −3 dB 宽对窗谱 < 0.1 %、对 Harris 表 < 2.3 %;
  τ = 0 残余为零;1 / 10 / 100 m 闭式 vs 合成 0.114 dB;FFT 上 +1 / +2 / +5 m 旁瓣 +0.11 / −0.02 / −0.44 dB;三个距离 SNR 差 −0.07 … −0.10 dB
  (扣格点失配、带内相噪均值、拍频音相干损失);ADPLL 曲线(峰 199 MHz、RMS 6.2 MHz、建立 1.47 µs @ 5 % 失配;匹配时底 0.54 MHz RMS)
  喂统计引擎与时域引擎逐点相同(宽 5.39 cm,旁瓣 −31.5 dB,差 0.00 dB)。
- **工具**:`tools/budget_report.py`(一页)、`fingerprint.py`(639 值)、`vendor_check.py --strict`、`run_examples.py --smoke`、`example_drift.py`;
  CI:lint + 4 个 Python + 依赖下限 + 示例冒烟 + vendor 漂移 + 指纹。

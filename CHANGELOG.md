# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.2.0] — 2026-11-07 — 里程碑 2:TDM-MIMO 测角、TX 泄漏、多目标与 CFAR 曲线

- **TDM-MIMO 虚拟阵列**(`mimo.py`,config `mimo.*`,vendored array_tx@e897c15 的 geometry / beam / coupling / touchstone):TX + RX 位置之和(默认填满的线),
  u 格点加窗 DFT 测角,TDM 多普勒相位补偿(2 m/s 不补偿偏 2.71°)、互耦三来源(analytic / survey / touchstone,相邻 −16 dB 占位 `assumed`;
  未校准偏 −0.29°,`coupling.calibrated` 后 0.0002°)、CRLB、array_tx 的波束宽与扫频斜视(60 GHz ±2 GHz 斜视 ±0.7°,FR2 的 5 倍)。
  时域引擎出 (chirp, RX, 样本) 立方,每 TX 块各自 FFT 后非相干合成,目标格 DBF:20° 目标 6 个 seed 均值 +0.014°、RMS 0.050°(界 0.023°)。
- **TX 泄漏**(`link/leakage.py`,config `leakage.*`、`rx.hpf_*`,`processing/iffilter.py`):直接泄漏(隔离 25 dB 占位)+ 近端反射体经同一 LO(τ ≈ 0,
  相噪几乎全抵消)的预算:P1dB 裕量 −5 dB、ADC 裕量 −21 dB → 2 阶 200 kHz 高通后 +35 dB;时域引擎削波 100 % → 3.5 %(飞回瞬态),
  目标在泄漏下 −18.1 dB 处被找到(预算 −16.2 dB)。
- **多目标与 CFAR 曲线**:`extra_targets` 列表进 config;统计引擎每目标一行(电平、SNR、最强他者的窗裙 / 相噪、遮蔽判断),
  时域引擎 `found_targets` 分格找峰;CA-CFAR 的蒙卡(Swerling 0 / 1)对闭式:Pd 0.9 处损失 N = 16 1.35 dB、N = 32 0.73 dB,Swerling 1 闭式与蒙卡 0.02 内。
- **修过的坑**:TDM 补偿用粗多普勒格留 −1.48° 偏差(改为相邻同 TX chirp 的相位推进);边缘波束的角旁瓣读到绕回的主瓣(谱按周期滚动);
  邻目标的主瓣被当成本目标(分格 + 局部极大);示例输出路径按仓库相对打印。
- 示例 05–08,`configs/radar_60g_mimo.yaml`,报表三节,`tests/` +25 项;指纹 691 → 1235 值,旧值逐位不变(numbers-move:只有新键)。
  CI 的 vendor-drift 作业多检出 array_tx。

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

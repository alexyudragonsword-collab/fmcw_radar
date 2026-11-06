# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 里程碑 2(下一轮)

1. **TDM-MIMO 虚拟阵列测角** —— vendor array_tx(main e897c15,到时按当时 main 的完整 SHA pin)的互耦矩阵三来源与按真实带宽算的波束斜视
   (4–7 GHz 扫频下斜视比 FR2 400 MHz 大一个数量级,ex06 的机制直接复用);虚拟阵列是新的。`target.angle_deg` 已在 config 里,单通道引擎不用它。
2. **TX 泄漏 / 自干扰**(老清单 #10 全双工 / SIC):近端泄漏经同一 LO 的 range correlation 在 τ ≈ 0 处几乎没有相噪,但幅度大;
   P1dB 裕量现在只对目标回波报(里程碑 1 的 `p1db_margin_db` 67 dB 不含泄漏)。
3. **多目标与 CFAR 的虚警 / 检测曲线**:现在的 CA-CFAR 是最简版(2-D 方窗,阈值因子 n(Pfa^(−1/n) − 1)),检测概率是 Swerling 0 已知噪底的闭式,
   没有 CFAR 损失;示例 00 在 64 chirp、距离零填充 ×4 下给 27 个过阈格(都是目标主瓣的邻格)。要做:Pfa / Pd 的蒙卡曲线对闭式,多目标遮蔽。
4. **mmw60_trx 前端到位后替换占位**:`frontend.*`、`lo.mult`、`lo.dco_pn_*`、`lo.tdc_res_s` 全是 `source: assumed`(`grep -c "source: assumed"` = 20);
   接口按前端对象写(`cfg.frontend_value(name)` 一处换),到了就换、重新 pin。倍频器自身底噪也在那时补。

## P1 — 结论的可信度

1. **TDC 量化的鬼目标在真噪声下不消失,但统计引擎不知道它**。32 chirp 帧、5 m 目标:无噪声 event 引擎 9.87 m 处 −45.5 dBc(5 ps TDC;2 ps 时 −55.8 dBc),
   开环路噪声后 2.2 / 7.81 m 处 −49 … −50 dBc(两个 seed 同位置)。机制与数字见 `cairn/chirp-engine.md`。统计引擎的非线性剖面只拿一个 ramp 的曲线,
   看得到它在距离维的位置,但 CFAR / Pd 的闭式里没有这一项;示例 00 的 CFAR 因此在主瓣外报 12 格。
   要做:(a) 在统计引擎里把 event 曲线的鬼目标当确定性杂散列表报出(距离、电平),与窗旁瓣、相噪底并列;(b) TDC dither(pllsim 没有,报回 pll_simulator);
   (c) chirp 引擎带噪声时与 `LOProfile` 的分工(环内由逐周期引擎、环外由剖面)以免重复计相噪。
   复现:`run_time(cfg, ChirpEngine(cfg).run(noise=False, n_chirps=32), phase_noise=False, noise=False, quantise=False)`,看 rd_db 离目标 ±40 格外的最大值。
2. **在线 dp_cal 收敛慢**:差分 sign-sign(`ChirpSignSignCal`)1.05 → 1.006 要 20 个 chirp(2 ms),从 0.96 一侧 6 个 chirp 只到 0.97;
   polar_tx 原版 SignSignLMS 在锯齿上发散(1.05 → 1.066)。要做:gear shift(大 mu 粗调后小 mu)、只在飞回后固定窗口内更新、或 LMS 全精度。
   默认是离线 LS(一次到 1e-4),足够里程碑 1。复现:示例 02 最后一组。
3. **polar_tx 的 event 有效域指标在 chirp 上读 495 %**,本库的判断是指标不适用(见 `cairn/chirp-engine.md`)。这是本库的读法,
   应报回 polar_tx ROADMAP B1:指标按"亚周期相位轨迹"与"频率斜坡"分开。没有报之前,`ChirpResult.ui_per_ref_cycle_p99` 和报表都把数打出来。

## P2 — 一致性与能力

1. **时域 SNR 比期望低 0.07–0.10 dB**(示例 04:2 / 5 / 10 m,32 chirp;示例 00 的 64 chirp 差 0.00 dB)。已扣的:格点失配(Hann 多普勒维 0.44 格 1.1 dB)、
   带内相噪均值(−74 … −60 dBc/格)、拍频音相干损失 e^{−σ²}(−0.05 … −0.10 dB)。纯热噪声 + 理想 chirp 时差 +0.15 dB(噪底估计的最大值偏差一类),
   剩下的 −0.1 dB 没有归因。1 dB 判据过了。
2. **FFT 上量相噪旁瓣的方差 ±0.3 dB**(64 chirp × ±10 格,Blackman,高斯相位精确谱对照):示例 04 +1 / +2 / +5 m 差 +0.11 / −0.02 / −0.44 dB,
   换 seed 在 ±0.4 dB 内摆。要压到 0.1 dB 需要 10 倍的 chirp 数或直接比残余 PSD(那条已经 0.1 dB)。更近的偏移(< 10 格)要更低旁瓣的窗(Blackman-Harris / Taylor)。
3. **时域引擎按 chirp 独立合成相噪**(块 500k 点,最低 10 kHz),chirp 间 LO 低频相关没有表示;对多普勒维噪底无影响的论证见 `cairn/range-correlation.md`,
   但慢目标 / 长帧(PRF 10 kHz 以下的相噪)没有验证。
4. **性能**:时域引擎 64 chirp × 500k 包络样本约 7 s(4 核);fingerprint 9 s;全套测试约 3 分钟,`test_engines.py` 占一半。

## P3 — 能力扩展

1. GUI 与 Android:`config/form.py` 的表单声明已在,Dash / Chaquopy 都没接。
2. 三角波 / 多斜率 chirp、chirp 间空闲对 ADPLL 的影响(现在 `idle_s` 只是让 LO 停在起始频率)。
3. 77 GHz 档只换了数(`configs/radar_77g_automotive.yaml`,全 assumed),没有任何车载规范的数字。

## 边界(有意不做)

- 通信波形、JCAS(以后第三个库 vendor 这两个)。
- 目标跟踪、分类、点云、机器学习;目标运动学(速度在帧内恒定)。
- 天线电磁仿真;信道只有自由空间 + 氧气吸收 + 点目标。
- 改 polar_tx / array_tx / mmw60_trx:需要它们改的报回各自 ROADMAP,合并后重新 pin。

# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 等上游

1. **mmw60_trx 前端到位后替换占位**:`frontend.*`、`lo.mult`、`lo.dco_pn_*`、`lo.tdc_res_s`、`leakage.isolation_db`、`mimo.coupling.c1_db` 全是 `source: assumed`
   (`grep -c "source: assumed" src/fmcw_radar/data/sources.yaml` = 24);接口按前端对象写(`cfg.frontend_value(name)` / `leakage_value` / `coupling_c1` 各一处换),
   到了就换、重新 pin。倍频器自身底噪也在那时补。mmw60_trx 在 2026-11-07 仍是空仓。

## P1 — 结论的可信度

1. **TDC 量化的鬼目标:统计引擎现在报它,但 CFAR / Pd 的闭式仍不含它**。32 chirp 帧、5 m 目标:无噪声 event 引擎 9.87 m 处 −45.5 dBc(5 ps TDC;2 ps 时 −55.8 dBc),
   开环路噪声后 2.2 / 7.81 m 处 −49 … −50 dBc(两个 seed 同位置)。机制与数字见 `cairn/chirp-engine.md`。0.1.1 起 `StatResult.nonlinearity["ghosts"]`
   从单 ramp 的曲线列出它(±4.85 m,−45.3 dBc,与距离–多普勒图 3 dB 内一致),报表有一张表;示例 00 的 CFAR 仍在主瓣外报 12 格,因为 Pd / Pfa 的闭式只认高斯噪底。
   要做:(a) TDC dither(pllsim 没有,报回 pll_simulator);(b) chirp 引擎带噪声时与 `LOProfile` 的分工(环内由逐周期引擎、环外由剖面)以免重复计相噪;
   (c) 示例 06 的 CFAR 曲线仍只对高斯噪底(蒙卡与闭式都是),确定性杂散没算进虚警。
   复现:`run_statistical(cfg).nonlinearity["ghosts"]`;时域对照 `run_time(cfg, ..., phase_noise=False, noise=False, quantise=False)` 看 rd_db 离目标 ±40 格外的最大值。
2. **polar_tx 的 event 有效域指标在 chirp 上读 495 %**,本库的判断是指标不适用(见 `cairn/chirp-engine.md`)。这是本库的读法,
   应报回 polar_tx ROADMAP B1:指标按"亚周期相位轨迹"与"频率斜坡"分开。没有报之前,`ChirpResult.ui_per_ref_cycle_p99` 和报表都把数打出来。

## P2 — 一致性与能力

0. **里程碑 2 留下的**(复现:示例 05–08,`cairn/mimo-angle.md`):
   - 高通后的飞回瞬态没有 blanking:2 阶 200 kHz 高通下每个 chirp 开头削波 3.5 %(1 阶 2.7 %,50 kHz 14.9 %),窗压住了它,但 `clipped_fraction` 不会到零;
     要做 chirp 开头的 ADC blanking 或把瞬态算进期望 SNR。
   - 时域测角 RMS 0.050° 对 CRLB 0.023°(2 × 4、20°、6 个 seed × 8 chirp),差的 2 倍没有归因(ADC 量化、相噪、多普勒估计噪声各占多少);
     界是单快拍确定性信源的,时域是 Hann 多普勒格上的合成快拍。
   - TDM 的多普勒补偿在目标格上估单音频率(`doppler_fine_hz`),两目标同距离格同多普勒格时取其合成,各自的角都偏;要做多普勒维的分辨或 BPM-MIMO。
   - `found_targets` 的分格规则只分到格:两目标近于一个距离格(3.75 cm)时仍找同一个峰;那是分辨率,不是 bug,但报表没有标。
   - 2-D CA-CFAR 的格相关:距离维零填充 ×4 下纯噪声帧 64000 格 4 个虚警(6.3e-5 对 1e-4),闭式的 Pfa 按独立格算是上界;要给出有效独立格数。
   - 泄漏只有直接路径 + 一个反射体,相噪经 τ ≈ 0 几乎全抵消是对的,但发射机的 AM 噪声 / 泄漏的幅度噪声没有模型(mmw60_trx 到位再说)。
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

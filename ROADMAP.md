# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 等上游

1. **mmw60_trx 的前端面**(消费清单已提:mmw60_trx#14,对照它的 main@`4df03852bcfce28054a2d313eeb32ba16bbf0fa9`,它的 ROADMAP D4 在收)。本库 24 条 `source: assumed`
   (12 项 × 两个频段)里:PA(`psat_dbm` / `ScaledRappPA`)与 LO 剖面现在就能用;天线增益有字段无来源;RX 增益 / NF / 压缩点只有 vendored wifitrx 的 sub-7 GHz AGC 梯子;
   TX→RX 隔离没有。等它补上 TX→RX 隔离、60 GHz 的 NF 与压缩点、带来源的天线增益,再按 main 的完整 SHA pin、换占位
   (`cfg.frontend_value(name)` / `leakage_value` 各一处)。
2. **×N 之后的 LO 剖面已经能读,还没用**:pll_simulator#71 / #72 做了倍频器剖面(N²·L_in + 底噪),mmw60_trx 带了
   `pllsim_wu19_x10_60p48g_floor{130..160}.yaml`。本库 `lo.profile` 原样读得进(floor140:60 GHz 处 L(1 MHz) −98.6 dBc/Hz,6 条杂散;占位 ADPLL −80.2)。
   要做:把它作为一个 bundled 配置的 LO(注意文件没有分项,见 P1 #1(b)),重跑示例 01 / 04 看相噪旁瓣(numbers-move)。chirp 仍由两点 ADPLL 逐周期生成,换的只是噪声。
3. **polar_tx#19**(B1 的有效域指标 + `SignSignLMS` 在锯齿上):只是观察,本库不依赖它的结论;B1 有定论前 `ui_per_ref_cycle_p99` 的 495 % 照打。
4. **pll_simulator#76**(CW 整数 N 下 `simulate` 比 `analyze` 带内高 15 dB;`analyze` 没有 TDC 抖动项):本库只在斜坡上用环路,不依赖;它若给 `analyze` 加了 TDC 抖动项,
   本库的剖面分项(`LOProfile.components`)要跟着多一项。

## P1 — 结论的可信度

1. **TDC 量化的鬼目标**(机制与数字见 `cairn/chirp-engine.md`:5 ps TDC 在 ±4.85 m 处 −45.3 dBc,2 ps 时 −54.9 dBc;TDC 抖动占位为 0 时开环路噪声后不消失,见 (a))。
   0.2.4 起它进了虚警账:`StatResult.cfar["ghosts"]` 把每个鬼目标当稳态目标算 Pd(`cairn/cfar-statistics.md`)。还没做的:
   (a) **不是等上游的事,是本库的占位**(2026-11-11 更正):pllsim 的 `TDCConfig.jitter_rms_s` 就是 dither,本库 `build_adpll` 把它留在 0,而且这个 0 不在 `sources.yaml` 里。
       32 chirp、noise=True:TDC 抖动 0 / 1 / 2 ps 时目标多普勒行上 9.85 m 处 −50.3 / −61.6 / −59.7 dBc(noise=False 是 −45.4;1 ps 起已埋进该行的底 −69 dBc 的起伏里)。
       要做:加 `lo.tdc_jitter_s`(占位进 `sources.yaml`,`assumed`),鬼目标表改从带噪声的曲线取(现在取 noise=False 的单 ramp),重写示例 00 / 06 与报表里的鬼目标数;
       CW / 空闲段的带内相噪随之也变(抖动 ≈ 1 LSB RMS 才与线性剖面一致,见 pll_simulator#76)。
   (b) 分工做了(0.2.5,`cairn/chirp-engine.md`)。剩下的:带 `lo.profile` 文件的配置没有分项,noise=False 的曲线仍叠在整份剖面上(LO 底高 1.1 dB);
       默认(noise=False)把量化当成每个 chirp 都相同的图样,统计引擎的相噪底表把它当平滑噪声——总量一致,但鬼目标所在的偏移上时域高 0.4–1.2 dB;
       `run_time(chirp_noise=True)` 最准(对闭式 −0.02 … +0.47 dB)但每个 seed 要重跑逐周期引擎(64 chirp 约 4.5 s)。
   (c) 鬼目标表只列单 ramp 曲线上最强的 6 个;时域图上的电平与它差 1–3 dB,而 Pd 在陡段每 dB 变 0.15:0 dBsm 目标(鬼目标 SNR 9–11 dB)闭式 2.78 个 / 帧,
       时域 8 帧平均 2.00;+4 dBsm 4.78 对 4.12;车 5 对 5。要更准得从整帧的非线性剖面而不是单 ramp 取电平。
   复现:`run_statistical(cfg).cfar["ghosts"]`;时域对照 `run_time(cfg, chirp, seed=s).cfar_detections` 在鬼目标距离 ±1.5 格内有没有格。
2. **polar_tx 的 event 有效域指标在 chirp 上读 495 %**,本库的判断是指标不适用(见 `cairn/chirp-engine.md`)。这是本库的读法,
   已提 polar_tx#19。B1 有定论之前,`ChirpResult.ui_per_ref_cycle_p99` 和报表都把数打出来。

3. **CFAR 的 Pd 闭式在很短的帧上只准到 ±0.07**(`cfar_pd`:阈值按 Gamma(N_eff)、目标自漏与被测格相关取一阶)。N_eff ≥ 24 时对注入单音的蒙卡 ±0.03;
   8 chirp(N_eff 11.8)13 dB 处 0.86 对 0.93,2 × 4 MIMO 每 TX 4 chirp(N_eff 5.2)5 dB 处 0.77 对 0.83。Pfa 用的是精确式,不受影响。
   要做:Pd 也走 Hermitian 型(非中心)的精确式,或在报表里对 N_eff < 20 标"近似"。另:RX 互耦让各通道噪声相关(−16 dB),K 个 look 当独立算,没量过。

## P2 — 一致性与能力

0. **里程碑 2 留下的**(复现:示例 05–08,`cairn/mimo-angle.md`):
   - blanking 之后每 chirp 最后一个样本仍削波(0.1 %):时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,下一个 chirp 的阶跃环回到本 chirp 末尾;
     真实的线性相位抽取滤波器也有前振铃,但长度是它的抽头数不是一整个 chirp。要做因果 / 有限长的 IF 滤波器(所有时域指纹都会动)。
   - TDM 的多普勒补偿在目标格上估单音频率(`doppler_fine_hz`),两目标同距离格同多普勒格时取其合成,各自的角都偏;要做多普勒维的分辨或 BPM-MIMO。
   - `found_targets` 的分格规则只分到格:两目标近于一个距离格(3.75 cm)时仍找同一个峰;那是分辨率,不是 bug,但报表没有标。
   - 泄漏只有直接路径 + 一个反射体,相噪经 τ ≈ 0 几乎全抵消是对的,但发射机的 AM 噪声 / 泄漏的幅度噪声没有模型(mmw60_trx 到位再说)。
1. (0.2.5 了结,见 LOG:时域 SNR 对期望的差 12 个 seed 平均 +0.06 / −0.04 / +0.06 dB(2 / 5 / 10 m),单 seed 标准差 0.10–0.21 dB;原来单 seed 的 −0.07 … −0.10 dB 里有 TDC 量化重复计的一份。)
2. **FFT 上量相噪旁瓣的方差 ±0.3 dB**(64 chirp × ±10 格,Blackman,高斯相位精确谱对照):示例 04 +1 / +2 / +5 m 差 +0.11 / −0.02 / −0.44 dB,
   换 seed 在 ±0.4 dB 内摆。要压到 0.1 dB 需要 10 倍的 chirp 数或直接比残余 PSD(那条已经 0.1 dB)。更近的偏移(< 10 格)要更低旁瓣的窗(Blackman-Harris / Taylor)。
3. **时域引擎按 chirp 独立合成相噪**(块 500k 点,最低 10 kHz),chirp 间 LO 低频相关没有表示;对多普勒维噪底无影响的论证见 `cairn/range-correlation.md`,
   但慢目标 / 长帧(PRF 10 kHz 以下的相噪)没有验证。
4. **性能**:时域引擎 64 chirp × 500k 包络样本约 7 s(4 核);fingerprint 9 s;全套测试约 3 分钟,`test_engines.py` 占一半。

## P3 — 能力扩展

1. GUI 与 Android:`config/form.py` 的表单声明已在,Dash / Chaquopy 都没接。
2. 三角波 / 多斜率 chirp、chirp 间空闲对 ADPLL 的影响(现在 `idle_s` 只是让 LO 停在起始频率)。
3. 77 GHz 档只换了数(`configs/radar_77g_automotive.yaml`,全 assumed),没有任何车载规范的数字。
4. 零中频 IQ 失配(mmw60_trx `IqMismatch` 的面):时域引擎是复包络、没有 IQ 失配,镜像会在 −拍频处出一个鬼目标(幅度 ≈ 失配的 IRR);
   要消费它得先把接收机从"复包络直接砖墙"改成 I / Q 两路。
5. 测角估计器不在 CRLB 上是它自己的选择(`angle_error_budget`):Hann 角窗 ×1.52、多普勒格刻度损失 ×1.09。单目标可以用均匀权(到界 × 刻度损失),
   多普勒维插值取快拍可以去掉刻度损失;多目标同格要 Hann 的旁瓣。现在只有 `mimo.angle_window` 一个开关,没有按目标数自适应,也没有 MUSIC / ESPRIT。

## 边界(有意不做)

- 通信波形、JCAS(以后第三个库 vendor 这两个)。
- 目标跟踪、分类、点云、机器学习;目标运动学(速度在帧内恒定)。
- 天线电磁仿真;信道只有自由空间 + 氧气吸收 + 点目标。
- 改 polar_tx / array_tx / mmw60_trx:需要它们改的报回各自 ROADMAP,合并后重新 pin。

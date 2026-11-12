# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 等上游

1. **mmw60_trx 的前端面**(消费清单已提:mmw60_trx#14,对照它的 main@`4df03852bcfce28054a2d313eeb32ba16bbf0fa9`,它的 ROADMAP D4 在收)。本库 24 条 `source: assumed`
   (12 项 × 两个频段)里:PA(`psat_dbm` / `ScaledRappPA`)与 LO 剖面现在就能用;天线增益有字段无来源;RX 增益 / NF / 压缩点只有 vendored wifitrx 的 sub-7 GHz AGC 梯子;
   TX→RX 隔离没有。等它补上 TX→RX 隔离、60 GHz 的 NF 与压缩点、带来源的天线增益,再按 main 的完整 SHA pin、换占位
   (`cfg.frontend_value(name)` / `leakage_value` 各一处)。
2. **×N 之后的 LO 剖面已经能读,还没用**:pll_simulator#71 / #72 做了倍频器剖面(N²·L_in + 底噪),mmw60_trx 带了
   `pllsim_wu19_x10_60p48g_floor{130..160}.yaml`。本库 `lo.profile` 原样读得进(floor140:60 GHz 处 L(1 MHz) −98.6 dBc/Hz,6 条杂散;占位 ADPLL −79.6)。
   要做:把它作为一个 bundled 配置的 LO(注意文件没有分项,见 P1 #1(b)),重跑示例 01 / 04 看相噪旁瓣(numbers-move)。chirp 仍由两点 ADPLL 逐周期生成,换的只是噪声。
3. **polar_tx#19**(B1 的有效域指标 + `SignSignLMS` 在锯齿上):只是观察,本库不依赖它的结论;B1 有定论前 `ui_per_ref_cycle_p99` 的 495 % 照打。
4. **pll_simulator 的 TDC 抖动改动要经 polar_tx 才到本库**(pll_simulator#76 已关:#77 给 `analyze()` 加了 `tdc_jitter` 项与整数 N 死区提示,#78 把 `simulate()` 里被截掉的
   TDC 抖动改成回绕;main@`5564c64`)。本库跑的是 polar_tx vendored 的 `adpll.py`@d7be4712,要等 polar_tx 更新这份副本(它的 ROADMAP C5,结构性的:上游把逐周期循环搬进了编译内核;
   已在 polar_tx#19 下留言)再重新 pin。到时:本库 `lo.py::_with_tdc_jitter` 见到已有 `tdc_jitter` 就不再加(同一个式子,相对差 2e-16,有测试守着,
   `tests/test_lo.py` 末尾那条断言会在 re-pin 后失败,提醒删掉本条);带噪声的 chirp 曲线与鬼目标的数会小动(numbers-move)。

## P1 — 结论的可信度

1. **TDC 量化在斜坡上的相干杂散(鬼目标)**。0.2.6:TDC 抖动接成占位(1 ps,`assumed`),鬼目标取一帧里开噪声后仍相干的部分,进虚警账(`cairn/chirp-engine.md`、
   `cairn/cfar-statistics.md`)。不抖动 −45.3 dBc;抖动 0 / 1 / 2 ps 时 −49 / −55 dBc / 低于检出限。还没做的:
   (a) 1 ps 这个占位决定了结论(−55 dBc、每帧 0.00 个);它是 `assumed`,等 polar_tx / pll_simulator 的 TDC 实测或文献数。1 ps 时哪几个杂散过检出限随 seed 变
       (seed 1:±9.18、−12.18 m;seed 2:±3.93 m),电平都在 −54 … −56 dBc,离 32 / 64 个 ramp 的检出限(−56 / −59 dBc)只有 1–3 dB。
   (b) 带 `lo.profile` 文件的配置没有分项,曲线保持确定性(noise=False)并叠在整份剖面上:量化算两遍(LO 底高 1 dB),鬼目标是不抖动的 −45 dBc。
   (c) CW / `chirp.idle_s` 空闲段:TDC 抖动 1 ps 时带内相噪仍比线性剖面高(死区):本库 vendored 的副本 +9 … +15 dB,pll_simulator@5564c64(抖动回绕之后)+5.5 … +10.9 dB;
       要到约半个量化格(2.5 ps)才对得上(2 ps:+0.1 … +1.6 dB)。现在空闲段的 LO 误差没有进帧,用了再说。
   复现:`run_statistical(cfg).nonlinearity["ghosts"]` / `["ghosts_quiet"]` / `["ghost_limit_dbc"]`;`python examples/02_chirp_nonlinearity.py` 末尾的表。
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
2. **FFT 上量相噪旁瓣的方差 ±0.3 dB**(64 chirp × ±10 格,Blackman,高斯相位精确谱对照):示例 04 +1 / +2 / +5 m 差 +0.10 / −0.02 / −0.44 dB,
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

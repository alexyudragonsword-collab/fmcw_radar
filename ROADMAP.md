# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 等上游

1. **天线增益与 77 GHz 一档还没有出处**(mmw60_trx#14 的三个面 0.2.8 已消化,见 `cairn/frontend-sources.md`;剩下的不在它那里等,而是没有对口的出处)。
   - 天线增益各 10 dBi 仍是 `assumed`:读到的是封装内 2 dBi(mmw60_trx `rx60.comm_asada2011`)与板上 8 元阵实测约 12 dBi(Adela 2018),MIMO 的单个阵元两者都不是。
     对 SNR 是 1 dB 对 1 dB(两副共 2 dB 对 1 dB):换成 2 dBi,5 m 人体的 51.3 dB 约变 35 dB(按雷达方程算的,没跑)。要一份给"单个贴片 / 封装内阵元在阵里的增益"的出处,或者等 array_tx 给阵元方向图的绝对增益。
   - 77 GHz 一档 15 条全是 `assumed`(0.2.9 加了 `rx_rapp_p`),两个压缩点都沿用拆分前的 −20 dBm;读过的雷达芯片是 60–64 GHz 的。
   - mmw60_trx 的通信前端没有带外压缩点(它的 ROADMAP C9):如果以后雷达要读"同一个 `Frontend60`",得先有这个数。它问过我们有没有通信接收机的出处,没有。
   - 上游表里还有三份没读原文的雷达文档(AOP 手册 SWRS237B、勘误 SWRZ092B、E2E 论坛帖),本库没有用它们的数。

2. **本库自己的 9 条 survey 等 spec_sources 的里程碑 2**(fmcw_radar#13 的"以后"一节):`oxygen.60g_db_per_km` / `oxygen.77g_db_per_km`(ITU-R P.676)、
   `rcs.human_dbsm` / `rcs.car_dbsm` / `rcs.corner_reflector_dbsm`、`window.{rect,hann,hamming,blackman}_3db_bins`(Harris 1978 Table I)现在都是"只读到转述"。
   spec_sources 会把它们迁进去并核对原文,到时另开 issue;本库再把这 9 条改成 `upstream:` 引用(数若因核对而动,是 numbers-move)。
   另:本库新加任何 `upstream:` 引用,要在 spec_sources 开 issue 登记进它的 `consumers.yaml`(它看不到本库的表)。

## P1 — 结论的可信度

1. **TDC 量化在斜坡上的相干杂散(鬼目标)**。0.2.6:TDC 抖动接成占位(1 ps,`assumed`),鬼目标取一帧里开噪声后仍相干的部分,进虚警账(`cairn/chirp-engine.md`、
   `cairn/cfar-statistics.md`)。不抖动 −45.3 dBc;抖动 0 / 1 / 2 ps 时 −49 / −55 dBc / 低于检出限。还没做的:
   (a) 1 ps 这个占位决定了结论(−55 dBc、每帧 0.00 个);它是 `assumed`,等 polar_tx / pll_simulator 的 TDC 实测或文献数。1 ps 时哪几个杂散过检出限随 seed 变,
       也随抖动的实现变(0.2.7 重新 pin 后示例 02 的 32 个 ramp:−11.81、−9.20、+9.19 m,−54.8 … −56.4 dBc;pin 之前是另外三个位置),
       离 32 / 64 个 ramp 的检出限(−56 / −59 dBc)只有 1–3 dB。
   (b) 带 `lo.profile` 文件的配置:0.2.9 起量化只算一次(导出的文件带分项;外来文件在 event 引擎下由剖面加上发生器的两项量化,`cairn/chirp-engine.md`)。
       剩下的:文件下逐周期曲线不开噪声,没有东西给 TDC dither,鬼目标是不抖动的 −45.3 dBc(±4.85 m),一帧里 3–5 m 的底比闭式高 1.3–2.1 dB
       (示例 04 末表,`configs/radar_60g_x10lo.yaml`)。要做:只开 TDC 抖动跑曲线(pllsim 的噪声开关是全开全关,需要它分开),或者在报表里把文件档的鬼目标标成"上限"。
   (c) CW / `chirp.idle_s` 空闲段:TDC 抖动 1 ps 时带内相噪仍比线性剖面高(死区):`simulate − analyze` 在 30 / 100 / 300 kHz 是 +5.5 / +5.9 / +10.9 dB
       (0.2.7 重新 pin 之后经本库 vendored 的副本量的,与在 pll_simulator@5564c64 上量的一致;pin 之前 +9 … +15);要到约半个量化格(2.5 ps)才对得上(2 ps:+0.1 … +1.6 dB)。
       0.2.7 起报表在相噪一节下标出来(`lo.parked_lo` / "The LO while it is not ramping":载波处与斜坡起点各自的 FCW 是否整数、抖动几格、空闲占 PRI 多少,
       附上游 `analyze()` 的原话);默认 config 载波处 FCW 150 在死区,起点 FCW 145 也是。还没做的是**数**:停着时的相噪没有剖面(要用就得从逐周期引擎的 CW 段取),
       空闲段的 LO 误差也没有进帧。判据本身偏保守:2 ps(0.41 格)仍被标,而那里只差 +0.1 … +1.6 dB。
   复现:`run_statistical(cfg).nonlinearity["ghosts"]` / `["ghosts_quiet"]` / `["ghost_limit_dbc"]`;`python examples/02_chirp_nonlinearity.py` 末尾的表。
2. **TDC 按标称周期归一化,斜坡把 DCO 带离标称 ±3.3 %**(`ChirpResult.dco_dev_frac_p99`;polar_tx#19 的答复里点出的效应,它推断"在锯齿上被环路吃掉",
   在本库的配置上量了,不成立)。vendored 的 `_sim_tdc` 用 `code / cpp_nom` 把 TDC 码换成小数周期,读数差 `小数 × Δf/f`。默认 config、匹配增益、noise=False:
   斜坡频率误差 513.8 kHz RMS(载波处);把那一行临时改成按实际周期归一化(不入库的改动)是 498.4 kHz,飞回后初始误差 400 → 200 kHz,
   最强静态鬼目标 −45.7 → −48.1 dBc。不改 vendored 代码也能复现:给 `ADPLL.simulate` 传 vendored 的 `TdcPeriodCal`(EMA 1e-3 / 1e-2 / 1e-1 → 507.1 / 500.7 / 499.6 kHz)。
   开噪声(TDC 抖动 1 ps、32 个 ramp)时看不出差别:鬼目标本来就贴着检出限(−55.4 dBc 对检出限 −55.9;开 `TdcPeriodCal` −54.9 … 无)。
   所以它只影响"不抖动的图样"那一列和 P1 #1(b) 的文件剖面配置。真实 ADPLL 按固定周期归一化也有这一项,所以保持建模;
   要做(如果做):`lo.tdc_period_cal`(None / EMA 系数)接 vendored 的校准器,并说明带噪声时它自己的测量噪声(0.5 码 RMS)。

3. **CFAR 的 Pd 闭式在很短的帧上只准到 ±0.07**(`cfar_pd`:阈值按 Gamma(N_eff)、目标自漏与被测格相关取一阶)。N_eff ≥ 24 时对注入单音的蒙卡 ±0.03;
   8 chirp(N_eff 11.8)13 dB 处 0.86 对 0.93,2 × 4 MIMO 每 TX 4 chirp(N_eff 5.2)5 dB 处 0.77 对 0.83。Pfa 用的是精确式,不受影响。
   要做:Pd 也走 Hermitian 型(非中心)的精确式,或在报表里对 N_eff < 20 标"近似"。另:RX 互耦让各通道噪声相关(−16 dB),K 个 look 当独立算,没量过。

4. **接收机压缩模型的三处没有出处、一处没建模**(0.2.9 起两级 Rapp 在两个引擎里,`link/compression.py`、`cairn/frontend-sources.md`)。默认档泄漏比带外压缩点高 4 dB:
   回波 −10.65 dB、热噪声 −8.35 dB、SNR −2.3 dB(含 ADC 量化 −2.7),两个引擎差 ≤ 0.35 dB。剩下的:
   (a) 带外 P1dB 的读法:本库当成那一级自己的 1 dB 点;若手册指的是"使带内增益降 1 dB 的阻塞电平",那一级自己的点要高 2.7 dB(p = 2),效应全部变弱。手册只给了测试信号。
   (b) 膝部 `rx_rapp_p` = 2 是占位:同一个 1 dB 点下 p = 1 / 2 / 3 → 回波 −5.9 / −10.65 / −12.2 dB、SNR −0.5 / −2.3 / −2.9 dB。
   (c) 统计引擎只算泄漏造成的压缩,不算强目标自己的:1 m 处的车(P_r −37 dBm,离带内点 3 dB)时域峰值 −0.29 dB,统计引擎 0。高通的飞回瞬态经第二级的压缩也不在预算里(被 blank 掉的那段)。
   (d) NF 取表值 12 dB 不随增益变,图 7-2 上 40 dB 增益是 11.0 dB(差 1 dB,没接)。
   复现:`tests/test_compression.py`;`python examples/08_tx_leakage.py` 的预算表(五行"receiver compression")。

## P2 — 一致性与能力

0. **里程碑 2 留下的**(复现:示例 05–08,`cairn/mimo-angle.md`):
   - blanking 之后每 chirp 末尾仍有样本削波(默认 1 个、0.1 %;线性接收机在有出处的泄漏电平下 3 个、0.3 %):时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,下一个 chirp 的阶跃环回到本 chirp 末尾;
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

6. numba 可选加速:polar_tx b007e60 起 vendored 的逐周期循环是 `@kernel`,装了 numba 就编译。本库的 `flyback_dp_step` 也是;手工核过编译与解释逐位一致
   (在线 / 离线 / 带噪声三条 chirp 的 `f_err` 与校准轨迹哈希相同),带噪声的 3 chirp 0.82 → 0.08 s。还没有 `[fast]` extra,也没有 polar_tx `test-jit` 那样的 CI 作业守着。

## 边界(有意不做)

- 通信波形、JCAS(以后第三个库 vendor 这两个)。
- 目标跟踪、分类、点云、机器学习;目标运动学(速度在帧内恒定)。
- 天线电磁仿真;信道只有自由空间 + 氧气吸收 + 点目标。
- 改 polar_tx / array_tx / mmw60_trx:需要它们改的报回各自 ROADMAP,合并后重新 pin。

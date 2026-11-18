# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 等上游

1. **接收天线增益与 77 GHz 一档还没有出处**(mmw60_trx#14 的三个面 0.2.8 已消化,见 `cairn/frontend-sources.md`;剩下的不在它那里等,而是没有对口的出处)。
   - 天线增益各 10 dBi 仍是 `assumed`:读到的是封装内 2 dBi(mmw60_trx `rx60.comm_asada2011`)、封装内 6 dBi(spec_sources `antenna60.okada2013_dbi`,0.6.0 起读过原文:
     通信收发机收、发各一个有机封装天线)与板上 8 元阵实测约 12 dBi(Adela 2018),MIMO 的单个阵元三者都不是。
     **0.2.19 起这个不确定只剩接收侧**(`cairn/regulatory-compliance.md`):合规的雷达 EIRP 被 §15.255(c)(2) 的上限钉住,默认档(12 dBm、58–62 GHz、14 dBm 上限)
     发射天线 2 / 6 / 10 dBi 按上限的 SNR 逐位相同(43.34 dB,`test_under_the_cap_the_tx_antenna_gain_stops_mattering`);`rx_gain_dbi` 仍 1 dB 对 1 dB:
     8 / 10 / 12 dBi → 41.34 / 43.34 / 45.34 dB。20 dBm 的档发射天线要到 8 dBi 才被钉住。
     要一份给"单个贴片 / 封装内阵元在阵里的接收增益"的出处,或者等 array_tx 给阵元方向图的绝对增益。按配置(不按上限)的那一列里发射天线仍 1 dB 对 1 dB。
   - 77 GHz 一档 15 条全是 `assumed`(0.2.9 加了 `rx_rapp_p`),两个压缩点都沿用拆分前的 −20 dBm;读过的雷达芯片是 60–64 GHz 的。
   - mmw60_trx 的通信前端没有带外压缩点(它的 ROADMAP C9):如果以后雷达要读"同一个 `Frontend60`",得先有这个数。它问过我们有没有通信接收机的出处,没有。
   - 上游表里还有三份没读原文的雷达文档(AOP 手册 SWRS237B、勘误 SWRZ092B、E2E 论坛帖),本库没有用它们的数。

2. **本库新加的 `upstream:` 引用要在 spec_sources 登记**(它看不到本库的表):0.2.13 起本库已没有 `survey` 条目(fmcw_radar#19),
   以后新加任何 `upstream:`,在 spec_sources 开 issue 登记进它的 `consumers.yaml`。
3. **信道不含水汽**(0.2.11 起氧气按 P.676 干空气算)。77 GHz 处水汽(标准大气 7.5 g/m³)约 0.25 dB/km,是氧气(0.091)的近 3 倍,但 25 m 目标往返只多约 0.01 dB;
   60 GHz 处水汽 0.15 dB/km,约为氧气的 1 %。要做(若有长距离 77 GHz 场景):spec_sources 补 P.676 Table 2 与水汽那一支(它提过:原文图 1 的 1013.25 hPa 是总压还是干空气压没说,
   湿空气下 60 GHz 两种读法差 0.12 dB/km),本库加 `channel.water_vapour_g_m3`。

## P0 — 待用户决定

0. **默认配置不合规,怎么改**(0.2.19 的检查查出来的,`cairn/regulatory-compliance.md`,示例 09;这一轮没有改任何现有数字)。
   `radar_60g_sensing.yaml`(以及 mimo / x10lo / dither 三个同频段的配置):58–62 GHz、EIRP 22 dBm,对 47 CFR §15.255(c)(2) 的 57–64 GHz 档(14 dBm)超 8.0 dB;
   没有声明帧周期,而这一档要求任意 33 ms 里关断 ≥ 25.5 ms(6.4 ms 的帧:帧周期 ≥ 31.9 ms,≤ 31.3 帧/秒)。三个选项:
   (a) 按上限降 EIRP:58–62 GHz 不变,EIRP 22 → 14 dBm,声明帧周期。5 m 人体格点 SNR 51.34 → 43.34 dB,所有带 SNR、P_r、目标电平、时域帧的文档数字都动 8 dB;
       鬼目标每帧 2.75 个会变少(鬼目标的 SNR 跟着降 8 dB,没重算);分辨率、相噪、chirp 的数不动。
   (b) 换频段:57–61.56 GHz(B 4.56 GHz,分辨率 5.39 → 4.73 cm,上限 20 dBm,关断 ≥ 16.5 ms → ≤ 68.3 帧/秒),EIRP 22 → 20 dBm,SNR 约 −2 dB;
       或 57–59.4 GHz 室内(20 dBm、没有关断要求,但 B 只有 2.4 GHz,分辨率 8.98 cm,要声明 `regulatory.scenario: indoor`)。
       换频段动的最多:中心频率、DCO 频率(FCW 不再是整数 150 → 停泊死区那一节的结论也变)、扫频斜率、最大距离、分辨率、全部 SNR 与 chirp / 相噪的数。贴边的扫频在实物上还要留保护带。
   (c) 保持数据手册的 12 dBm 与 10 dBi 占位不动,报表里标明超限(现在就是这个状态):文档数字都不动,但默认配置描述的是一颗不能在美国按这一节上市的雷达。
   不为了过合规去改 `assumed` 的天线增益(用户定的)。定了以后单独一个 numbers-move 的 PR。

## P1 — 结论的可信度

1. **TDC 量化在斜坡上的相干杂散(鬼目标)**。0.2.6:TDC 抖动接成占位(1 ps,`assumed`),鬼目标取一帧里开噪声后仍相干的部分,进虚警账(`cairn/chirp-engine.md`、
   `cairn/cfar-statistics.md`)。0.2.12 起 60 GHz 的 TDC 是原文的 12.2 ps(spec,fmcw_radar#17),结论翻了:不抖动 −34.1 dBc(−10.31 / ±2.81 m);
   抖动 0 / 0.5 / 1 / 2 ps 时 −35.7 / −36.3 / −37.5 / −41.1 dBc,全在 32 个 ramp 的检出限(−52 … −56 dBc)之上(示例 02)。还没做的:
   (a) **默认配置每帧 2.75 个鬼目标检出**(5 m 人体,鬼目标 SNR +11 … +13.6 dB;示例 00 主瓣外 35 格对 0.2.11 的 22 格;四目标帧里 +10 dBsm 的车把超门限格从 70 推到 284,示例 05)。
       原因:1 ps 抖动只有 12.2 ps 的 0.08 格,打不散量化(5 ps 时 0.2 格,−55 dBc、每帧 0.00 个)。抖动没有出处(spec_sources 查过 Wu 2014 与 Staszewski 2006 原文,都没给),
       不为了压鬼目标去调它。同一个原因让斜坡上的误差不再是随机噪声:16 个斜坡时 300 kHz 处相干分量 −1.3 dB(纯随机 −12;半格抖动回到随机水平),
       这就是一帧积出鬼目标的部分。**更正(0.2.15,pll_simulator#80)**:0.2.12 这里写"逐周期引擎对剖面 100 / 300 kHz 差 −3.5 / +3.4 dB",那是单个 seed、±25 % 频带的读数,
       ±15 % 频带、seed 7–9 是 −0.7 … −3.3 dB;电平随读法变,稳的是相干分量。
       `tests/test_lo_noise_split.py::test_the_default_tdc_is_not_dithered_enough_for_the_profile`。12.2 ps 下扫抖动(默认 64 chirp,`run_statistical`):1 / 1.8 / 2.44 / 3 ps(0.08 / 0.15 / 0.20 / 0.25 格)→ 最强 −37.3 / −39.5 / −42.0 / −44.7 dBc,
       每帧 2.75 / 2.08 / 0.92 / 0.16 个,L(1 MHz) −75.9 / −75.4 / −74.8 / −74.3 dBc/Hz。
       **0.2.17:扣除式 TDC dither 接进了配置**(`lo.tdc_dither_lsb`、`lo.tdc_dither_gain_error`;pll_simulator#80,`cairn/chirp-engine.md`),**默认关**:
       默认配置的鬼目标仍是结论(每帧 2.75 个),因为"这颗 60 GHz ADPLL 有扣除式 dither"没有出处。开了以后(`configs/radar_60g_dither.yaml`,1 LSB):
       每帧 0.002 个、最强 −50.9 dBc,3 LSB 时检出限以上没有;L(1 MHz) 不动;相干分量回到随机水平(`tests/test_tdc_dither.py`)。还没做的:
       - 默认要不要开:要一份出处(这类 FMCW ADPLL 用不用参考路径 DTC 的扣除式 dither、几个 LSB)。TDC 自身抖动的出处两边都没有,1 ps 仍是占位。
       - 1 LSB / 2 LSB 时还剩几条 −50 … −54 dBc 的相干杂散贴着检出限(2 LSB 是一对 ±4.68 m);对虚警无影响,来源没查(每周期 5.46 码不是整数,dither 的白化不严格)。
       - DTC 自身的抖动与 INL 没有建模(上游写明的边界);`tdc_dither_gain_error` 只有增益误差一项。
       - 上游不做 FCW 的 Σ-Δ 与周期性偏移;`dtc_bbpd` 接 `mod_freq`(换成 DTC + BBPD 架构)本库说了暂不需要。
       0.2.7 重新 pin 后鬼目标的位置随 seed 与抖动的实现变;12.2 ps 下 −10.31 / ±2.81 / ±8.43 / −14.05 m 在 0 … 2 ps 间稳定。
   (b) 带 `lo.profile` 文件的配置:0.2.9 起量化只算一次(导出的文件带分项;外来文件在 event 引擎下由剖面加上发生器的两项量化,`cairn/chirp-engine.md`)。
       剩下的:文件下逐周期曲线不开噪声,没有东西给 TDC dither,鬼目标是不抖动的 −34.1 dBc(−10.31 / ±2.81 m;5 ps 时 −45.3 dBc @ ±4.85 m),一帧里 1–5 m 的底比闭式高 −1.5 … +3.2 dB(均 +0.9)
       (示例 04 末表,`configs/radar_60g_x10lo.yaml`)。**0.2.17 起有解法**:扣除式 dither 在 `noise=False` 下也生效,文件档开 1 LSB 后每帧 2.96 → 0.002 个,
       鬼目标从 63 个不开噪声但抖动的 ramp 上搜(`test_dither_works_under_a_noise_file_too`)。剩下的:不开 dither 时仍是不抖动的图样(现状,如实报);
       只开 TDC 抖动跑曲线仍做不到(pllsim 的噪声开关是全开全关)。
   (c) CW / `chirp.idle_s` 空闲段:TDC 抖动 1 ps 时带内相噪仍比线性剖面高(死区):12.2 ps TDC 上 `simulate − analyze` 在 30 / 100 / 300 kHz 是 +15.5 / +19.2 / +9.8 dB
       (0.08 格;抖动 0 / 3 / 5 / 6.5 ps 时均值 +18.8 / +4.2 / +0.9 / +1.1);要到约半个量化格(6.1 ps)才对得上。5 ps TDC 时是 +5.5 / +5.9 / +10.9 dB,
       半格 2.5 ps(0.2.7 重新 pin 之后经本库 vendored 的副本量的,与在 pll_simulator@5564c64 上量的一致;pin 之前 +9 … +15)。
       0.2.7 起报表在相噪一节下标出来(`lo.parked_lo` / "The LO while it is not ramping":载波处与斜坡起点各自的 FCW 是否整数、抖动几格、空闲占 PRI 多少,
       附上游 `analyze()` 的原话);默认 config 载波处 FCW 150 在死区,起点 FCW 145 也是。还没做的是**数**:停着时的相噪没有剖面(要用就得从逐周期引擎的 CW 段取),
       空闲段的 LO 误差也没有进帧。判据本身偏保守:0.41 格仍被标,而那里只差 +0.9 dB(12.2 ps 上的 5 ps;5 ps TDC 上的 2 ps:+0.1 … +1.6 dB)。
       **0.2.17,扣除式 dither 对停泊段**:1 LSB 把 +14.9 dB 降到 +2.8 dB(30 / 100 / 300 kHz +3.6 / +1.7 / +3.2),没到 1 dB——12.2 ps 每个 DCO 周期 5.46 个码,
       边沿那一格只有 0.46 LSB 宽,白化的前提不成立(pll_simulator 量到 +2.4 … +2.9);3 LSB +0.65 dB(+0.8 / +0.5 / +0.6)。判据跟着走:1 LSB 是 0.30 格 RMS,仍被标;
       2 LSB 以上不标。所以要让停泊段能用线性剖面,dither 取 3 LSB(`test_parked_lo_wants_three_lsb`)。
   复现:`run_statistical(cfg).nonlinearity["ghosts"]` / `["ghosts_quiet"]` / `["ghost_limit_dbc"]`;`python examples/02_chirp_nonlinearity.py` 末尾的两张表(抖动、dither)。
2. **TDC 按标称周期归一化,斜坡把 DCO 带离标称 ±3.3 %**(`ChirpResult.dco_dev_frac_p99`;polar_tx#19 的答复里点出的效应,它推断"在锯齿上被环路吃掉",
   在本库的配置上量了,不成立)。vendored 的 `_sim_tdc` 用 `code / cpp_nom` 把 TDC 码换成小数周期,读数差 `小数 × Δf/f`。以下是 5 ps TDC 时(0.2.11 及以前)量的,
   12.2 ps 下没重量(那里鬼目标已在检出限之上 15 dB 以上,这一项相对小)。默认 config、匹配增益、noise=False:
   斜坡频率误差 513.8 kHz RMS(载波处);把那一行临时改成按实际周期归一化(不入库的改动)是 498.4 kHz,飞回后初始误差 400 → 200 kHz,
   最强静态鬼目标 −45.7 → −48.1 dBc。不改 vendored 代码也能复现:给 `ADPLL.simulate` 传 vendored 的 `TdcPeriodCal`(EMA 1e-3 / 1e-2 / 1e-1 → 507.1 / 500.7 / 499.6 kHz)。
   开噪声(TDC 抖动 1 ps、32 个 ramp)时看不出差别:鬼目标本来就贴着检出限(−55.4 dBc 对检出限 −55.9;开 `TdcPeriodCal` −54.9 … 无)。
   所以它只影响"不抖动的图样"那一列和 P1 #1(b) 的文件剖面配置。真实 ADPLL 按固定周期归一化也有这一项,所以保持建模;
   要做(如果做):`lo.tdc_period_cal`(None / EMA 系数)接 vendored 的校准器,并说明带噪声时它自己的测量噪声(0.5 码 RMS)。
   **0.2.17**:开了扣除式 dither 以后这一项不再是图样,是剖面里的一项噪声 `tdc_dither_mod`(比 `tdc_quant` 低 19.4 dB,Hann 距离窗加权后低 25.6 dB,
   `test_profile_carries_what_the_subtraction_leaves`);不开 dither 时上面的描述不变。

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

5. **目标 RCS 是一个常数,不随距离、视角、频段变**(fmcw_radar#19 读原文时看出来的)。
   (a) 乘用车 10 dBsm 是 ISO 19206-3 车尾、40 m 以外那条带子的下界(带子中心 20);ISO 的中心近处按 20 − 0.013·(D − 40)² 下降,15 / 10 / 5.3 m 约 11.9 / 8.3 / 4.3 dBsm。
       示例 05 的车在 5.3 m,按 ISO 中心应比本库低约 5.7 dB。侧面(90°,30 m)是 13–30 dBsm,本库没有视角。
   (b) 角反射器 20 dBsm 两个频段共用:按 Doerry 式 (1),同一个反射器 77 GHz 比 60 GHz 多 2.17 dB(本库把 77 GHz 档读成 13.8 cm 的反射器)。
   要做(若需要):目标按"种类 + 尺寸 / 视角"给,RCS 由 λ 与距离算(三面角 4πa⁴/(3λ²);车按 ISO 的带子中心或上下界);现在的常数是一个保守的单点。
   复现:`tests/test_sources.py::test_the_last_surveys_are_read_from_the_originals`;`spec_sources:target_rcs.iso19206_3_car_rear` / `target_rcs.trihedral_peak`。

6. **规管检查里本库自己的读法**(0.2.19,`link/compliance.py` 的 `READINGS`,报表逐条写明;条文原文没有):
   (a) 关断被 33 ms 窗口截断时怎么计:本库按"自身连续 ≥ 2 ms 的关断,落在窗口里的部分计入"。另一种读法(截下来的片段也要 ≥ 2 ms)多扣最多 4 ms,
       6.4 ms 的帧在 14 dBm 档(33 − 6.4 − 4 = 22.6 < 25.5 ms)任何帧率都不合规。要一份 FCC 的测量规程或 KDB 的说法。
   (b) 占用带宽取指令的扫频范围,没有 (f) 要求的温度 / 电压余量,也没算飞回的过冲;贴边的档(57–61.56、57–59.4 GHz)在实物上要保护带,本库没有量化。
   (c) 多发射通道:TDM 按单通道;若以后做同时发射(DDM / 波束成形),条文没有说怎么合计,(h) 还禁止外部锁相输入的波束成形阵。
   (d) 峰值 EIRP 的测量带宽没有;本库拿配置的 `tx_power_dbm`(手册典型值)当峰值传导功率。
   (e) 只读了美国的 §15.255;欧洲(ETSI)等没有条目。61.0–61.5 GHz 档的档外限值、无人机档的高度、换档停 33 ms 没建模。
   复现:`tests/test_compliance.py`;`python examples/09_band_tradeoff.py`;报表的"Regulatory check"一节。

## P2 — 一致性与能力

0. **里程碑 2 留下的**(复现:示例 05–08,`cairn/mimo-angle.md`):
   - blanking 之后每 chirp 末尾仍有样本削波(默认 1 个、0.1 %;线性接收机在有出处的泄漏电平下 3 个、0.3 %):时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,下一个 chirp 的阶跃环回到本 chirp 末尾;
     真实的线性相位抽取滤波器也有前振铃,但长度是它的抽头数不是一整个 chirp。要做因果 / 有限长的 IF 滤波器(所有时域指纹都会动)。
   - TDM 的多普勒补偿在目标格上估单音频率(`doppler_fine_hz`),两目标同距离格同多普勒格时取其合成,各自的角都偏;要做多普勒维的分辨或 BPM-MIMO。
   - `found_targets` 的分格规则只分到格:两目标近于一个距离格(3.75 cm)时仍找同一个峰;那是分辨率,不是 bug,但报表没有标。
   - 泄漏只有直接路径 + 一个反射体,相噪经 τ ≈ 0 几乎全抵消是对的,但发射机的 AM 噪声 / 泄漏的幅度噪声没有模型(mmw60_trx 到位再说)。
1. (0.2.5 了结,见 LOG:时域 SNR 对期望的差 12 个 seed 平均 +0.06 / −0.04 / +0.06 dB(2 / 5 / 10 m),单 seed 标准差 0.10–0.21 dB;原来单 seed 的 −0.07 … −0.10 dB 里有 TDC 量化重复计的一份。)
2. **FFT 上量相噪旁瓣的方差 ±0.3 dB**(64 chirp × ±10 格,Blackman,高斯相位精确谱对照):示例 04 +1 / +2 / +5 m 差 +0.11 / −0.04 / −0.45 dB(5 ps TDC 时 +0.10 / −0.02 / −0.44),
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

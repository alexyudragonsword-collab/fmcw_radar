# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

## 等上游

1. **mmw60_trx 有前端了,但它是通信前端:先写雷达消费清单,再谈换占位**。mmw60_trx main@`caebcde6552ee6f621cdbe5846616266958a02dd`(0.1.0)
   的 `src/mmw60/frontend/` 有 `Frontend60`(`ScaledRappPA`、`Lo60`、`ConverterLaw`、`IqMismatch`、`EirpLimit`)。本库 24 条 `source: assumed`
   (`grep -c "source: assumed" src/fmcw_radar/data/sources.yaml`,12 项 × 两个频段)里它只能供 PA、LO 泄漏、LO 剖面形状;天线增益、LNA NF、
   TX–RX 隔离、倍频器自身底噪它没有。接口按前端对象写(`cfg.frontend_value(name)` / `leakage_value` / `coupling_c1` 各一处换):等它补上缺的面,
   再按 main 的完整 SHA pin、换占位、重新 pin。下面这张表是消费清单,可直接贴进 mmw60_trx `ROADMAP.md` 的 D 节(由用户转):

   > **fmcw_radar(雷达姊妹库,与 mmw60_trx@caebcde 对照)要从 `Frontend60` 消费的面**,每项是 fmcw_radar `sources.yaml` 的一条 `assumed` 占位(60 GHz 档的数),
   > "供"= 现有字段可直接读,"部分"= 有字段但语义不同或没有 60 GHz 的数,"缺"= 没有这个面:
   >
   > | fmcw_radar 占位(60g_sensing) | 占位值 | `Frontend60` 的对应 | 状态 |
   > |---|---|---|---|
   > | `tx_power_dbm` | 10 dBm | `psat_dbm`、`pa_gain_db`、`ScaledRappPA.p1db_out_dbm()`、Rapp 的 p / q1 / q2;`target_pout_dbm()` = Psat − OBO | 供。chirp 是恒包络,工作点在 P1dB 附近而不是 OBO 8 dB,fmcw_radar 自己取回退量 |
   > | `tx_gain_dbi` | 10 dBi | `antenna_gain_dbi`(默认 0,只进 `EirpLimit.check`) | 部分:有字段无来源 |
   > | `rx_gain_dbi` | 10 dBi | — | 缺 |
   > | `rx_gain_db`(RX 链增益) | 40 dB | wifitrx `RxParams.lna_states`(AGC 档位表) | 部分:是 AGC 梯子,不是 60 GHz LNA 的数 |
   > | `nf_db`(RX NF) | 10 dB | — | 缺 |
   > | `p1db_dbm`(RX 输入 P1dB) | −20 dBm | `RxParams.nonlin_enabled` 有开关,数是 wifitrx 的(未核实是否 60 GHz) | 缺 |
   > | `lo_mult`(×N) | 4 | `Lo60` 只有 `carrier_hz` + `profile`;×N 在拓扑 A(A1),倍频器底噪已报 pll_simulator(D 节) | 缺 |
   > | `dco_pn_dbchz`、`dco_pn_floor_dbchz` | −95 / −140 dBc/Hz | `Lo60.profile`(`NoiseSource`,`from_pole_zero`)是载波处的剖面形状 | 供(载波剖面):fmcw_radar 经 `lo.profile` 文件消费;DCO 自身与 TDC 不在它那 |
   > | `tdc_res_s` | 5 ps | — | 缺(ADPLL 内部量,属 polar_tx / pll_simulator) |
   > | `tx_rx_isolation_db` | 25 dB | `Lo60.tx_leak_dbc` 是 LO 到调制器输出的泄漏,不是 TX→RX 天线隔离 | 缺;`tx_leak_dbc` 可作泄漏预算的第三项(LO 泄漏经同一隔离进 RX) |
   > | `rx_coupling_c1_db`(阵元互耦) | −16 dB | — | 缺(阵列是 array_tx 的面) |
   >
   > 另外两项 fmcw_radar 没有占位但可以直接消费:`EirpLimit`(avg / peak dBm、频段、`source`)对照本库的 EIRP 20 dBm;`ConverterLaw.bits(fs)`(ENOB 随采样率)对照 `rx.adc_bits`。
   > `IqMismatch`(零中频 IQ)本库现在不消费:时域引擎是复包络无 IQ 失配,镜像会在 −拍频处出鬼目标,记在 fmcw_radar P3。
   > **请 mmw60_trx 补的面(按优先级)**:RX NF 与输入 P1dB(60 GHz LNA)、TX / RX 天线增益(有来源的数)、TX→RX 隔离(dB,同一封装 / 天线);
   > 倍频器 ×N 与底噪已在 D 节报 pll_simulator,两个消费方。

## 报回上游(等用户转;本库不动那两个库,合并后重新 pin)

格式按对方 ROADMAP:复现方式、数字、本库哪个测试 / 示例在等它。

1. **给 polar_tx ROADMAP B1(event 引擎的有效域指标)**:
   > **fmcw_radar 的观察(chirp,15 GHz DCO、1 GHz 斜坡、fref 100 MHz;polar_tx@7057738 的 `adpll.py`@d7be4712)**:
   > 每参考周期相位推进指标读 **4.95 UI/周期(495 %)**——按声明域 event 引擎在任何现实 chirp 上都无效(fref 提到 1 GHz 也是 50 %)。
   > 但逐周期引擎在斜坡上与线性化引擎逐周期一致:5 % 两点失配的飞回瞬态,飞回后前 40 个周期的误差比值 **1.005 ± 0.046**,初始误差 199.4 vs 200.0 MHz;
   > 匹配增益时 event 只剩 TDC + DCO 量化底 0.54 MHz RMS(载波处)。fmcw_radar 的判断:指标针对亚周期相位轨迹(GFSK / OFDM 要 TDC 在一个 DCO 周期内分辨相位),
   > 频率斜坡是环路本职(分数 FCW 就是斜坡),**建议 B1 把有效域按"亚周期相位轨迹"和"频率斜坡"分开写**,或给指标加一个"斜坡分量先扣掉"的变体。
   > 复现:`fmcw_radar` `python examples/02_chirp_nonlinearity.py`;`tests/test_chirp.py::test_validity_metric_is_measured_and_far_outside_polar_tx_domain`、
   > `::test_event_and_response_engines_agree_on_the_transient`。等它的:`ChirpResult.ui_per_ref_cycle_p99` 与报表里的 495 % 一直打出来,直到 B1 有定论。
   >
   > **附:`dp_cal` 的在线 `SignSignLMS` 在锯齿 chirp 上往错方向走**(同一 config,+5 % 失配,mu 2e-5,20 个 chirp):1.05 → **1.066**。
   > 原因:斜坡的 EMA 居中回归量几乎恒正,而失配留下的是二阶环对斜坡的常数稳态相位误差,去直流后与回归量不相关——信息只在飞回后 ~25 个参考周期里
   > (Δe 比匹配时多 +0.47 UI,逐周期衰减到 0.03 UI 的量化底;50–200 周期是符号相反的过冲)。差分 sign-sign 能收敛但慢(1.05 → 1.006 / 20 chirp);
   > 离线 LS(`estimate_dp_gain_error`)喂 ≥ 2 个连续 chirp 一次到位(估 4.995 %,单 chirp 只到 2.5 %)。fmcw_radar 的处理:离线 LS 为主、自己的
   > `ChirpFlybackLMS`(飞回后 20 周期、幅值加权)在线,四个 chirp 内 ±5 % → ±0.05 %,无偏;不改 polar_tx。这不是 polar_tx 的 bug——`dp_cal` 的契约是
   > 调制信号居中回归,chirp 不满足——只建议在 `dp_cal` 的 docstring 里写明"回归量须零均值;频率斜坡不适用"。
   > 复现:`tests/test_chirp.py::test_online_calibration_converges_in_a_few_chirps_from_both_sides`、`cairn/chirp-engine.md`"dp_cal 在锯齿 chirp 上"。

2. **给 pll_simulator(`docs/roadmap.md`)**:
   > **TDC dither**(fmcw_radar P1 #1(a)):`TDCConfig` 只有 INL / 抖动,没有 dither。TDC 量化在 chirp 上出确定性鬼目标:fmcw_radar 默认 config
   > (15 GHz DCO、1 GHz 斜坡、fref 100 MHz、5 ps TDC)5 m 目标在 **±4.85 m 处 −45.3 dBc**,2 ps TDC 时 **−54.9 dBc**;随 TDC 分辨率变、不随 Kdco 变、
   > 开环路噪声后不消失(2.2 / 7.81 m 处 −49 dBc)。要一个 dither(或亚 LSB 噪声注入)选项把它打散成底噪。
   > 复现:`fmcw_radar` `run_statistical(RadarConfig()).nonlinearity["ghosts"]`,`tests/test_engines.py::test_tdc_ghost_targets_are_reported_and_scale_with_the_tdc`,示例 00 / 02。
   > 等它的:fmcw_radar ROADMAP P1 #1(a);`StatResult.nonlinearity["ghosts"]` 在那之前是悲观一侧。
   >
   > **倍频器 ×N 模型,含 20·log₁₀N 之外的自身底噪**(两个消费方):mmw60_trx ROADMAP D 节已提(拓扑 A 的 LO 链);fmcw_radar 的 LO 是
   > 15 GHz ADPLL ×4 到 60 GHz,现在倍频器理想(相噪 +20 log N,`lo_mult` 占位 `assumed`),剖面在 fref/2 以上取 DCO 自身。
   > 等它的:fmcw_radar `LOProfile.from_config`(`lo.py`)一处换;示例 01 / 04 的相噪旁瓣数会动(numbers-move)。

## P1 — 结论的可信度

1. **TDC 量化的鬼目标:统计引擎现在报它,但 CFAR / Pd 的闭式仍不含它**。32 chirp 帧、5 m 目标:无噪声 event 引擎 9.87 m 处 −45.5 dBc(5 ps TDC;2 ps 时 −55.8 dBc),
   开环路噪声后 2.2 / 7.81 m 处 −49 … −50 dBc(两个 seed 同位置)。机制与数字见 `cairn/chirp-engine.md`。0.1.1 起 `StatResult.nonlinearity["ghosts"]`
   从单 ramp 的曲线列出它(±4.85 m,−45.3 dBc,与距离–多普勒图 3 dB 内一致),报表有一张表;示例 00 的 CFAR 仍在主瓣外报 12 格,因为 Pd / Pfa 的闭式只认高斯噪底。
   要做:(a) TDC dither(pllsim 没有,报回 pll_simulator);(b) chirp 引擎带噪声时与 `LOProfile` 的分工(环内由逐周期引擎、环外由剖面)以免重复计相噪;
   (c) 示例 06 的 CFAR 曲线仍只对高斯噪底(蒙卡与闭式都是),确定性杂散没算进虚警。
   复现:`run_statistical(cfg).nonlinearity["ghosts"]`;时域对照 `run_time(cfg, ..., phase_noise=False, noise=False, quantise=False)` 看 rd_db 离目标 ±40 格外的最大值。
2. **polar_tx 的 event 有效域指标在 chirp 上读 495 %**,本库的判断是指标不适用(见 `cairn/chirp-engine.md`)。这是本库的读法,
   报回条目已写在上面"报回上游"#1(等用户转到 polar_tx ROADMAP B1)。B1 有定论之前,`ChirpResult.ui_per_ref_cycle_p99` 和报表都把数打出来。

## P2 — 一致性与能力

0. **里程碑 2 留下的**(复现:示例 05–08,`cairn/mimo-angle.md`):
   - blanking 之后每 chirp 最后一个样本仍削波(0.1 %):时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,下一个 chirp 的阶跃环回到本 chirp 末尾;
     真实的线性相位抽取滤波器也有前振铃,但长度是它的抽头数不是一整个 chirp。要做因果 / 有限长的 IF 滤波器(所有时域指纹都会动)。
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
4. 零中频 IQ 失配(mmw60_trx `IqMismatch` 的面):时域引擎是复包络、没有 IQ 失配,镜像会在 −拍频处出一个鬼目标(幅度 ≈ 失配的 IRR);
   要消费它得先把接收机从"复包络直接砖墙"改成 I / Q 两路。

## 边界(有意不做)

- 通信波形、JCAS(以后第三个库 vendor 这两个)。
- 目标跟踪、分类、点云、机器学习;目标运动学(速度在帧内恒定)。
- 天线电磁仿真;信道只有自由空间 + 氧气吸收 + 点目标。
- 改 polar_tx / array_tx / mmw60_trx:需要它们改的报回各自 ROADMAP,合并后重新 pin。

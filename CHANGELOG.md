# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.2.10] — 2026-11-13 — 前端的五个数改读共享库 spec_sources(只搬家,数不动)

- fmcw_radar#13(spec_sources 发起):vendor spec_sources@`d7b4d1e` 的 `reader.py` 与 `data/frontend60.yaml`(`vendor/spec_sources/`);
  删掉 `vendor/mmw60/` 的 `spec.py` 与 `data/spec/survey.yaml`,那里只剩 ×10 LO 剖面(仍 pin 在 mmw60_trx@`ef0f00c`)。
- `data/sources.yaml` 的 5 条 `upstream:` 改成 `spec_sources:<引用>`;`value` / `cite` / `quote` / `section` / `note` 不动。隔离度的减法换成 spec_sources 的
  derived 条目 `isolation.tx_rx_tue2018_no_ebg_min_db`(40 − 20 = 20 dB)。`sources.upstream_value` 只剩查找(读取器的 `ref()`,`KeyError` 转 `ValueError`),
  不再自己解析 `@` 和 `-`;引用里的减法现在被拒。
- 测试:来源守卫换读 spec_sources、坏引用多一条"减法";vendored 表的四个标签数得准(`audit_tags`);vendor 检查的 pin 表加 spec_sources。CI 的 vendor-drift 多检出 spec_sources。
- 指纹:逐位不变(1979 个值)。

---

## [0.2.9] — 2026-11-12 — 接收机的两级压缩;×10 LO 的配置;推荐 blanking 不再给无效值

- **接收机压缩模型**(ROADMAP 原 P1 #4,`link/compression.py`):高通之前一级(带外 P1dB)、之后一级(带内 P1dB),各是一个 Rapp 限幅(膝部 `frontend.rx_rapp_p`,占位 2)。
  时域引擎逐样本过两级;统计引擎用闭式(弱信号在强信号旁:回波保留 (F′ + F/B)/2、噪声 (F′² + (F/B)²)/2),泄漏造成的压缩进所有 SNR(`LinkBudget.compression_*`、
  `LeakageBudget.compression_*`)。默认档:泄漏 −8 dBm 比带外点高 4 dB → 前级压掉泄漏 5.24 dB,回波 −10.65 dB,SNR −2.3 dB;两个引擎对同一帧差 ≤ 0.35 dB。
  `frontend.compression: false` 是原来的线性接收机。**更正 0.2.8 的结论**:"1 阶 200 kHz 高通不够、78 % 削波"是线性接收机的;有压缩时 ADC 还有 5.3 dB,代价在回波上。
- **×10 LO**:`configs/radar_60g_x10lo.yaml` 用 mmw60_trx 的 ×10 剖面(vendored,逐字节校验)。文件剖面下 chirp 发生器的量化只算一次(外来文件在 event 引擎下加上两项量化,
  导出的文件带分项)——之前时域比闭式高 10–15 dB。结论:带内的底是发生器的 5 ps TDC(L(1 MHz) −85.1),不是 ×10 LO(−98.6)。
- **推荐 blanking**(原 P1 #5):瞬态要落进 ADC 在稳态泄漏之上还剩的量程;稳态泄漏本身到满幅时不给推荐(`steady_clipping`),改报还缺多少衰减。示例 08 列出没 blank 的情形和原因。
- 新配置字段 `frontend.rx_rapp_p`、`frontend.compression`;来源表多两条 `rx_rapp_p`(占位,两个频段)。
- 指纹(numbers-move):带泄漏的三个用例(`radar_60g_mimo`、`leakage_hpf`、`leakage_hpf_blanked`)、文件剖面用例的鬼目标表、新配置;其余逐位不变。

---

## [0.2.8] — 2026-11-12 — 前端的数有了出处:读 mmw60_trx 的来源表;接收压缩点拆成两个

- **vendor mmw60_trx 的来源表**(`vendor/mmw60/`:`spec.py` + `data/spec/survey.yaml`,pin `ef0f00c`;不 vendor `Frontend60`)。漂移检查现在也逐字节比 vendored 的 YAML;CI 多检出一个姊妹库。
- **60 GHz 档五个数从占位换成读过原文的**(`source: spec`,带引文;`upstream:` 指向上游条目,加载时核对相等):发射 10 → 12 dBm、NF 10 → 12 dB、收发隔离 25 → 20 dB、
  接收压缩点 −20 dBm → 带外 −12 dBm 与带内 −34 dBm(40 dB 增益)。前三条与两个压缩点来自一颗 60 GHz 雷达芯片的手册(TI SWRS219F 7.9 节),隔离来自 Adela 等 2018。
  天线增益与 RX 增益档仍是占位(设计选择,没有对口的出处)。来源表 26 → 23 条 `assumed`,0 → 5 条 `spec`。
- **接收压缩点是两个量**:`frontend.p1db_dbm` 拆成 `p1db_oob_dbm`(高通之前;泄漏碰到的)与 `p1db_inband_dbm`(回波碰到的;留空时随增益每 dB 降 1 dB,`RadarConfig.p1db_inband()`)。
  泄漏预算按每一项的拍频在高通截止的哪一侧选点(`LeakageBudget.p1db_kind`)。**配置里写了 `frontend.p1db_dbm` 的要改成这两个字段。**
- 结论的变化:SNR 几乎不动(+0.04 dB:发射与 NF 各 +2 dB 抵消);泄漏强 7 dB(接收端 −15 → −8 dBm)——对带外压缩点 −4 dB;2 阶 200 kHz 高通的 ADC 裕量 +35 → +28 dB、推荐 blanking 4.5 → 5.4 µs;
  **1 阶 200 kHz 高通不再够**(高通后泄漏在 ADC 满幅,稳态削波 78 %)。
- 指纹(numbers-move):60 GHz 的预算、所有带热噪声 / 泄漏的时域帧、两个改名的预算行;chirp 曲线、相噪、77 GHz 的数逐位不变。示例期望输出重新接受。

---

## [0.2.7] — 2026-11-12 — 重新 pin polar_tx(b007e60):上游的 TDC 抖动项、内核里的 dp_cal、有效域的定论

- **vendor 重新 pin**:polar_tx `7057738` → `b007e60`(嵌套的 pllsim 整体到 pll_simulator@5564c64;多一个 `core/tdcspurs.py`)。polar_tx#19 的答复(B1 的真因、C5)都在里面。
- **TDC 抖动项用上游的**:`analyze()` 自带 `tdc_jitter`(pll_simulator#77),本库 `lo.py` 自己加的那段删了(同一个式子,相对差 2e-16);`simulate()` 的 TDC 抖动跨边沿回绕(#78)。
- **`ChirpFlybackLMS` 改成步进内核**(`flyback_dp_step` + `kernel_view` / `kernel_done`):polar_tx 把 `dp_cal` 搬进了 ADPLL 的逐周期内核,只有 `.step/.value` 的对象会抛 `TypeError`。
  校准轨迹与改前逐位相同;装了 numba 时编译与解释逐位一致。
- **有效域**:495 % UI/周期不再是越界——polar_tx 查到真正的条件是 TDC 量程盖住一个 DCO 周期(本库 9.5 个)。`build_adpll` 拒绝盖不住的 TDC(三个引擎都拒绝);
  报表的措辞改成描述量,并多一个 `ChirpResult.dco_dev_frac_p99`(DCO 偏离标称 ±3.3 %)。
- **量了上游的一条推断**:TDC 按标称周期归一化在斜坡上不是"被环路吃掉":不抖动时频率误差 513.8 对 498.4 kHz RMS,最强静态鬼目标 −45.7 对 −48.1 dBc;
  带 1 ps 抖动时看不出。保持建模,记在 ROADMAP P1 #2(可接 vendored 的 `TdcPeriodCal`)。
- **报表说明剖面在哪里不再是答案**(P1 #1(c) 的标注部分):`lo.parked_lo` 与 `LOProfile.notes` 把上游 `analyze()` 的 TDC 死区提示接进相噪一节——
  LO 停在载波(CW)或斜坡起点(`chirp.idle_s`)时,若那个频率是整数 N 且 TDC 输入的抖动不到半格,带内相噪高于线性剖面(默认 1 ps:+5.5 … +10.9 dB)。不动任何数。
- 指纹(numbers-move):1838 值里 253 个。chirp 曲线与静态鬼目标逐位不变;相噪旁瓣只动末位(≤ 1.75e-11 dB);带噪声的曲线只在抖动非零时动(回绕),
  随之时域帧 SNR ≤ 0.09 dB、峰值旁瓣 ≤ 0.43 dB、检测数 ±3,示例 02 的 1 ps 行 −54.6 → −54.8 dBc(换了位置)。

---

## [0.2.6] — 2026-11-12 — TDC 抖动:占位、剖面里的一项、相干杂散(P1 #1(a))

- **`lo.tdc_jitter_s`**(None → 占位 1 ps RMS,`assumed`):进 `TDCConfig.jitter_rms_s`。之前它是 0,且不在 `sources.yaml` 里——一个没登记的占位。来源表 24 → 26 条 `assumed`。
- **LO 剖面多一项 `tdc_jitter`**:与量化同形,功率是 `tdc_quant` 的 12σ²/t_res²(pllsim 的 `analyze()` 没有,pll_simulator#76)。L(1 MHz) −80.2 → −79.6 dBc/Hz。
  斜坡上逐周期引擎对这个剖面,抖动 0–5 ps、0.3–10 MHz 差 ≤ 0.4 dB。
- **鬼目标改成"一帧里什么是相干的"**(`coherent_spurs`):开环路噪声跑一帧的 ramp,距离谱相干平均里显著的局部极大(CA-CFAR 式的判据,给出检出限)。
  不抖动的图样 −45.3 dBc;抖动 0 / 0.5 / 1 / 2 ps:−49 / −51 / −55 dBc / 低于检出限。人体目标每帧鬼目标检测 0.03 → 0.00。原来的单 ramp 列表留作 `ghosts_quiet`。
- **时域引擎默认用带噪声的逐周期曲线**(LO 是 vendored 环路本身时),与统计引擎的鬼目标表共用一次运行(`noisy_chirp` 缓存)。示例 02 多一张抖动表。
- 被推翻的判断:"TDC 鬼目标是物理的,要等 pll_simulator 的 dither"——是抖动为零这个占位造成的。`tools/export_lo_profile.py` 改为导出含抖动项的剖面,bundled 的剖面文件重出。
- 指纹(numbers-move):所有相噪值(剖面多一项)、鬼目标表、带相噪的时域帧动了;预算、chirp 曲线、CFAR 的 Pfa 逐位不变。

---

## [0.2.5] — 2026-11-10 — LO 噪声在 chirp 曲线与剖面之间的分工(P1 #1(b))

- **时域引擎把 TDC 量化算了两遍**:noise=False 的逐周期曲线就是剖面的 `tdc_quant` + `dco_quant`(1 MHz 处 −85.2 对 −85.3 dBc/Hz),却叠在整份剖面上,
  1–5 m 的 LO 底比分工后高 1.1 dB(比闭式高 1.5–2.2 dB)。现在曲线带什么、剖面就不合成什么(`ChirpResult.lo_noise_in_curve`、`LOProfile.components` / `without` / `above`、`info["lo_noise_split"]`)。
- **带噪声的 chirp 曲线修对了**:`freq_out` 是调谐字的频率,不含 DCO 自己的相噪;积分它在 30 kHz 处多读 45 dB。`phase_err_carrier_rad()` 加上
  `osc_phase_dco_rad`(从 `phase_err_out` 减指令相位得到)。修后斜坡上逐周期引擎与线性剖面 0.1–10 MHz 差 ≤ 0.6 dB。
- `run_time(cfg, chirp_noise=True)`:环路到 fref/2 的噪声由逐周期引擎带,剖面只留 fref/2 以上;LO 底对闭式 −0.02 … +0.47 dB。示例 04 多一张三种分法的表。
- 发现:CW 整数 N 下 `simulate` 的带内相噪比 `analyze` 高 15 dB(TDC 死区,0.133 rad @ DCO);斜坡自带 dither 所以 chirp 时一致。并入给 pll_simulator 的条目。
- 时域 SNR 对期望的差(原 P2 #1)了结:12 个 seed 平均 +0.06 / −0.04 / +0.06 dB(2 / 5 / 10 m),单 seed 标准差 0.10–0.21 dB。指纹(numbers-move):带相噪的时域帧全部动了(少合成了量化两项),统计值与 chirp 值逐位不变。

---

## [0.2.4] — 2026-11-10 — K-look 阈值、训练窗裁剪、含自漏的 Pd、鬼目标进虚警账(P1 #3、P1 #1(c))

- **MIMO 图的 CFAR**:非相干和的格是 Gamma(K),`threshold_factor(n, pfa, n_looks)` 取 Beta(K, K·N) 的分位数(K = 8:4.6 dB 而不是 9.7 dB);`_process_cube` 用它。
  修之前 Pfa 1.2e-23,`mimo_2x4_coupled` 的 39 dB 目标 0 个检测格(现在 12 个)。精确 Pfa 推广到 K 重特征值(K 阶极点的留数)。
- **训练窗裁剪**(`cfar_window`):每轴半宽不超过 (len − 1)//2。8 chirp 帧不再绕回到被测格:设计 1e-4 实际 1.4e-6 → 6.3e-5。32 / 64 chirp 不裁,逐位不变。
- **Pd**(`cfar_pd`、`cfar_snr_for_pd`):阈值的抖动、被测格相关与目标自己漏进训练格(c_w = 0.0062)都在内;默认图 Pd 0.9 要 12.24 dB,CFAR 损失 0.49 dB。
- **鬼目标进虚警账**:每个 TDC 鬼目标当作 SNR + 电平的稳态目标,`StatResult.cfar["ghosts"]` 与 `ghost_detections_per_frame`;人体 0.03 / 帧,车 5 / 帧,时域引擎同。
- 被推翻的判断:示例 00 主瓣外的 12 个过阈格是"量化杂散"——是噪声虚警(期望 10.5 格 + 0.20 个鬼目标)。示例 00 的那行改了。
- 指纹(numbers-move):14 个用例的 `n_detections`(8 chirp 的裁剪与 MIMO 的阈值)和 8 chirp 配置的 `cfar.*` 动了,其余旧值逐位不变;多了 `cfar.*` 新键。

---

## [0.2.3] — 2026-11-10 — CFAR 有效格数(P2 #0 第三项)

- `processing/cfarstats.py`:窗与零填充后的格相关(w² 的谱)、训练集有效格数 N² / Σρ、训练格与被测格的相关、每格 Pfa 的**精确式**
  (Hermitian 型 |x|² − (α/N)Σ|y|² 的特征值:Π 1/(1 + |λ_j|/λ₊))、一帧的带内格数 / 独立观测数 / 期望虚警格。进 `StatResult.cfar`、报表与示例 06。
- 默认(Hann / Hann、距离 ×4、guard 2 + train 8):416 个训练格值 33.4 个;guard 只有 0.5 个距离格,c = 0.015;两个效应单看 2.7e-4 / 2.6e-5,合起来精确 1.02e-4。
  白噪声 1.54e7 格实测 1.062e-4(641 团,±4 %;六组配置比值 0.89–1.04);时域纯噪声帧 6 帧 1.022e-2 / 9.57e-4 / 9.2e-5 对精确式 0.98 / 0.92 / 0.90。
- 被推翻的判断:"按独立格算的闭式 Pfa 是上界"(里程碑 2 的 4 个虚警是抽样;guard 8 时实际 1.8e-4,高于设计)。
- 发现并记入 ROADMAP P1 #3:MIMO 非相干和图用单通道阈值因子(K = 8:Pfa 1.2e-23,多丢 5.1 dB);帧短于训练窗时 Pfa 塌到 1.4e-6。指纹只多 `cfar.*` 新键(numbers-move)。

---

## [0.2.2] — 2026-11-10 — 测角 RMS 归因(P2 #0 第二项)

- `VirtualArray.angle_error_budget`:本估计器(加窗 DBF + 脉冲对多普勒补偿)的一阶误差闭式,拆成四个因子乘在 CRLB 上——元方向图、格点刻度损失、
  角窗对均匀权、TDM 补偿的多普勒估计(含它与快拍的相关)。默认 2 × 4:0.0231° × 1.088 × 1.523 × 1.011 = 0.0386°(cos 元再 × 1.064 = 0.041°)。
  进 `StatResult.angle`(`sigma_expected_deg`、`factor_*`、`snr_element_cell_db`)、报表与示例 07。
- 核对:快拍级蒙卡 9 组配置 ≤ 1.5 %;时域引擎 384 个 seed 0.0395° 对 0.0386°(+2.3 %,抽样 ±3.6 %)。ADC 量化、相噪、多普勒估计都不是那 2 倍的来源。
- 示例 07:32 个 seed、期望列、同一批快拍用真多普勒 / 均匀权重读;报表的"目标角度"原来恒打 0(`report["target"]` 没带 `angle_deg`),已修。
- 被推翻的判断:"时域测角误差贴着 CRLB,差的是 ADC 量化与多普勒估计噪声"(`cairn/mimo-angle.md` 2b)。指纹只多新键(numbers-move)。

---

## [0.2.1] — 2026-11-07 — 飞回 blanking(里程碑 2 的 P2 #0 第一项)

- `rx.blank_s`:每个 chirp 开头 blanking 的时长;距离窗按剩下的样本重配(`processing.windows.range_window`,所有距离 FFT 与窗统计共用),
  近旁瓣不变、主瓣宽 n/(n − k)、SNR 损 10 log(n/(n − k));时域引擎把那些样本置零并另报 `clipped_fraction_after_blanking`。
- 泄漏预算多五行:锯齿重启的泄漏相位跳变在 ADC 的阶跃(2A|sin(Δφ/2)| 求和,7.2 V)、高通最慢极点的时间常数(1.13 µs @ 2 阶 200 kHz)、
  推荐 blanking(阶跃落到满幅以下 + 1 个时间常数:4.5 µs)、配置值、blanking 的 SNR 损失。1 / 2 / 3 阶的推荐值盖住时域量到的削波段(余量 1.2–1.3 倍)。
- 示例 08 多 blanking 行与无噪声的远底对照;指纹 1235 → 1367 值,旧值逐位不变(numbers-move:只有新键与新用例 `leakage_hpf_blanked`)。
- 被推翻的判断:"blanking = 把样本清零"——不变的窗下清零 80 个样本把远旁瓣抬 20 dB 以上(`cairn/mimo-angle.md`)。

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

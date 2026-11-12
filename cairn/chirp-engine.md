---
type: project_topic
status: active
summary: "chirp 发生器 = vendored polar_tx 两点 ADPLL 喂斜坡:event 引擎在 chirp 上的有效域(495 % UI/周期可用;polar_tx#19 之后真正的条件是 TDC 量程盖住一个 DCO 周期,斜坡的代价是标称周期归一化)、频率误差曲线的数(TDC 量化底 ~0.54 MHz RMS、5 % 失配 200 MHz 阶跃 1.5 µs 建立)、dp_cal 在锯齿上的行为(原版发散、差分版慢收敛、离线 LS 一次到位)。"
tags: [adpll, chirp, two-point, dp_cal, polar_tx]
contains: [decision, lesson, experience]
created: "2026-11-06"
updated: "2026-11-12"
related: [architecture-invariants]
authoring_mode: ai_generated
---
# chirp 引擎

## 背景

铁律 4:频率误差曲线由 vendored ADPLL 在斜坡下的真实响应给出。polar_tx 的 `ADPLLTwoPoint` 有两个引擎:`response`(z 域线性化)和
`event`(逐参考周期,`ADPLL.simulate(mod_freq=...)`),后者的有效域声明为"每参考周期相位推进 ≪ 1 UI"(BLE 0.8 %、EDR 4.2 % 可以,
LTE-20 的 29 % 不行,polar_tx ROADMAP B1)。任务要求先量一次这个指标再决定 event 引擎能不能用。

## 当前结论

- **指标量了:4.95 UI/周期(495 %)**,默认 config(15 GHz DCO、1 GHz 斜坡、fref 100 MHz):斜坡偏差 ±500 MHz 除以 fref。
  按 polar_tx 的声明域,event 引擎在任何现实 chirp 上都"无效"(fref 提到 1 GHz 也是 50 %)。
- **但引擎本身在斜坡上行为正常,判断是:指标不适用于 chirp,引擎可用。** 理由:polar_tx 的指标针对的是 *亚周期相位轨迹*
  (GFSK/OFDM 的相位要靠 TDC 在一个 DCO 周期窗内分辨);计数器辅助的 ADPLL 对整数 DCO 周期用计数器、只对小数用 TDC,
  频率斜坡是环路的本职(分数 FCW 就是一个斜坡)。证据(`tests/test_chirp.py`、示例 02):
  - 5 % 两点失配时,event 与 response 在飞回后前 40 个周期逐周期一致:比值 1.005 ± 0.046;初始误差 199.4 vs 200.0 MHz(载波处)。
  - 匹配增益时 event 的误差只剩量化底:**载波处 ~0.54 MHz RMS**(5 ps TDC 在 15 GHz DCO 上约 13 码/周期,经比例路径 α = 0.054 → ~2 LSB Kdco);
    TDC 1 ps 时底降到一半以下。
  - 5 % 失配:飞回阶跃 eps·B = 200 MHz,环路(1 MHz UGB)在 1.47 µs 内建立到 ±2 %(response 1.10 µs);斜坡末尾误差 < 5 % 阶跃。
- **更正(2026-11-12,polar_tx#19 的答复,见本文"polar_tx#19 的答复与重新 pin"一节)**:上面"指标针对亚周期相位轨迹"的读法方向对、原因没说对。
  polar_tx 查到 LTE-20 失败是因为它的 TDC 量程只盖 0.25 个 DCO 周期(每周期饱和),与推进量无关;推进量的告警已删,指标只作描述。
  本库的 TDC(5 ps × 127 = 635 ps)盖 9.5 个周期(66.7 ps),所以 495 % 照样跟得上。
- 所以 chirp 引擎直接驱动 `pll.simulate`(不经 `ADPLLTwoPoint._mod_event`,后者做去趋势;polar_tx a6c65f0 之前还会按推进量告警),`freq_out − (fout + mod)` 就是曲线;
  指标仍算出来放在 `ChirpResult.ui_per_ref_cycle_p99` 和报表里。response 仍经 `ADPLLTwoPoint`,作为线性参照和离线校准的回归量来源。
- "DTC 量化"在 TDC 模式 ADPLL 里对应的是 **TDC + DCO 量化**(两点调制和 `dp_cal` 只在 TDC 模式有;dtc_bbpd 模式不接受 mod_freq)。

## dp_cal 在锯齿 chirp 上

- **被推翻的判断:"dp_cal 就是 chirp 线性度校准"按原样不成立。** polar_tx 的在线 `SignSignLMS`(误差 × EMA 居中的调制量)在锯齿上往错方向走:
  1.05 → 1.066(20 个 chirp,mu 2e-5)。原因:斜坡的 EMA 居中回归量几乎恒正,而失配留下的稳态相位误差是常数(二阶环对频率斜坡的稳态误差),
  去直流后与回归量不相关;信息只在飞回瞬态里。
- **信息在哪**(0.1.1 量的,+5 % 失配、无噪声):飞回后第 0 个周期 Δe 比匹配时多 +0.47 UI,逐周期衰减,到第 ~25 周期降到量化底(0.03 UI RMS);
  第 50–200 周期是环路过冲,符号相反(均值符号 −0.28);200 周期之后斜坡稳态里 Δe 与失配无关。
- 走过的弯路:(1) 全周期差分 sign-sign 能收敛但慢(1.05 → 1.006 / 20 chirp):20 个有信息的周期对 10 000 个量化噪声周期,是随机游走;
  (2) 大 mu 的 gear shift 让它乱走(mu 2e-3 时 1 个 chirp 内 1.05 → 0.64);(3) 飞回后 60–300 周期的窗口落在过冲区,两侧都往外漂 0.05;
  (4) 20 周期窗口 + sign-sign 从两侧 6 个 chirp 收敛,但都停在 0.995 —— 窗口里 TDC 锯齿(小数相位转码的 +0.001 步与 −0.067 回落)符号不对称。
- **定型:`ChirpFlybackLMS`** —— 飞回(回归量步 > 0.3 × 斜坡幅度)后 20 个周期内 value += mu·Δe·sign(步),mu = 1e-2(单位 1/UI)。
  幅值加权让锯齿均值为零、无偏:开噪声时 1.05 → 1.0082 → 1.0023 → 1.0004(第 1/2/3/4 chirp),0.96 → 0.9937 → 0.9985 → 0.9996;
  从 1.01 / 0.995 也都在 4 个 chirp 内到 ±0.05 %。这是 `lo.dp_cal: online` 的实现;离线 LS 仍是默认。
- **离线 LS**(polar_tx `cal/twopoint.estimate_dp_gain_error`,在 response 的精确高通回归量上投影)一次把 5 % 估到 4.995 %(event)/ 4.98 %(response),
  第二次残余 1e-4。但要喂它**连续两个 chirp 以上**:单个 chirp 的首个飞回是从锁定态来的半幅阶跃,回归量按整幅建模 → 估计只有 2.5 %。
  现在每次校准跑 3 个 PRI、估后 2 个。这是默认(`lo.dp_cal: offline`)。

## 带噪声的曲线与 LO 剖面的分工(P1 #1(b),0.2.5)

- 逐周期引擎和线性剖面(`analyze()` × N²)说的是同一个环路。**斜坡上两者一致**:noise=True 时每个 ramp 去线性趋势的载波相位谱对剖面
  0.1 / 0.3 / 1 / 3 / 10 MHz 处 −83.2 / −80.5 / −80.1 / −89.9 / −100.7 对 −83.8 / −80.8 / −80.2 / −90.2 / −100.9 dBc/Hz(0.6 dB 内;30 / 45 MHz 高 0.9 / 1.9 dB,
  逼近 fref/2 的混叠);一个 ramp 的相位 RMS 0.194 对 0.197 rad。(这一组是 0.2.5、TDC 抖动为 0 时量的;加了抖动项之后见下一节。)
- **noise=False 的曲线就是剖面里的量化两项**:−84.6 / −83.4 / −85.2 / −94.0 / −106.1 对 `tdc_quant` −85.1 / −84.0 / −85.3 / −95.5 / −106.0(`dco_quant` 低 40 dB)。
  同一份能量,在斜坡上是每个 chirp 都相同的确定性图样(鬼目标),在线性模型里是白噪声。
- **分工**(`ChirpResult.lo_noise_in_curve` → `beat_frame`):曲线已经带的,剖面就不再合成。
  noise=False 的 event 曲线带量化 → 剖面去掉 `tdc_quant` + `dco_quant`(`LOProfile.without`);noise=True 带环路在 fref/2 以内的全部 → 剖面只留 fref/2 以上
  (`LOProfile.above`,DCO 自身的 Leeson 段);ideal / 不带噪声的 response → 剖面全算。`run_time(cfg, chirp_noise=True)` 走第二种。
- 核对(示例 04:32 chirp,Blackman,±12 格,对整份剖面的闭式,+1 / +2 / +3 / +5 m;0.2.6 的数,TDC 抖动 1 ps):只有剖面 +0.28 / +0.00 / +0.04 / +0.03 dB;
  noise=False 曲线 + 去量化的剖面 +0.26 / +0.09 / +0.38 / +0.72(均 +0.36;图样是成团的,鬼目标所在的偏移高);noise=True 曲线 + fref/2 以上
  +0.12 / −0.08 / +0.29 / +0.21(均 +0.13);0.2.7 重新 pin 后(TDC 抖动回绕,同一 seed 的实现变了)+0.39 / −0.03 / +0.21 / +0.16(均 +0.18)。
- **坑(contains:时域引擎把 TDC 量化算了两遍)**:0.2.4 及以前把 noise=False 的曲线叠在**整份**剖面上:1–5 m 的底比分工后高 0.99 dB(示例 04;0.2.5 时 1.11);
  逐偏移对闭式 +1.88 / +1.56 / +2.21 / +1.68 dB(0.2.5、seed 3)。
- **坑(contains:`freq_out` 不是带噪声的瞬时频率)**:pllsim 的 `freq_out` 是调谐字决定的频率;DCO 自己的相噪只进 `phi_v`(`phase_err_out`)。
  noise=True 时把 `freq_out − 指令` 积分,得到的是环路对 DCO 噪声的**反作用**:30 kHz 处 −39 dBc/Hz(真值 −85,多 45 dB),3 MHz 以上反而少 4–10 dB。
  `phase_err_carrier_rad()` 现在加上 `osc_phase_dco_rad` = `phase_err_out`(后移一拍,减指令相位)− 调谐字积分;noise=False 时这一项 < 2e-5 rad,不加,逐位不变。
- **坑(contains:CW 下线性模型低估带内相噪 15 dB)**:整数 N、不扫频、noise=True:`simulate` 的带内相噪 −66 … −69 dBc/Hz(60 GHz 处),`analyze` −81 … −85。
  相位误差 0.133 rad RMS(DCO 处)= 5 ps / √12 的 0.136 rad:TDC 死区,环路看不见一个量化格以内的漂移。斜坡每周期把小数相位扫过量化格,等于给了 dither,
  所以 chirp 时两者才一致。雷达只在斜坡上用 LO,结论不受影响;CW / 空闲段(`chirp.idle_s`)的相噪不能用剖面。已提 pll_simulator#76(在它自己的 main 上复现:
  TDC 抖动 0 / 1 / 2 / 5 ps 时带内差 +15.8 / +10 / +6 / 0 dB;`analyze` 的总量不随抖动变,5 ps 时 `simulate` 在 3–10 MHz 高 4 dB)。
  **上游的答复(2026-11-12,pll_simulator#77 / #78,main@5564c64,已在它的 main 上复核)**:`analyze()` 加了 `tdc_jitter` 项(与本库自己加的那项相对差 2e-16);
  dither 不到半个量化格时给死区提示(本库的环路抖动 0 / 1 / 2 ps 是 0.08 / 0.22 / 0.41 格,都被标);另查出 `simulate()` 在整数 N 时把负的 TDC 抖动截掉了,改成回绕——
  上面"5 ps 时 3–10 MHz 高 4 dB"就是这个截断,修后 +0.6 / +0.8 dB;CW 带内 1 ps +5.5 / +5.9 / +10.9、2 ps +0.1 / +0.9 / +1.6 dB。斜坡上修前修后都在 ±0.7 dB 内
  (贴着量化格边沿的周期只占 1.5 %)。这些要等 polar_tx 更新 vendored 副本才到本库(ROADMAP"等上游"#4)。
  **0.2.7 已到**(polar_tx b007e60):经本库 vendored 的副本重量,CW 带内 0 / 1 / 2 / 5 ps 是 +15.8 / +15.8 / +15.3、+5.5 / +5.9 / +10.9、+0.1 / +0.9 / +1.6、+0.1 / +1.7 / −1.1 dB,
  与在上游量的逐项相同;`analyze().notes` 对 0 / 1 / 2 ps 给死区提示,5 ps 不给。
  报表现在把这条接出来(`lo.parked_lo`、`LOProfile.notes`,相噪一节下的"The LO while it is not ramping"):死区只在 LO **停着**的频率是参考的整数倍时才有,
  所以分开看载波处(CW,默认 FCW 150)和斜坡起点(`chirp.idle_s` 停在那里,默认 FCW 145);2 GHz 扫频的起点是 147.5,分数 N,不在死区。
  测试用两条独立实现守着这个标记:被标的(1 ps)逐周期引擎在 30–300 kHz 平均比线性分析高 > 4 dB(量到 +7.8),没被标的(5 ps)在 ±2 dB 内(量到 +0.5)。
- 没做的:带 `lo.profile` 文件的配置没有分项,noise=False 的曲线仍叠在整份剖面上(`lo_noise_split` 里写明);response 引擎的 noise=True 没核对过它加了什么,
  时域引擎拒绝它。

## TDC 抖动:既是噪声也是 dither(P1 #1(a),0.2.6)

- `lo.tdc_jitter_s`(None → 占位 1 ps RMS,`assumed`,5 ps TDC 的 0.2 LSB)进 `TDCConfig.jitter_rms_s`。之前 `build_adpll` 把它留在 0,而且这个 0 不在 `sources.yaml` 里。
- **线性模型里的一项**:TDC 抖动是与量化误差同一节点的白时间误差,所以形状同 `tdc_quant`、功率是它的 12σ²/t_res²(1 ps / 5 ps:0.48 倍)。pllsim 的 `analyze()` 当时没有这一项
  (pll_simulator#76),`LOProfile.from_config` 自己加(`components["tdc_jitter"]`);0.2.7 重新 pin 后 `analyze()` 自带这一项(同一个式子,相对差 2e-16),本库那段代码删了。L(1 MHz) −80.2 → −79.6 dBc/Hz,LO 自身 186.7 → 202.0 mrad。
  斜坡上逐周期引擎(noise=True)对这个剖面,0.3 / 1 / 3 / 10 MHz:抖动 0 ps −0.1 / −0.3 / +0.3 / +0.1 dB,1 ps +0.2 / −0.2 / −0.1 / +0.1,2 ps +0.1 / −0.4 / 0.0 / 0.0,5 ps 0.0 / −0.3 / −0.3 / −0.2。
- **鬼目标看一帧里什么是相干的**(`coherent_spurs`):各 ramp 的距离谱相干平均与非相干平均;杂散 = 相干平均里的局部极大,在窗自己的裙边之外(比无误差响应高 6 dB)、
  高于 −70 dBc,并且显著——噪声在均值里剩 (非相干 − 相干)/(M − 1),由 M − 1 个 look 估,所以判据是 CA-CFAR 的因子 K(p^(−1/K) − 1),
  p 取"全剖面的独立格里每一百次搜索错报一个"(8 个 ramp 15 dB,64 个 11 dB)。检出限(杂散低于它就分不清是不是 LO 噪声):8 / 16 / 32 / 64 个 ramp −47 / −52 / −56 / −60 dBc。
- 数(5 ps TDC、5 m 目标):不抖动的图样(noise=False 单 ramp)±4.85 m **−45.3 dBc**;开噪声、抖动 0 ps:−12.18、±7.68 m 处 **−49 dBc**(两个 seed 同位置,
  环路别的噪声只打散 4 dB,换了位置);0.5 ps −51.3;**1 ps −54.6 … −56**(±7.68、±9.18、±3.93、−11.8 m,哪几个过检出限随 seed 变);2 ps 低于 32 个 ramp 的检出限(−54.8),64 个 ramp 时 −57。
  **0.2.7 重新 pin 后**(抖动回绕;抖动 0 ps 的曲线逐位不变):0.5 ps ±7.68 m −50.7;1 ps −11.81 m −54.8、−9.20 m −56.1、+9.19 m −56.4;2 ps 仍低于检出限。
- 时域引擎默认用这条带噪声的曲线(`run_time` 的 `chirp_noise` 缺省:event 引擎、没有 `lo.profile` 文件、相噪开关开着时为真),与统计引擎的鬼目标表读的是同一次逐周期运行
  (`chirp.noisy_chirp`,按 LO / 斜坡 / seed / chirp 数缓存最近 4 次)。显式传进来的曲线照用;`chirp_noise=False` 是不抖动的图样。
- **被推翻的判断(contains:lesson)**:"鬼目标是物理的、开噪声后不消失、pllsim 没有 dither"(0.1.1)。它是"TDC 抖动为零"这个没登记的占位的结果:1 ps 抖动就把 −45 压到 −55 dBc。
  凡是进了 vendored 构造函数却没走 `sources.yaml` 的默认值,都是没标来源的占位。
- **坑(contains:把一行噪声的极大值读成杂散)**:2026-11-11 复核时在 32 chirp 时域图的目标多普勒行上读 9.85 m ±6 cm 内的最大值,抖动 1 ps 时 −61.6 dBc,就写了"鬼目标降到 −61"。
  那一行的中位是 −69.6 dBc,几十个格里的最大值本来就高 8 dB——读到的是噪声。真正的相干杂散换到了别的偏移,−55 dBc。要说"有 / 没有杂散"得有显著性判据,所以才有上面的搜索。

## polar_tx#19 的答复与重新 pin(0.2.7,polar_tx b007e60 / pllsim 5564c64)

- **有效域(contains:decision)**:polar_tx 的 B1("event 引擎覆盖不到 LTE 级带宽")真因是 LTE-20 预设的 TDC 量程(127 ps)只盖 1.95 GHz DCO 周期(513 ps)的四分之一,
  小数相位一过 0.25 UI 就饱和;本库的 495 % 斜坡是让它排除"推进量"这个变量的反例。现在 `ADPLLTwoPoint` 构造时拒绝量程不足的 TDC;
  本库的 `build_adpll` 做同一个检查(`code_span`),三个引擎都拒绝(线性剖面描述的是一个能工作的 TDC)。`ui_per_ref_cycle_p99` 留作描述量。
- **标称周期归一化(contains:lesson,上游的一条推断在本库不成立)**:vendored 的 TDC 用标称周期把码换成小数周期(`code / cpp_nom`),斜坡把 DCO 带离标称
  B/(2N·f_dco) = ±3.3 %(`ChirpResult.dco_dev_frac_p99` 0.033),读数差 `小数 × Δf/f`。polar_tx 推断"锯齿上几乎恒定频偏、被环路吃掉"并注明没跑过本库的配置。量了:
  小数相位每周期都在变(推进 4.95 UI/周期),所以它是随小数相位摆动的误差,不是常数。默认 config、匹配增益、noise=False:

  | 量 | 标称周期(vendored) | 实际周期(临时改一行,不入库) | `TdcPeriodCal` EMA 1e-3 / 1e-2 / 1e-1 |
  |---|---|---|---|
  | 斜坡频率误差 RMS(载波处) | 513.8 kHz | 498.4 kHz | 507.1 / 500.7 / 499.6 kHz |
  | 斜坡前 / 中 / 后三段 | 515.6 / 500.3 / 525.2 | 483.7 / 500.9 / 510.2 | — |
  | 飞回后初始误差 | 400 kHz | 200 kHz | 601 / 801 / 0.6 kHz(含校准器自己的建立,没分开) |
  | 最强静态鬼目标(64 个 ramp 相干) | −45.7 dBc | −48.1 dBc | — |

  中段(DCO 在标称上)两种归一化相同,两端差,和 Δf/f 的形状一致;功率上多 (0.033/√12 ÷ 0.075/√12)² 的三分之一 ≈ 6 %,即 0.27 dB,与 513.8 / 498.4 相符。
  开噪声(TDC 抖动 1 ps、32 个 ramp)看不出:最强相干杂散 −55.4 dBc 对检出限 −55.9,开 `TdcPeriodCal`(EMA 1e-3 / 1e-2 / 1e-1)−54.9 / −55.4 / 无。
  真实 ADPLL 按固定周期归一化也有这一项,保持建模;ROADMAP P1 #2 记着"要不要接 `TdcPeriodCal`"。
- **`dp_cal` 契约变了**:polar_tx b007e60 起 `dp_cal` 在 TDC 内核里逐周期步进,只有 `.step/.value` 的对象抛 `TypeError`。`ChirpFlybackLMS` 改成步进内核
  `flyback_dp_step`(状态 7 个数:值、上一拍误差 / 回归量、窗内剩余周期、飞回符号、是否见过一拍、飞回计数),对象自己的 `.step()` 调同一个内核。
  校准轨迹哈希、`dp_gain_used` 与改前逐位相同(指纹 `event_online_cal` 的 chirp 段不动)。装了 numba 时内核被编译:三条 chirp(在线 / 离线静态 / 离线带噪声)
  的 `f_err` 与轨迹哈希在 编译 / `PLLSIM_JIT=0` / 没装 numba 三种情况下相同,带噪声的 3 chirp 0.82 → 0.08 s(手工核的,没有 CI 守着,ROADMAP P3 #6)。
- **什么动了(指纹 1838 值里 253 个)**:chirp 曲线 251 个值与静态鬼目标逐位不变;统计引擎相噪旁瓣只动末位(≤ 1.75e-11 dB,`tdc_jitter` 项换成上游自己的求和);
  带噪声的 chirp 曲线只在 TDC 抖动非零时动(抖动 0 ps 时 `f_err` 与载波相位哈希逐位相同;1 ps 时 `f_err` RMS 163.6 → 164.7 kHz,DCO 处)——原因是 #78 的回绕;
  随之鬼目标检出限 ≤ 0.09 dB、时域帧 SNR ≤ 0.09 dB、峰值旁瓣 ≤ 0.43 dB、CFAR 检测数 ±3。

## 经验

- 一个 chirp 的 event 仿真 = settle 40k + 10k 周期 ≈ 0.1 s(纯 Python 逐周期);64 chirp 一帧 0.7 s。够用,不需要 numba。
- 时域引擎用 chirp 误差相位时在参考网格上线性插值 t 与 t − τ:频率逐周期恒定,相位分段线性,插值是精确的。
- **TDC 量化的"鬼目标"**(32 chirp 帧,5 m 目标,只开 chirp 误差):无噪声逐周期引擎在 9.87 m / 2.34 m/s(目标的多普勒行)处 −45.5 dBc;
  TDC 从 5 ps 改 2 ps 后降到 −55.8 dBc 并移到 10.07 m;Kdco 从 50 改 20 kHz 不动它(−46.2 dBc,9.87 m)。开 DCO / 参考噪声(`noise=True`,
  两个 seed)后变成 2.2 m 与 7.81 m 处 −48.6 … −50.2 dBc,位置不随 seed 变。
  判断:这是 TDC 量化的物理 —— 斜坡让每参考周期的小数相位以线性增长的速率转过 TDC 码,量化误差是一个二次相位的锯齿,其谐波本身是 chirp,
  与延迟副本混频后落在固定拍频上,即固定距离处的鬼目标(FMCW ADPLL 文献里的 DTC / TDC 鬼目标机制);不是 `noise=False` 的产物,
  噪声只把它打散到别的距离。按铁律 6 由 event 引擎背书,引擎里 TDC 没有 dither(pllsim `TDCConfig` 只有 INL / 抖动),所以是悲观一侧。
  **更正(2026-11-11)**:"没有 dither"说错了——TDC 的抖动 `jitter_rms_s` 就是 dither,是本库的 `build_adpll` 把它留在 0(一个没进 `sources.yaml` 的占位)。
  noise=True、32 chirp,目标多普勒行上 9.85 / 0.14 m 处:抖动 0 ps −50.3 / −52.3 dBc,1 ps **−61.6 / −60.6**,2 ps −59.7 / −58.2(已是该行的底,中位 −69 dBc),
  5 ps −53.5 / −51.4(底自己抬到 −63.5)。所以 −45 dBc 的鬼目标是"TDC 抖动为零"这个占位的结果,不是 5 ps TDC 的必然;ROADMAP P1 #1(a)。

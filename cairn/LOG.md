# Project Cairn 日志

本文件按倒序记录实质性进展 —— 最新条目在本行正下方。每条保持简短(数字原值、被推翻的判断、下一步),
结论沉淀进 `cairn/<topic>.md`。

## 2026-11-11 · 三个上游 issue 已提;提之前查出一条自己的错(feat/upstream-issues)

- 已提:**polar_tx#19**(B1 的 495 % 指标 vs 逐周期一致 1.005 ± 0.046,附 SignSignLMS 1.05 → 1.066)、**pll_simulator#76**、**mmw60_trx#14**(消费清单,对照 main@4df0385,它的 D4 在收)。
- **被推翻的判断**(提之前复核时):"pllsim 没有 TDC dither,所以鬼目标是物理的、要等上游"。`TDCConfig.jitter_rms_s` 就是 dither,本库把它留在 0。
  noise=True、32 chirp,9.85 m 处:抖动 0 / 1 / 2 / 5 ps → −50.3 / −61.6 / −59.7 / −53.5 dBc(noise=False −45.4;行的底中位 −68.8 / −69.6 / −68.1 / −63.5)。
  所以 pll_simulator#76 没有要 dither 功能,P1 #1(a) 从"等上游"改成本库的占位问题(加 `lo.tdc_jitter_s`,鬼目标表从带噪声的曲线取)。
- pll_simulator#76 的内容在它自己的 main(src@00e48a2,adpll 到 675614a 未变)上复现:CW 整数 N,`simulate − analyze` 带内 +15.8 / +13…16 / +9…15 / +5…6 / 0 dB
  (TDC 抖动 0 / 0.5 / 1 / 2 / 5 ps);相位 0.1329 rad 对 5 ps/√12 的 0.1360;`analyze` 总量不随抖动变(没有抖动项),5 ps 时 `simulate` 在 3–10 MHz 高 4 dB。斜坡上不带抖动也一致(≤ 0.6 dB)。
- 上游的变化:pll_simulator#71 / #72 已做倍频器剖面;mmw60_trx main@4df0385 带了 ×10 的剖面文件,本库 `lo.profile` 原样读得进(floor140:L(1 MHz) −98.6 dBc/Hz @ 60 GHz,占位 −80.2)。
  原来"报回上游"里要倍频器模型的那条作废,改成 ROADMAP"等上游"#2(本库去用)。polar_tx 的 `_mod_event` 用的是 `phase_err_out`,0.2.5 修的 `freq_out` 问题只在本库的直驱封装里。
- 下一步:P1 #1(a)(现在是本库的事)。

## 2026-11-10 · 0.2.5:LO 噪声的分工(feat/lo-noise-split)

- **被推翻的判断**(0.2.4 那条里的):"noise=True 的逐周期谱在 3–30 MHz 比剖面低 3.5–4.7 dB、低频高得多"——估计器没错,量错了对象:`freq_out` 是调谐字的频率,
  不含 DCO 自己的相噪(只进 `phi_v`)。积分它 30 kHz 处 −39 dBc/Hz;用 `phase_err_out` 减指令相位是 −84.7(剖面 −84.7)。修后 0.1 / 1 / 10 MHz:−83.2 / −80.1 / −100.7 对 −83.8 / −80.2 / −100.9。
- **发现**:时域引擎把 TDC 量化算了两遍(曲线的图样 −85.2 @ 1 MHz = 剖面的 `tdc_quant` −85.3,叠在整份剖面上)。32 chirp ±12 格对闭式:
  +1.88 / +1.56 / +2.21 / +1.68 dB(+1 / +2 / +3 / +5 m);分工后 noise=False +0.23 / +0.41 / +1.18 / +0.70,noise=True −0.02 / −0.03 / +0.47 / +0.15,只有剖面 +0.23 / −0.38 / +0.20 / −0.04。
- **发现 2**:CW 整数 N、noise=True:`simulate` 带内 −69 / −68 / −65.5 dBc/Hz(0.03 / 0.1 / 0.3 MHz)对 `analyze` −84.7 / −83.8 / −80.8;相位 0.133 rad @ DCO = 5 ps/√12。TDC 死区;斜坡上没有。
- 原 P2 #1(时域 SNR 低 0.07–0.10 dB)了结:12 个 seed 平均 +0.058 / −0.044 / +0.063 dB(2 / 5 / 10 m;sem 0.033 / 0.030 / 0.060),单 seed 标准差 0.12 / 0.10 / 0.21 dB;原来的数是单 seed(seed 1,现在读 +0.07 / −0.02 / −0.05)。
- 结论在 `cairn/chirp-engine.md`"带噪声的曲线与 LO 剖面的分工";ROADMAP P1 #1(b) 换成剩下的三点,报回 pll_simulator 的条目加了 CW 死区。
- 下一步:不等上游的 P1 已清;剩 P1 #1(a)(等 pll_simulator)、P1 #1(c) / #3 的精度项、P2 #0 的因果 IF 滤波器。

## 2026-11-10 · 0.2.4:K-look 阈值、窗裁剪、Pd、鬼目标进虚警账(feat/cfar-looks-and-ghosts)

- P1 #3 修了:MIMO 图用 Beta(K, K·N) 分位数的阈值因子(K = 8:2.88 = 4.6 dB,原 9.31 = 9.7 dB;修前 Pfa 1.2e-23、`mimo_2x4_coupled` 0 个检测格 → 12 个);
  训练窗每轴裁到 (len − 1)//2(8 chirp:1.4e-6 → 6.3e-5)。精确 Pfa 的 K-look 版对独立格回到设计值(1e-5 内),相关格 K = 8 对蒙卡 1.01 / 1.02。
- P1 #1(c) 做了:鬼目标当稳态目标算 Pd。32 chirp:人体 0.03 / 帧(时域 0/4 帧)、0 dBsm 2.78(2.00)、+4 dBsm 4.78(4.12)、车 5.00(5.00)。
- **被推翻的判断**:示例 00 主瓣外的 12 个过阈格是"逐周期引擎的量化杂散"(0.1.0 起就这么标)。64 chirp 期望 10.5 个噪声虚警格 + 0.20 个鬼目标检测 —— 是噪声。
- Pd 闭式(含目标自漏 c_w = 0.0062):默认图 Pd 0.9 要 12.24 dB(损失 0.49 dB);对注入单音蒙卡 N_eff ≥ 24 时 ±0.03,短帧 ±0.07(ROADMAP P1 #3 新条目)。
- 过程中的错:`cfar_pd` 第一版把 K-look 的 α 多除了一个 K(MIMO Pd 恒为 1,蒙卡一眼看出);Gamma 平均用等概率节点在 N_eff = 16 时 Pfa 端差 4 %,换 Gauss–Laguerre。
- P1 #1(b) 起了个头(原值记在 ROADMAP):逐周期引擎 noise=True 的谱在 3–30 MHz 比剖面低 3.5–4.7 dB,低频高得多,未核实估计器。结论在 `cairn/cfar-statistics.md`。
- 下一步:P1 #1(b)。

## 2026-11-10 · 0.2.3:CFAR 有效格数(feat/cfar-effective-cells)

- **被推翻的判断**:"格相关下按独立格算的 Pfa 是上界"。两个方向相反的效应:训练集 416 格只值 33.4(Pfa ×2.7),guard 2 个填充格 = 0.5 个距离格、
  训练格与被测格相关 0.0151(Pfa ×0.26);默认配置碰巧抵消到 1.02e-4。guard 8:1.8e-4。里程碑 2 的"64000 格 4 个"是 ~2 团,期望 5.2 格。
- **被推翻的判断 2(过程中的)**:一阶式 (1 + α′/N_eff)^(−N_eff) 够用——两维都 ×4 填充时给 7e-10 对实测 9.7e-6;Gamma 矩匹配积分差 5 倍;
  换成 Hermitian 型特征值的精确式(只有一个正特征值 → 连乘)后六组配置比值 0.89–1.03。
- 原值:白噪声 120 图 1.54e7 格 1.044e-2 / 1.033e-3 / 1.062e-4(示例 06;另一个 seed 1.040e-2 / 1.026e-3 / 1.018e-4;精确 1.039e-2 / 1.036e-3 / 1.021e-4);时域 6 帧 6.1e5 带内格 1.022e-2 / 9.57e-4 / 9.2e-5
  (1420 / 186 / 25 团);一次独立观测 7.78 × 1.94 个填充格,32 chirp 一帧 3385 次。
- 发现:MIMO 非相干和图的阈值因子错 5.1 dB(K = 8:1.2e-23)、帧短于训练窗 Pfa 1.4e-6 —— ROADMAP P1 #3。结论与坑在 `cairn/cfar-statistics.md`。
- P2 #0 的三项(blanking、测角归因、CFAR 有效格数)做完;下一步:P1 #1(a)–(c),其中 (a) 等 pll_simulator,(c) 可与 P1 #3 一起做。

## 2026-11-10 · 0.2.2:测角 RMS 归因(feat/angle-rms-attribution)

- **被推翻的判断**:"时域测角贴着 CRLB,差的 2 倍是 ADC 量化 / 相噪 / 多普勒估计噪声"。闭式(`angle_error_budget`)说估计器自己就该散 1.67 倍:
  界 0.0231° × 1.088(多普勒格刻度损失,目标偏 0.36 格)× 1.523(8 元 Hann 角窗)× 1.011(脉冲对多普勒估计)= 0.0386°;cos 元 @ 20° 再 × 1.064 = 0.041°。
- 核对原值:快拍级蒙卡 4000 次 × 9 组配置,比值 0.992–1.015;时域 384 seed 全开 0.0395°、只留热噪声 0.0403°、真多普勒 0.0389°、真多普勒 + 均匀权 0.0247°
  (闭式 0.0386 / 0.0386 / 0.0382 / 0.0251);多普勒估计误差 1.7 Hz RMS。复现:`run_time(cfg, chirp, seed=s)`,s = 1000…1383,2 × 4、20°、8 chirp、各向同性元。
- **被推翻的判断 2(过程中的)**:128 个 seed 读 0.0434(+12 %)时以为还有 10 % 没归因,去找相噪的公共相位(算下来 < 0.1 mrad);384 个 seed 回到 +2.3 %——是抽样。
  6 / 24 / 128 / 384 个 seed 的 RMS 只准到 ±29 / 14 / 6 / 3.6 %;里程碑 2 的 0.050° 是 6 个 seed。
- 顺带修:报表"目标角度"恒为 0。结论与坑在 `cairn/mimo-angle.md` 2b;下一步:P2 #0 的 CFAR 有效格数。

## 2026-11-07 · 0.2.1:飞回 blanking(feat/flyback-blanking)

- 瞬态的机理量清了:不是 LO 飞回本身(泄漏 τ ≈ 0 不见误差曲线),是锯齿重启让泄漏拍频相位跳 2π f_beat T_c,7.2 V 的阶跃整个穿过高通,
  按最慢极点衰减(200 kHz 2 阶 τ 1.13 µs);削波段 1 / 2 / 3 阶 27 / 35 / 48 个样本,闭式推荐(落到满幅 + 1τ)32 / 45 / 64 个,都盖住。
- **被推翻的判断**:"blanking = 把开头样本清零"。不变的 Hann 窗下清零 80 个样本,1 阶高通例子的 2–4 m 底从 −94 升到 −72 dBc(台阶抬远旁瓣);
  窗按剩下的样本重配后近旁瓣不变,SNR 损 0.2 dB,无噪声底回到无泄漏参照 2 dB 内(余下是瞬态在窗上升沿下的尾巴)。
- 顺带量到:有噪声的帧里 blanking 的收益看不见(底是热噪声);blanking 后每 chirp 仍有最后 1 个样本削波,是引擎循环 IF 砖墙的前振铃(ROADMAP P2 #0)。
- 指纹 1235 → 1367,旧值逐位不变;示例 00–07 全量输出不变,08 换了表。
- 下一步:P2 #0 的测角 RMS 归因、CFAR 有效格数。

## 2026-11-07 · ROADMAP 结构:上游消费清单与报回条目,分支改 feat/* + PR(feat/roadmap-upstream)

- mmw60_trx main@caebcde6552ee6f621cdbe5846616266958a02dd 的 `Frontend60` 逐项对照本库 12 项 × 2 频段的 `assumed`:供 3(PA Psat / P1dB / Rapp,LO 剖面形状,
  `tx_leak_dbc` 可作泄漏第三项)、部分 2(天线增益字段无来源,AGC 档位表)、缺 7(RX NF、输入 P1dB、RX 天线增益、×N、TDC、TX→RX 隔离、互耦)。
  清单写成 mmw60_trx ROADMAP D 节可贴格式;本库不换占位,等它补面后按完整 SHA pin。
- ROADMAP 新节"报回上游(等用户转)":polar_tx B1(495 % 指标 vs 逐周期一致 1.005 ± 0.046;附 SignSignLMS 1.05 → 1.066 的观察与"回归量须零均值"的建议)、
  pll_simulator(TDC dither:±4.85 m −45.3 / −54.9 dBc;倍频器 ×N 底噪,两个消费方)。里程碑 2 的分支策略:`main` 默认,工作在 `feat/*` 开 PR;
  `ccr-dd350ddf-xv24an` 与 main 同提交,不再推。
- 保持的判断:dp_cal 不是 chirp 线性度校准——离线 LS 为主、`ChirpFlybackLMS` 在线(用户确认)。
- 下一步:P2 #0(飞回 blanking、测角 RMS 归因、CFAR 有效格数)→ P1 #1(a)–(c)。

## 2026-11-07 · 0.2.0:里程碑 2 —— TDM-MIMO 测角、TX 泄漏、多目标与 CFAR 曲线(ccr-dd350ddf-xv24an)

- vendor array_tx@e897c159e5fc5b2e26af6336cf9f6164461ff7f5(geometry / beam / coupling / touchstone,coupling 改编);`mimo.py` 虚拟阵列 2 × 4 → 8 元 20 mm,
  波束宽 13.42°,CRLB 0.023°(每元 39.3 dB);互耦 −16 dB 未校准偏 −0.292°、校准后 +0.0002°;斜视 +0.72 / −0.67°(FR2 ±0.15°)。
- **被推翻的判断**:"TDM 补偿用多普勒 FFT 的格就够"—— 4 chirp/TX 的格 1250 Hz 对 800 Hz 的目标留 −1.48° 系统偏差(界 0.023°);
  改为目标距离格上相邻同 TX chirp 的相位推进后均值 +0.014°、RMS 0.050°(6 seed)。
- **被推翻的判断 2**:"高通之后目标就是图上的峰"—— 2 阶 200 kHz 衰 56 dB 后泄漏 −31 dBm 仍比 5 m 人体 −47 dBm 高 16 dB,目标在 −18.1 dB 处被找到,
  测试改为对预算差(−16.2 dB)3 dB 内。P1dB 裕量 −5 dB、ADC 裕量 −21 → +35 dB、削波 100 % → 3.5 %(飞回瞬态)。
- **被推翻的判断 3**:u 格点上直接读角旁瓣 —— 55° 的主瓣从 u = −1 绕回来读成 −2.5 dB;半波长栅格的谱以 2 为周期,读前滚到中间;
  `peak_sidelobe_of` 主瓣跑出格点的一侧不算。
- **被推翻的判断 4**:`found_targets` 的 ±3 格窗 —— 12 cm 外的 −20 dBsm 点"找到"的是车的主瓣(+30 dB);分格 + 距离维局部极大后 5.434 m −28.3 dB 对统计 −30.4 dB。
- CFAR 损失 Pd 0.9:N = 16 1.35 dB,N = 32 0.73 dB;Swerling 1 闭式与蒙卡 0.02 内;时域纯噪声帧 64000 格 4 个虚警(格相关)。
- 指纹 691 → 1235 值,旧值逐位不变;示例 00 / 01 / 03 / 04 的全量输出逐字节不变(02 只有计时行)。mmw60_trx 仍空,占位未换。
  **更正(2026-11-07,用户指出)**:mmw60_trx 不是空仓——main@caebcde(0.1.0)已有 `Frontend60`;本会话的 checkout 是空克隆,没拉。
  它是通信前端,24 条占位里只供 PA / LO 泄漏 / LO 剖面形状,消费清单见 ROADMAP"等上游"。
- 结论与坑在 `cairn/mimo-angle.md`;下一步:ROADMAP P2 #0(飞回 blanking、测角 RMS 归因、CFAR 有效格数)、P1 #1(a)–(c)。

## 2026-11-06 · 0.1.1:鬼目标进统计引擎、在线校准定型(ccr-dd350ddf-xv24an)

- `nonlinearity_profile` 从单 ramp 曲线提鬼目标(主瓣外 15 格、−70 dBc 以上的局部极大):5 ps TDC ±4.85 m −45.3 dBc,2 ps −54.9 dBc;
  与时域图 3 dB 内一致;报表加表,`ghosts_vouched` 跟 event 引擎走。
- 在线校准走了四条弯路后定型为飞回后 20 周期的幅值加权 LMS(`ChirpFlybackLMS`,mu 1e-2):±5 % 四个 chirp 内到 ±0.05 %。
  被推翻的判断:"gear shift 能救 sign-sign"——问题不在步长而在更新的位置(信息只在飞回后 25 个周期里),大 mu 反而让它乱走。
  被推翻的判断 2:窗口里的 sign-sign 停在 0.995 不是失配,是 TDC 锯齿的符号不对称,换幅值加权就无偏。
- 新 config 字段 `lo.dp_cal_window_cycles`(20);`lo.dp_cal_mu` 含义改为窗口内 LMS 增益(默认 1e-2)。指纹:在线用例与新 ghost 键动了,其余逐位不变。
- 下一步:ROADMAP P1 #1(a)–(c);里程碑 2。

## 2026-11-06 · CI 首轮修复与 TDC 鬼目标判定(ccr-dd350ddf-xv24an)

- CI 红两处:fingerprint 作业在单提交历史上 `git rev-parse HEAD^` 把字面量 "HEAD^" 当 base(改 `--verify -q`);
  test-floor 作业的 numpy 1.26 没有 `np.trapezoid`(测试改用 conftest 的 shim;源码本来就有 shim)。
- ROADMAP P1 #1 判定:杂散随 TDC 分辨率变(5 ps −45.5 dBc @ 9.87 m,2 ps −55.8 dBc @ 10.07 m)、不随 Kdco 变、开环路噪声后不消失
  (2.2 / 7.81 m 处 −49 dBc)→ TDC 量化的鬼目标,物理,不是 `noise=False` 的产物。被推翻的判断:原以为是 dither 限环。
- 下一步:把鬼目标作为确定性杂散列表进统计引擎(ROADMAP P1 #1a);在线 dp_cal(P1 #2)。

## 2026-11-06 · 里程碑 1:单 chirp、单目标(ccr-dd350ddf-xv24an,0.1.0)

- 先量了 polar_tx event 引擎的有效域指标:chirp 上 **4.95 UI/周期(495 %)**,远超 10 %;但逐周期引擎在斜坡上与线性化引擎逐周期一致
  (5 % 失配飞回瞬态比值 1.005 ± 0.046),判断"指标不适用于 chirp,引擎可用",chirp 引擎直驱 `ADPLL.simulate`(`cairn/chirp-engine.md`)。
- **被推翻的判断**:"dp_cal 就是 chirp 线性度校准"——polar_tx 的 SignSignLMS 在锯齿上往错方向走(1.05 → 1.066);
  差分版能收敛但慢(1.05 → 1.006 / 20 chirp);离线 LS 一次到位(4.995 %),但要喂 ≥ 2 个连续 chirp(单 chirp 只估到 2.5 %)。
- 数字:匹配增益时误差底 0.54 MHz RMS(载波,5 ps TDC);5 % 失配 200 MHz 阶跃 1.47 µs 建立;
  5 m 目标 SNR 51.3 dB/格(64 chirp Hann),时域 51.06 对期望 51.06;相噪残余 51.7 mrad(LO 186.7);+1/+5 m 旁瓣 −64.3/−51.9 dBc/格。
- 被推翻的判断 2:FFT 上 +0.25 m 处量到的 −54 dBc 不是相噪是 Hann 主瓣;量旁瓣要 Blackman + 带平均闭式(`cairn/range-correlation.md`)。
- 被推翻的判断 3:LO 剖面 fref/2 以上平举底噪让拍频音掉 0.24 dB(exp(−σ²/2) 积到 2.5 GHz);改为 DCO-only,并把相干损失计入期望 SNR。
- 被推翻的判断 4:一阶旁瓣公式 S_res/2 在 100 m 处比时域低 21 dB —— 残余 0.3 rad 时带内相噪自拍出 −56 dBc 的底;
  换成高斯相位的精确谱(exp(R − R(0)) 的变换)后 2 m 处差 0.09 dB。5 m 目标 +0.1 m 处一阶也低 11 dB。
- 被推翻的判断 5:时域测相噪旁瓣以峰值格为基准会高 0.75 dB(拍频落在 0.43 格外,Blackman 的刻度损失);基准改为 16 倍零填充的峰。
- 修过的 bug:路径损耗 30·db(4π)(1069 dB);噪底估计含 IF 带外空格(+1 dB);多普勒符号反了;统计引擎的非线性剖面没过 IF 砖墙(与时域差 3 dB RMS)。
- 下一步:ROADMAP P1 #1(无噪声 event 引擎的量化杂散是物理还是产物)、里程碑 2 的 MIMO。

## 2026-11-06 · Project Cairn initialized

- Initialized Project Cairn structure.
- Historical migration mode: `start_fresh`.
- Details: see `AGENTS.md` and `.cairn/config.yaml`.

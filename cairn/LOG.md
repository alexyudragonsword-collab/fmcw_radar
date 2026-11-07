# Project Cairn 日志

本文件按倒序记录实质性进展 —— 最新条目在本行正下方。每条保持简短(数字原值、被推翻的判断、下一步),
结论沉淀进 `cairn/<topic>.md`。

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

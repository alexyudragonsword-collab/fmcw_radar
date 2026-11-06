---
type: project_topic
status: active
summary: "chirp 发生器 = vendored polar_tx 两点 ADPLL 喂斜坡:event 引擎在 chirp 上的有效域判断(495 % UI/周期但可用)、频率误差曲线的数(TDC 量化底 ~0.54 MHz RMS、5 % 失配 200 MHz 阶跃 1.5 µs 建立)、dp_cal 在锯齿上的行为(原版发散、差分版慢收敛、离线 LS 一次到位)。"
tags: [adpll, chirp, two-point, dp_cal, polar_tx]
contains: [decision, lesson, experience]
created: "2026-11-06"
updated: "2026-11-06"
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
- 所以 chirp 引擎直接驱动 `pll.simulate`(不经 `ADPLLTwoPoint._mod_event`,后者会告警并做去趋势),`freq_out − (fout + mod)` 就是曲线;
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

## 经验

- 一个 chirp 的 event 仿真 = settle 40k + 10k 周期 ≈ 0.1 s(纯 Python 逐周期);64 chirp 一帧 0.7 s。够用,不需要 numba。
- 时域引擎用 chirp 误差相位时在参考网格上线性插值 t 与 t − τ:频率逐周期恒定,相位分段线性,插值是精确的。
- **TDC 量化的"鬼目标"**(32 chirp 帧,5 m 目标,只开 chirp 误差):无噪声逐周期引擎在 9.87 m / 2.34 m/s(目标的多普勒行)处 −45.5 dBc;
  TDC 从 5 ps 改 2 ps 后降到 −55.8 dBc 并移到 10.07 m;Kdco 从 50 改 20 kHz 不动它(−46.2 dBc,9.87 m)。开 DCO / 参考噪声(`noise=True`,
  两个 seed)后变成 2.2 m 与 7.81 m 处 −48.6 … −50.2 dBc,位置不随 seed 变。
  判断:这是 TDC 量化的物理 —— 斜坡让每参考周期的小数相位以线性增长的速率转过 TDC 码,量化误差是一个二次相位的锯齿,其谐波本身是 chirp,
  与延迟副本混频后落在固定拍频上,即固定距离处的鬼目标(FMCW ADPLL 文献里的 DTC / TDC 鬼目标机制);不是 `noise=False` 的产物,
  噪声只把它打散到别的距离。按铁律 6 由 event 引擎背书,引擎里 TDC 没有 dither(pllsim `TDCConfig` 只有 INL / 抖动),所以是悲观一侧。

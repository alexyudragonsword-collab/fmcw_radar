---
type: project_topic
status: active
summary: "range correlation 的实现与验证:残余 PSD = 2(1 − cos 2πfτ)·S_φ,闭式与合成 0.1 dB 内;FFT 上量旁瓣要让窗的旁瓣低于相噪(Blackman);距离旁瓣随目标距离的曲线;LO 剖面 ×N 与 fref/2 以上的处理。"
tags: [phase-noise, range-correlation, lo, d2d_link]
contains: [decision, lesson]
created: "2026-11-06"
updated: "2026-11-06"
related: [architecture-invariants, chirp-engine]
authoring_mode: ai_generated
---
# range correlation

## 背景

铁律 2。与 d2d_link `clock/forwarded.py` 的树延时泄漏 `|1 − e^{−j2πfτ}|²` 是同一个式子;d2d 的测试模板
"相关 = 1 残余为零 / 跟踪带宽 → ∞ → 0 / → 0 时两路独立之和"在这里是"τ = 0 逐位为零 / τ → ∞ → 2 倍单边 / 中间按闭式"。

## 当前结论

- `RangeCorrelation`:闭式 `residual_psd`、`sidelobe_dbc(offset, enbw)`(= 残余 L(f) + 10 log 窗的每格噪声带宽)、
  合成 `synthesize_lo` → `residual = phi − delayed(phi)`(FFT 域循环延迟,平稳块上精确)。τ = 0 时 `delayed` 返回输入对象本身,减法逐位为零。
- 闭式 vs 合成:1 / 10 / 100 m 上按倍频程带平均差 **0.114 dB**(24 块 × 16384 点);测试用 32 块 × 65536 点卡 0.1 dB。
  三个距离差值完全相同不是巧合:同一白噪声实现经不同的确定性线性滤波,比值只由实现决定。
- 默认 60 GHz LO(15 GHz ADPLL ×4 占位剖面):L(1 MHz) ≈ −80 dBc/Hz。目标 5 m(τ 33 ns)时残余 51.7 mrad RMS(LO 自身 186.7 mrad,[10 kHz, 4 MHz]);
  距离维旁瓣(Hann,每格 15 kHz,单 chirp):+0.25 m 处 −75.2、+1 m −64.3、+5 m −51.9 dBc;距离–多普勒格再低 16.3 dB(64 chirp Hann 的相干增益)。
  随目标距离:同一距离偏移下的旁瓣每 10 倍距离升 20 dB,直到 1/(6τ) 越过该偏移(100 m 时 +5 m 处反而比 +1 m 低)。
- **一阶公式 S_res/2 只在残余小时成立。** 时域在 100 m(残余 0.3 rad)量到 −56 dBc 的平底,一阶给 −77:带内相噪自拍(φ² 项,谱是 S_res 的自卷积)。
  高斯相位的精确谱是 exp(R(t) − R(0)) 的变换(`RangeCorrelation.beat_sideband`,含各阶与载波损失 e^{−σ²}),与时域 2 m 处差 0.09 dB;
  5 m 目标 +0.1 m 处一阶 −88 对精确 −77 dBc。统计引擎的旁瓣表与期望 SNR 都用精确谱。
- **在 FFT 上量相噪旁瓣要让窗的旁瓣低于相噪**:Hann 在 3 格外 −32 dB、每倍频程降 18 dB,在 +0.25 m(2.7 格)处完全盖住 −80 dBc 的相噪;
  `measured_pn_sidelobes` 默认用 Blackman(−58 dB)、取 ±5 格平均、并把闭式也在同一组格上平均(残余 PSD 在带内有斜率,中心值 ≠ 带平均)。
  基准取 16 倍零填充的峰(拍频落在 0.43 格外时峰值格损失 0.75 dB,噪声格不损失)。结果:+1 / +2 / +5 m 差 +0.11 / −0.02 / −0.44 dB(64 chirp 平均),
  换 seed 摆 ±0.4 dB;测试在 1 / 10 / 100 m 上取 64 chirp × ±10 格卡 0.5 dB。
- LO 剖面 ×N:相位 ×N,PSD ×N²;倍频器自身底噪没有(assumed)。fref/2 以上的 analyze() 是采样环路的镜像,不用;
  那里取 DCO 自身的 Leeson 噪声到底噪。这一决定来自时域引擎:把 −113 dBc/Hz 平举到 2.5 GHz 时,拍频音的相干部分少了 0.24 dB
  (exp(−σ²/2),σ² 积到全带)——统计引擎现在把这一项(`pn_carrier_loss_db`)也算进"期望实测 SNR"。

## 教训

- 示例 01 第一版在 Hann 窗下 +0.25 m 处量到 −54 dBc 还以为闭式错了:量的是窗的主瓣。先问窗在那个偏移上是多少。
- 时域引擎按 chirp 独立合成相噪块(500k 点 @ 5 GS/s,最低 10 kHz):chirp 间的 LO 低频相关没有表示。在 IF 带内任何距离上,
  2(1 − cos) 在 10 kHz 以下至少 −50 dB,多普勒维的噪底是热噪声,不是相噪 —— 这是可以不表示的理由,不是没注意到。

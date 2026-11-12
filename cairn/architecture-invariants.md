---
type: project_topic
status: active
summary: "七条铁律的论证:为什么配置是唯一真值、为什么 range correlation 不许走捷径、为什么统计引擎是主引擎、为什么 chirp 非线性只能从环路来、来源标签、杂散只认逐周期引擎、数值指纹;每条守着它的测试。"
tags: [architecture, invariants, radar, range-correlation, adpll]
contains: [decision, lesson]
created: "2026-11-06"
updated: "2026-11-12"
related: [chirp-engine, range-correlation]
authoring_mode: ai_generated
---
# 架构铁律与论证

## 背景

本库是 mmw60_trx 的姊妹库而不是扩展:通信库的指标(EVM / ACLR / MCS)雷达一个都不用;雷达的核心机制 ——
TX / RX 共用 LO 的相噪经往返延迟后相关抵消 —— 在数学上和 d2d_link 的"前向时钟跟踪发端 PLL 相噪"是同一个式子
(`|1 − e^{−j2πfτ}|²` 作用在 PLL 的相位 PSD 上)。塞进通信库会让 config 变成两套东西的并集,Halo 把 UCIe 分出去就是这个理由。
polar_tx(main,现 pin b007e60;最初 7057738)被 vendor 进来做 chirp 发生器:线性调频 = 两点调制喂一个斜坡。

## 当前结论

1. **配置是唯一真值。** 一个 frozen `RadarConfig`(`config/schema.py`),示例、报表、指纹都从它出发;不是用户设计决定的数
   (前端占位、RCS、氧气吸收、窗表)不写在 config 里而是 `None` → `data/sources.yaml` 按频段取,带 `source` 标签。
   GUI 这一轮不做,但 `config/form.py` 已声明每个字段的表单行,测试卡住字段与表单双向一致。
2. **range correlation 是核心机制。** `phase_noise/range_correlation.py` 是唯一合成 LO 相噪的地方;时域引擎延迟同一条序列,
   不画第二条;config 里没有任何 RX 侧振荡器字段(`test_invariants.py::test_law2_*`)。τ = 0 时 `residual()` 返回 `phi − phi`
   (对象层面同一个数组),残余逐位为零。
3. **统计引擎是主引擎。** 雷达方程 + 窗的相干增益给格点 SNR;相噪旁瓣 = 残余 PSD/2 × 窗的等效噪声带宽;非线性旁瓣 = 误差曲线喂一次 FFT。
   时域引擎(5 GS/s 包络、真混频、砖墙 IF、ADC 量化)只做一致性检查:三个距离 < 1 dB(实测 −0.3 … −0.4 dB,见 LOG)。
4. **chirp 非线性从环路来。** `chirp/engine.py` 直接驱动 vendored `ADPLL.simulate(mod_freq=...)`,`freq_out` 就是瞬时频率误差曲线;
   解析二次项是 `quadratic_reference`,带 `engine="quadratic"` 标签,引擎目录里没有任何调用(`test_law4_*`)。
5. **目标是输入不是模型。** 点目标四个数由 config 给;RCS 取 `rcs.<kind>_dbsm`(survey)。
6. **杂散只认逐周期引擎。** `ChirpResult.vouches_for_spurs` 只有 `event` 为真;`response` 的 note 写明"线性化,不能背书"。
7. **数值指纹。** `tools/fingerprint.py` 记两个 bundled config + 7 个合成用例共 639 个值(标量 repr、数组 SHA-256),
   CI 对比 base 与 head,动了数要在提交信息里写 `(numbers-move: 为什么)`。

## 决策记录

- **vendor 的 pin 指向 polar_tx 而不是 pll_simulator**:polar_tx 自己嵌套的 pllsim 子树连同它的 `# Vendored from pll_simulator@...` 头一起拷进来,
  `vendor_check.py` 只剥最外层头(array_tx 的做法),剩下的和 polar_tx 的文件逐字节比。好处是 CI 只需检出一个姊妹库、一个 SHA。
- **chirp 引擎绕过 `ADPLLTwoPoint` 的 event 模式**:它做载波恢复式去趋势,雷达要的是 `freq_out` 本身。
  (更正 2026-11-12:原来还写着"它会因有效域指标 495 % UI/周期发 RuntimeWarning"——polar_tx a6c65f0 起这个告警没有了,有效域换成"TDC 量程盖住一个 DCO 周期",见 `chirp-engine.md`。)response 模式仍经 `ADPLLTwoPoint`(线性化参照)。见 `chirp-engine.md`。
- **相噪与量化不重复计**:chirp 引擎 `noise=False`(确定性的环路 + TDC / DCO 量化 + dither),随机相噪只经 `LOProfile`(analyze() 预算 ×N²)进入两个引擎。
- **LO 剖面在 fref/2 以上只取 DCO 自身的 Leeson 噪声**:采样环路的线性模型在 fref/2 以上是镜像(量化噪声折回),没有意义;
  环路在那里对 DCO 不起作用,所以剖面延到波形 Nyquist 时只用 DCO 的 1/f² 到底噪。拍频音的相干部分是 exp(−σ²/2),
  σ² 积到全接收带宽 —— 这一项(`pn_carrier_loss_db`)进了统计引擎的"期望实测 SNR"。

## 教训

- `30 · db(4π)` 写成了 `(4π)³` 的 dB:应是 `3 · db(4π)`(10 log 已在 db() 里)。路径损耗 1069 dB 一眼就错,靠的是示例把数打出来。
- 时域引擎的噪底估计要限制在 IF 带内:砖墙滤波后 IF 带外的格子是空的,全图取均值会把 SNR 读高 1 dB。
- 时域 SNR 对雷达方程要先扣格点失配(Hann 在 Doppler 维差半格 1.4 dB),否则 1 dB 判据是在和刻度误差比。

---
type: project_topic
status: active
summary: "里程碑 2 的知识:TDM-MIMO 虚拟阵列测角(位置之和、u 格点 DBF、TDM 多普勒相位补偿要用细多普勒、互耦三来源与校准、CRLB、斜视)、TX 泄漏(τ ≈ 0 无相噪但幅度压 P1dB / ADC,IF 高通的得失)、多目标遮蔽与 found_targets 的分格、CA-CFAR 的损失曲线。"
tags: [mimo, tdm, dbf, coupling, array_tx, leakage, hpf, cfar, multi-target]
contains: [decision, lesson, experience]
created: "2026-11-07"
updated: "2026-11-10"
related: [architecture-invariants, range-correlation]
authoring_mode: ai_generated
---
# TDM-MIMO 测角、TX 泄漏与多目标(里程碑 2 的知识)

> 当前真相。数字来自示例 05–08 与 `tests/test_mimo.py`、`tests/test_leakage.py`;复现方式在每节末尾。

## 1. 虚拟阵列是两个阵列位置的和

- `mimo.py::VirtualArray`:TX 位置 + RX 位置 → 虚拟位置;TX 间距默认 `n_rx × RX 间距`,得到一条填满的线(2 × 4 → 8 元,孔径 20 mm @ 60 GHz,
  波束宽 13.4°)。TX 间距不是 RX 间距的整数倍时 config 拒绝(`whole number of RX pitches`);等于 1 λ 时 8 元只占 6 个位置(重叠),`filled = False`。
- 测角是 u = sin θ 格点上的加窗 DFT(`angle_window`,默认 Hann,格点 `n_virtual × angle_pad`),抛物线插峰;理想快拍上 −40 / 0 / 20 / 55° 都在 0.05° 内,
  Hann 8 元的角旁瓣 −32 dB。
- **坑(contains:边缘波束的旁瓣读数)**:半波长栅格上谱在 u 里以 2 为周期,指向 ±1 附近的主瓣会从另一端绕回来;读旁瓣前把峰滚到格点中间
  (`estimate` 里按"位置差是 λ/2 的整数倍"判断周期性),否则 55° 读到 −2.5 dB 的"旁瓣"。`peak_sidelobe_of` 也改为:主瓣在到零点前跑出格点的那一侧不算。

## 2. TDM 的多普勒相位与它的补偿

- TX 轮流发,第 m 个 TX 块比第 0 个晚 m·PRI,目标多普勒 f_d 在块间加 2π f_d m PRI 的相位,看起来像 TX 间距上的一个角偏:2 m/s(f_d 800 Hz)在 2 × 4 阵列上偏 **2.71°**
  (`tdm_bias_deg`);时域引擎不补偿时读 +2.735°。不模糊速度减半:±6.25 m/s。
- **坑(contains:粗多普勒格补偿留 −1.5° 偏差)**:用多普勒 FFT 的格中心(每 TX 4 个 chirp → 1250 Hz 一格)补偿,800 Hz 的目标被按 1250 Hz 补,
  留 **−1.48°** 的系统偏差(界 0.023°)。改为在目标距离格上取相邻同 TX chirp 的相位推进(`doppler_fine_hz`,TX × RX 平均,单音的 ML 估计),
  偏差降到 +0.014°,RMS 0.050°(6 个 seed × 8 chirp;界 0.023°)。
  **更正(0.2.2)**:当时写的"剩下的是 ADC 量化与多普勒估计本身的噪声"是错的,见下一节;6 个 seed 的 RMS 本身只准到 ±29 %。

## 2b. 时域测角不在 CRLB 上:估计器自己的代价(0.2.2 归因)

- `VirtualArray.angle_error_budget`:加窗 DBF 峰在 TDM 快拍上的一阶(高 SNR)误差,对每个距离格样本 z[i, m, r] 的噪声线性,方差是系数平方和。
  默认 2 × 4、20°、2 m/s、每 chirp 距离格 SNR 35.0 dB:界 0.0231° × **1.088**(目标离多普勒格 −0.36 格,Hann(4) 的刻度损失 0.70 dB + 距离 0.03 dB)
  × **1.523**(8 元上 Hann 对均匀权:Σw²(x−x̄)²·Σ(x−x̄)² / (Σw(x−x̄)²)² = 2.32 的方差)× **1.011**(多普勒估计)= **0.0386°**;cos 元方向图再 × 1/cos θ = 1.064 → 0.041°。
- 多普勒估计只占 1 %:脉冲对估计(`doppler_fine_hz`)等权时望远镜求和成"最后一个 chirp 的相位减第一个",对 8 个虚拟通道平均,误差 1.7 Hz RMS;
  它与快拍通过这两个 chirp 相关(Hann(4) 的首样本权为 0),闭式里带着这个相关。
- 核对:快拍级蒙卡(引擎自己的估计器,4000 次)9 组配置与闭式差 ≤ 1.5 %;时域引擎 384 个 seed:全开 0.0395°(闭式 0.0386,+2.3 %),只留热噪声 0.0403°;
  同一批快拍用真多普勒读 0.0389°(闭式 0.0382),真多普勒 + 均匀权 0.0247°(闭式 0.0251 = 界 × 刻度损失)。ADC 量化(比热噪声低 16 dB)和相噪
  (5 m 处每 chirp 的公共相位 < 0.1 mrad,且对同一 chirp 的各 RX 是共模)都不在账上。
- **坑(contains:少量 seed 的 RMS 会骗人)**:N 个 seed 的 RMS 相对标准差是 1/√(2N):6 个 ±29 %,24 个 ±14 %,128 个 ±6 %。归因过程中 24 个 seed 读 0.0325(−16 %)、
  128 个读 0.0434(+12 %,2σ),384 个才收敛到 0.0395。里程碑 2 的"2 倍没有归因"= 1.77 倍的估计器代价 + 6 个 seed 的抽样误差(0.050 对 0.041,+22 %,不到 1σ)。
  示例 07 现在用 32 个 seed 并把 ±% 打出来(cos 元:0.042° 对期望 0.041°,真多普勒 + 均匀权 0.025° 对 0.027°);要 5 % 以内的对照得上百个。

## 3. 互耦:array_tx 的矩阵三来源,校准后残差 < 0.01°

- `mimo.coupling.source`:`analytic`(array_tx 的解析矩阵,相邻 c1 = −16 dB 占位 `source: assumed`、180°、次邻 −6 dB 相对)、`survey`(同一占位数经 survey 路径)、
  `touchstone`(S 参数文件,端口数必须等于 n_rx)。RX 耦合作用在每个 TX 块的 RX 快拍上:`c_rx = I + S_offdiag(f0)`。
- 未校准偏 **−0.29°**(20° 目标,相邻 −16 dB),角旁瓣从 −32 升到 −20.6 dB;`coupling.calibrated: true` 用逆矩阵,残差 +0.0002°(时域 32 个 seed:均值 +0.008°,RMS 0.044°,对期望散布 0.041°;未校准时均值 −0.284°)。
- 扫频带宽上的斜视(array_tx 的 `squint_analytic_deg`):相移器对准 60 GHz 的 TX 波束在 ±2 GHz 边沿偏 +0.72 / −0.67°,FR2 28 GHz / 400 MHz 的 ±0.15° 的 5 倍;
  虚拟阵列边缘元的拍频只偏 0.04 格、窗锥 −0.009 dB —— 带宽对测角本身无妨,对波束赋形的 TX 有妨。
- CRLB:var(u) = λ² / (8π² SNR Σ(x − x̄)²),N(N² − 1) 随元数、1/√SNR、1/cos θ(`crlb_sigma_deg`);20° 目标、每元 39.3 dB → 0.023°。

## 4. TX 泄漏:大但没有相噪,靠 IF 高通

- `link/leakage.py`:直接泄漏(隔离 25 dB 占位,τ 0.2 ns → 拍频 8 kHz)+ 近端反射体(2 cm,−10 dB 相对)。经同一 LO,τ ≈ 0 的 range correlation 让它几乎不带相噪
  (`window_sidelobe_at_target_db` −122 dBc:泄漏在目标格只剩窗旁瓣),但幅度:接收端 −15 dBm,P1dB 裕量 **−5 dB**(压缩),ADC 裕量 **−21 dB**(满幅削波,
  时域引擎 `clipped_fraction` > 0.9)。
- 2 阶 200 kHz 高通(`rx.hpf_corner_hz` / `rx.hpf_order`,`processing/iffilter.py` 的因果 Butterworth,闭式衰减与滤波一致 0.2 dB 内):8 kHz 衰 56 dB,
  ADC 裕量 +35 dB,削波 3.5 %(1 阶 2.7 %,2 阶 50 kHz 14.9 %);1.33 MHz 的目标拍频只衰 0.002 dB。
- **坑(contains:高通后泄漏仍是图上的峰)**:高通后泄漏 −31 dBm 仍比 5 m 人体 −47 dBm 高 16 dB,距离–多普勒图的峰在 0.03 m,目标在 5 m 处被 `found_targets` 找到,
  相对电平 −18.1 dB 对预算 −16.2 dB(32 chirp)。要目标成为峰得再 20 dB 隔离或更高阶高通 —— 这是物理,不是 bug。
- **坑(contains:飞回瞬态过高通削波)**:状态跨 chirp 连续并在第一个 chirp 前预热后,剩下的 3.5 % 削波是每个 chirp 开头的飞回瞬态经高通的响应:
  锯齿重启让每个泄漏音的相位跳 2π f_beat T_c,阶跃 2A|sin(Δφ/2)|(两项共 7.2 V)整个穿过高通(高通对阶跃不衰减),按最慢极点
  (阻尼 sin(π/2k),200 kHz 2 阶 τ = 1.13 µs)衰减。预算的闭式 `blank_recommended_s` = τ·(ln(阶跃/满幅) + 1):1 / 2 / 3 阶 3.2 / 4.5 / 6.4 µs,
  对时域量到的削波段 2.7 / 3.5 / 4.8 µs(都盖住,余量 1.2–1.3 倍)。
- **坑(contains:blanking 不能只把样本清零)**:在不变的 Hann 窗下把前 80 个样本清零,窗边出一个台阶,远旁瓣抬 20 dB 以上 —— 1 阶高通的例子里
  2–4 m 的底从 −94 **升到** −72 dBc。正确做法是距离窗按剩下的 n − k 个样本重配(`range_window`),近旁瓣不变、主瓣宽 n/(n − k)、SNR 损 10 log(n/(n − k))
  (4.5 µs / 100 µs:0.2 dB)。所有距离 FFT 与窗统计(预算 ENBW、刻度损失、相噪底表、非线性剖面、遮蔽表)都走同一个 `range_window`。
- **坑(contains:blanking 后剩的那一个削波样本)**:时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,下一个 chirp 的阶跃环回到本 chirp 的最后一个样本
  (每 chirp 1 个,窗权 ~1e-5);`clipped_fraction_after_blanking` 因此是 0.1 % 不是 0,ROADMAP P2 #0 记了因果 IF 滤波器。
- blanking 后的收益在有噪声的帧里看不见(2–4 m 的底本来就是热噪声),只在无噪声视图里显出来:2 阶 200 kHz 下瞬态把底相对目标抬到 −43.5 dB,
  blanking 后 −51.0 dB,无泄漏参照 −53.3 dB;剩下的差是瞬态在窗上升沿下未削波的尾巴。

## 5. 多目标与 CFAR 曲线

- `engine/statistical.py::target_rows`:每个目标的 ADC 电平、格点 SNR、最强的他者在本格的裙边(窗旁瓣包络 ±0.5 格内取最大,或相噪)与"被遮蔽"判断。
  30 cm 外 +20 dBsm 的车不遮蔽 5 m 人体(裙边 −43.7 dBc);5.05 m 处 −45 dBsm 的点在车的窗裙下(`masked`,`interference_kind = window`)。
- 时域 `found_targets`:每个目标在 ±3 距离格 / ±2 多普勒格内找峰。**坑(contains:邻目标的瓣被当成本目标)**:12 cm 外的 −20 dBsm 点原来"找到"的是车的主瓣
  (电平差 +30 dB);改为两目标分格(各自只搜离自己更近的格)且峰必须是距离维局部极大,之后找到 5.434 m −28.3 dB,对统计 −30.4 dB(车的裙边相干叠加)。
- CA-CFAR 的蒙卡(`cfar_pd_monte_carlo`,Swerling 0 / 1)对已知噪底闭式:Pd 0.9 处 CFAR 损失 N = 16 **1.35 dB**、N = 32 **0.74 dB**;Swerling 1 的闭式
  `cfar_pd_swerling1` 与蒙卡 0.02 内;−300 dB 的"目标"过阈率 = Pfa(±25 %)。时域引擎纯噪声帧 64000 格 4 个虚警(6.3e-5 对 1e-4)。
  **更正(0.2.3)**:那 4 个格是抽样(期望 5.2 格 ≈ 2 团),格相关对 Pfa 的两个效应与精确式见 `cairn/cfar-statistics.md`。

## 复现

```
python examples/05_multi_target_masking.py   # 遮蔽表、found_targets
python examples/06_cfar_curves.py            # Pd / Pfa 曲线与 CFAR 损失
python examples/07_mimo_angle.py             # 耦合三来源、TDM 补偿、CRLB、斜视
python examples/08_tx_leakage.py             # 泄漏预算、高通前后的削波
pytest tests/test_mimo.py tests/test_leakage.py
```

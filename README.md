# fmcw_radar

60 GHz 宽带 FMCW 雷达的行为级仿真框架:chirp 发生(vendored polar_tx 的两点 ADPLL 喂一个斜坡)、TX / RX 共用 LO 的相噪经往返延迟
的相关抵消(range correlation)、雷达方程、低速 ADC、距离–多普勒处理、CFAR;指标是距离 / 速度分辨率、相噪旁瓣、检测概率。
mmw60_trx 的姊妹库而不是扩展 —— 它的前端(PA / LNA / 阵列 / 封装 / LO ×N)到位之前,这里用一个解析占位前端(每项一个数,全标 `source: assumed`)。

里程碑 1(单 chirp、单目标)与里程碑 2(TDM-MIMO 测角、TX 泄漏、多目标 / CFAR 曲线)已交付;待办在 [`ROADMAP.md`](ROADMAP.md)。协作规则在 [`AGENTS.md`](AGENTS.md)。

## 用法

```bash
pip install -e ".[plot,test]"
python tools/budget_report.py configs/radar_60g_sensing.yaml     # 一页预算:雷达方程、来源、相噪旁瓣、chirp 线性度
python examples/00_single_target_rd_map.py                        # 图在 examples/output/
pytest -q
```

```python
from fmcw_radar.config import load_config
from fmcw_radar.engine import run_radar

cfg = load_config("configs/radar_60g_sensing.yaml", {"sim.engine": "both"})
res = run_radar(cfg)             # res.stat: 统计引擎(主);res.time: 时域交叉检查;res.chirp: ADPLL 的频率误差曲线
print(res.stat.snr_cell_db, res.time.snr_cell_db, res.stat.pn_floor[1.0])
```

配置是唯一真值(`src/fmcw_radar/config/schema.py`):频段(57–64 GHz 窗内,默认 58–62 GHz,B 可到 7 GHz)、chirp(锯齿,100 µs × 64)、
LO(15 GHz ADPLL ×4:fref、环路带宽、Kdco、TDC 分辨率、两点增益与校准方式、引擎)、前端占位、信道(自由空间 + 氧气)、点目标、
IF / ADC、窗与 CFAR、仿真。77 GHz 车载一档结构相同只换数(`configs/radar_77g_automotive.yaml`)。

## 模块地图

| 模块 | 做什么 | 铁律 |
|---|---|---|
| `config/` | frozen `RadarConfig`、YAML 加载、表单字段声明(GUI 以后做) | 1 |
| `sources.py` + `data/sources.yaml` | 每个不是设计决定的数:前端占位 `assumed`、文献 `survey`、原文 `spec` | 5 |
| `lo.py` | vendored ADPLL 的构造;LO 相噪剖面 = analyze() ×N²(fref/2 以上取 DCO 自身)或剖面文件 | 2 |
| `phase_noise/` | range correlation:残余 PSD = 2(1 − cos 2πfτ)·S_φ,合成与闭式 | 2 |
| `chirp/` | 斜坡经 event / response / ideal 引擎 → 瞬时频率误差曲线;离线 LS / 在线 sign-sign 两点校准 | 4, 6 |
| `link/` | 雷达方程、噪声密度、窗的相干增益、P1dB 裕量;TX 泄漏预算(直接 + 近端反射体,高通前后) | 3 |
| `processing/` | 窗、距离 / 多普勒 FFT、峰值读数、CA-CFAR 与它的蒙卡 Pd(Swerling 0 / 1)、相关格上的 CFAR 统计(`cfarstats`)、IF 高通 | — |
| `mimo.py` | TDM-MIMO 虚拟阵列:位置之和、u 格点 DBF、TDM 多普勒补偿、互耦(array_tx 三来源)与校准、CRLB、斜视 | 1, 5 |
| `engine/statistical.py` | 格点 SNR、分辨率、相噪旁瓣表、非线性旁瓣(误差曲线喂一次 FFT)、Pd;每目标一行与遮蔽、测角指标、泄漏 | 3 |
| `engine/timedomain.py` | 5 GS/s 包络真混频 → 泄漏音 → 砖墙 IF → 高通 → ADC 量化(削波)→ 距离–多普勒图 / MIMO 立方与 DBF | 3 |
| `report.py`, `tools/` | 预算一页、指纹、vendor 漂移、示例冒烟 / 漂移 | 7 |
| `vendor/polartx/` | polar_tx@7057738 的两点调制器、两点校准、嵌套的 pllsim 子树(逐字节校验) | — |
| `vendor/arraytx/` | array_tx@e897c15 的阵列几何、波束宽 / 斜视、互耦矩阵三来源、Touchstone 读写(coupling 为改编副本) | — |

## 默认配置的数(示例 00–04,`examples/expected/` 存全量输出)

- 60 GHz、B = 4 GHz、100 µs × 64、10 MS/s、Hann:c/2B 3.75 cm,Hann 下 5.34 cm;最大距离 15 m(IF 4 MHz);速度分辨率 0.39 m/s,±12.5 m/s。
- 人体(−10 dBsm,survey)5 m:P_r −87.1 dBm,C/N0 76.8 dBHz,格点 SNR 51.3 dB(矩形窗 54.8,窗损失 3.5 dB),Pd = 1 @ Pfa 1e-4;
  时域引擎在同一格读 51.06 dB,与统计引擎扣掉格点失配、带内相噪与拍频音相干损失后的期望 51.06 dB 差 0.00 dB(三个距离 −0.07 … −0.10 dB)。
- LO(占位 15 GHz ADPLL ×4)L(1 MHz) −80 dBc/Hz;5 m 处残余 51.7 mrad(LO 自身 186.7);距离维旁瓣 +1 m −64.3、+5 m −51.9 dBc/格(单 chirp,
  高斯相位的精确谱;一阶 S_res/2 在近目标处低估:100 m 目标 +0.25 m 处差 8 dB),距离–多普勒格再低 16.3 dB。τ = 0 残余逐位为零;
  1 / 10 / 100 m 残余 PSD 闭式 vs 合成 0.11 dB;FFT 上量到的旁瓣 +1 / +2 / +5 m 差 +0.11 / −0.02 / −0.44 dB。
- chirp:匹配增益时误差底 0.54 MHz RMS(5 ps TDC 经环路);5 % 两点失配 → 飞回 200 MHz 阶跃、1.47 µs 建立、距离响应 ISLR −29 dB(IF 砖墙之后);
  离线校准两次把失配压到 1e-4,在线校准(飞回后 20 周期的 LMS)四个 chirp 内到 ±0.05 %。event 与 response 在瞬态上逐周期一致(比值 1.005 ± 0.046);
  误差曲线喂统计引擎与时域引擎的剖面逐点相同;TDC 量化的鬼目标(5 ps:±4.85 m 处 −45.3 dBc)从同一条曲线里报出。

## 里程碑 2 的数(示例 05–08,`configs/radar_60g_mimo.yaml`)

- 2 TX × 4 RX、RX 间距 0.5 λ、TX 间距 2 λ → 8 元填满的线,孔径 20 mm,波束宽 13.4°;20° 目标每元 39.3 dB,CRLB 0.023°;理想快拍 DBF 读 20.000°,Hann 角旁瓣 −32 dB。
  TDM 把不模糊速度减半到 ±6.25 m/s,2 m/s 的块间多普勒相位不补偿偏 +2.71°(时域 +2.72°),补偿后时域 32 个 seed 均值 +0.008°、RMS 0.042°。
  这个估计器不在界上(0.2.2 归因):期望散布 0.041° = 界 × 1.064(cos 元方向图 @ 20°)× 1.088(目标离多普勒格 0.36 格的刻度损失)× 1.523(8 元上的 Hann 角窗对均匀权)
  × 1.011(TDM 补偿用的多普勒估计);各向同性元 384 个 seed 的时域 RMS 0.0395° 对闭式 0.0386°(+2.3 %,抽样 ±3.6 %),同一批快拍用真多普勒 + 均匀权重读 0.0247° 对 0.0251°。
- 互耦(array_tx,相邻 −16 dB 占位):未校准偏 −0.29°、角旁瓣升到 −20.6 dB;校准后 +0.0002°(时域 32 个 seed 均值 +0.008°、RMS 0.044°,与无耦合的 0.042° 同)。扫频斜视:相移器对准 60 GHz 的 TX 波束在 ±2 GHz 边沿 +0.72 / −0.67°
  (FR2 28 GHz / 400 MHz ±0.15°);虚拟阵列边缘元的拍频只偏 0.04 格。
- TX 泄漏(隔离 25 dB 占位,τ 0.2 ns → 8 kHz;2 cm 反射体 −10 dB):接收端 −15 dBm,P1dB 裕量 −5 dB,ADC 裕量 −21 dB(时域 100 % 削波);
  2 阶 200 kHz 高通衰 56 dB → 裕量 +35 dB、削波 3.5 %(飞回瞬态),5 m 人体在泄漏下 −18.1 dB 处(预算 −16.2 dB)。
  飞回瞬态(0.2.1):锯齿重启让泄漏拍频相位跳变,7.2 V 的阶跃整个穿过高通(时间常数 1.13 µs),预算推荐 blanking 4.5 µs(阶跃落到满幅以下 + 1 个时间常数),
  `rx.blank_s` 照此 blanking 后进 FFT 的削波样本为零、距离窗按剩下的 955 个样本重配(SNR 损失 0.2 dB,分辨率宽 4.7 %),无噪声时 2–4 m 的底从瞬态抬高的 −43.5 dB 回到 −51.0 dB(无泄漏参照 −53.3 dB)。
- 四目标(人 5 m / 车 5.3 m / 人 9.9 m / −20 dBsm 点 5.42 m):统计引擎的遮蔽判断全为否(最强他者的窗裙 −43.7 … −7.7 dBc),时域各目标电平对统计 0.0 / 0.0 / +0.8 / +2.1 dB。
- CA-CFAR 对已知噪底(Pfa 1e-4,Pd 0.9):N = 16 损失 1.35 dB、N = 32 0.73 dB;Swerling 1 在 N = 16 要 20.0 dB。
- 图上的 CA-CFAR(0.2.3):窗与 ×4 零填充让 416 个训练格只值 33.4 个独立格(单看 Pfa 1e-4 → 2.7e-4),guard 2 个填充格 = 0.5 个距离格让训练格与被测格相关 0.015
  (单看 → 2.6e-5);两项几乎抵消,精确式 1.02e-4。白噪声经同样处理 1.54e7 格实测 1.062e-4(641 团,±4 %),时域纯噪声帧 6 帧 9.2e-5(25 团);32 chirp 一帧 51200 个带内格 = 3385 次独立观测,期望 5.2 个虚警格。

## 建模口径与已知边界

- 倍频器理想(相噪 +20 log N,无自身底噪);前端与 TX-RX 隔离、互耦都是占位(`source: assumed`);泄漏只有直接路径 + 一个近端反射体。
- 时域引擎按 chirp 独立合成相噪(最低 10 kHz),chirp 间 LO 低频相关没有表示(论证见 `cairn/range-correlation.md`)。
- polar_tx 的 event 有效域指标(每参考周期相位推进)在 chirp 上读 495 %;本库的判断是该指标针对亚周期相位轨迹、不适用于频率斜坡,
  证据与保留意见在 `cairn/chirp-engine.md`。`lo.engine: response` 是线性化引擎,不能背书杂散。
- CA-CFAR 是最简版(2-D 方窗,guard / train 按填充格数);`pd` 仍是已知噪底的闭式,CFAR 损失由示例 06 的蒙卡曲线给。MIMO 的非相干和图仍用单通道阈值因子(K = 8 多丢 5.1 dB,ROADMAP P1 #3)。示例 00 的 64 chirp 帧里 CFAR 在目标主瓣外还报 12 个格:无噪声逐周期引擎的量化杂散(ROADMAP P1 #1)。
- 测角只有 DBF(加窗 DFT + 抛物线插峰),没有 MUSIC / ESPRIT;TDM 的多普勒补偿在目标格上估单音频率,多目标同格时取其合成。
- blanking 只盖 chirp 开头;时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,会把下一个 chirp 的阶跃环回到本 chirp 的最后一个样本(每 chirp 1 个样本仍削波,窗权 ~1e-5)。

# fmcw_radar

60 GHz 宽带 FMCW 雷达的行为级仿真框架:chirp 发生(vendored polar_tx 的两点 ADPLL 喂一个斜坡)、TX / RX 共用 LO 的相噪经往返延迟
的相关抵消(range correlation)、雷达方程、低速 ADC、距离–多普勒处理、CFAR;指标是距离 / 速度分辨率、相噪旁瓣、检测概率。
mmw60_trx 的姊妹库而不是扩展 —— 它的前端(PA / LNA / 阵列 / 封装 / LO ×N)到位之前,这里用一个解析占位前端(每项一个数,全标 `source: assumed`)。

里程碑 1(单 chirp、单目标)已交付;MIMO 测角、TX 泄漏、多目标 / CFAR 曲线在 [`ROADMAP.md`](ROADMAP.md)。协作规则在 [`AGENTS.md`](AGENTS.md)。

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
| `link/` | 雷达方程、噪声密度、窗的相干增益、P1dB 裕量 | 3 |
| `processing/` | 窗、距离 / 多普勒 FFT、峰值读数、CA-CFAR、Swerling 0 检测概率 | — |
| `engine/statistical.py` | 格点 SNR、分辨率、相噪旁瓣表、非线性旁瓣(误差曲线喂一次 FFT)、Pd | 3 |
| `engine/timedomain.py` | 5 GS/s 包络真混频 → 砖墙 IF → ADC 量化 → 距离–多普勒图 | 3 |
| `report.py`, `tools/` | 预算一页、指纹、vendor 漂移、示例冒烟 / 漂移 | 7 |
| `vendor/polartx/` | polar_tx@7057738 的两点调制器、两点校准、嵌套的 pllsim 子树(逐字节校验) | — |

## 默认配置的数(示例 00–04,`examples/expected/` 存全量输出)

- 60 GHz、B = 4 GHz、100 µs × 64、10 MS/s、Hann:c/2B 3.75 cm,Hann 下 5.34 cm;最大距离 15 m(IF 4 MHz);速度分辨率 0.39 m/s,±12.5 m/s。
- 人体(−10 dBsm,survey)5 m:P_r −87.1 dBm,C/N0 76.8 dBHz,格点 SNR 51.3 dB(矩形窗 54.8,窗损失 3.5 dB),Pd = 1 @ Pfa 1e-4;
  时域引擎在同一格读 51.06 dB,与统计引擎扣掉格点失配、带内相噪与拍频音相干损失后的期望 51.06 dB 差 0.00 dB(三个距离 −0.07 … −0.10 dB)。
- LO(占位 15 GHz ADPLL ×4)L(1 MHz) −80 dBc/Hz;5 m 处残余 51.7 mrad(LO 自身 186.7);距离维旁瓣 +1 m −64.3、+5 m −51.9 dBc/格(单 chirp,
  高斯相位的精确谱;一阶 S_res/2 在近目标处低估:100 m 目标 +0.25 m 处差 8 dB),距离–多普勒格再低 16.3 dB。τ = 0 残余逐位为零;
  1 / 10 / 100 m 残余 PSD 闭式 vs 合成 0.11 dB;FFT 上量到的旁瓣 +1 / +2 / +5 m 差 +0.11 / −0.02 / −0.44 dB。
- chirp:匹配增益时误差底 0.54 MHz RMS(5 ps TDC 经环路);5 % 两点失配 → 飞回 200 MHz 阶跃、1.47 µs 建立、距离响应 ISLR −29 dB(IF 砖墙之后);
  离线校准两次把失配压到 1e-4。event 与 response 在瞬态上逐周期一致(比值 1.005 ± 0.046);误差曲线喂统计引擎与时域引擎的剖面逐点相同。

## 建模口径与已知边界

- 倍频器理想(相噪 +20 log N,无自身底噪);前端是占位;TX 泄漏不在里程碑 1。
- 时域引擎按 chirp 独立合成相噪(最低 10 kHz),chirp 间 LO 低频相关没有表示(论证见 `cairn/range-correlation.md`)。
- polar_tx 的 event 有效域指标(每参考周期相位推进)在 chirp 上读 495 %;本库的判断是该指标针对亚周期相位轨迹、不适用于频率斜坡,
  证据与保留意见在 `cairn/chirp-engine.md`。`lo.engine: response` 是线性化引擎,不能背书杂散。
- CA-CFAR 是最简版;Pd 是已知噪底的闭式,不含 CFAR 损失。示例 00 的 64 chirp 帧里 CFAR 在目标主瓣外还报 12 个格:无噪声逐周期引擎的量化杂散(ROADMAP P1 #1)。

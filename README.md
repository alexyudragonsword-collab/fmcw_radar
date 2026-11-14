# fmcw_radar

60 GHz 宽带 FMCW 雷达的行为级仿真框架:chirp 发生(vendored polar_tx 的两点 ADPLL 喂一个斜坡)、TX / RX 共用 LO 的相噪经往返延迟
的相关抵消(range correlation)、雷达方程、低速 ADC、距离–多普勒处理、CFAR;指标是距离 / 速度分辨率、相噪旁瓣、检测概率。
mmw60_trx 的姊妹库而不是扩展 —— 前端是一个解析模型(每项一个数,带来源标签):0.2.8 起 60 GHz 档的发射功率、NF、两个接收压缩点、收发隔离读 mmw60_trx 来源表里读过原文的条目(`source: spec`),天线增益、RX 增益档、LO 仍是占位(`source: assumed`)。

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
LO(15 GHz ADPLL ×4:fref、环路带宽、Kdco、TDC 分辨率、两点增益与校准方式、引擎)、前端占位、信道(自由空间 + 氧气:ITU-R P.676 干空气海平面,60 GHz 14.65 dB/km、77.5 GHz 0.091 dB/km,不含水汽)、点目标、
IF / ADC、窗与 CFAR、仿真。77 GHz 车载一档结构相同只换数(`configs/radar_77g_automotive.yaml`)。

## 模块地图

| 模块 | 做什么 | 铁律 |
|---|---|---|
| `config/` | frozen `RadarConfig`、YAML 加载、表单字段声明(GUI 以后做) | 1 |
| `sources.py` + `data/sources.yaml` | 每个不是设计决定的数:占位 `assumed`、文献 `survey`、原文 `spec`、由原文按公式算出的 `derived`;`upstream:` 指向共享库 spec_sources 的条目(只查找),加载时核对两边相等 | 5 |
| `lo.py` | vendored ADPLL 的构造;LO 相噪剖面 = analyze() ×N²(fref/2 以上取 DCO 自身)或剖面文件 | 2 |
| `phase_noise/` | range correlation:残余 PSD = 2(1 − cos 2πfτ)·S_φ,合成与闭式 | 2 |
| `chirp/` | 斜坡经 event / response / ideal 引擎 → 瞬时频率误差曲线;离线 LS / 在线 sign-sign 两点校准 | 4, 6 |
| `link/` | 雷达方程、噪声密度、窗的相干增益、P1dB 裕量;TX 泄漏预算(直接 + 近端反射体,高通前后) | 3 |
| `processing/` | 窗、距离 / 多普勒 FFT、峰值读数、CA-CFAR 与它的蒙卡 Pd(Swerling 0 / 1)、相关格上的 CFAR 统计(`cfarstats`)、IF 高通 | — |
| `mimo.py` | TDM-MIMO 虚拟阵列:位置之和、u 格点 DBF、TDM 多普勒补偿、互耦(array_tx 三来源)与校准、CRLB、斜视 | 1, 5 |
| `engine/statistical.py` | 格点 SNR、分辨率、相噪旁瓣表、非线性旁瓣(误差曲线喂一次 FFT)、Pd;每目标一行与遮蔽、测角指标、泄漏 | 3 |
| `engine/timedomain.py` | 5 GS/s 包络真混频 → 泄漏音 → 砖墙 IF → 高通 → ADC 量化(削波)→ 距离–多普勒图 / MIMO 立方与 DBF | 3 |
| `report.py`, `tools/` | 预算一页、指纹、vendor 漂移、示例冒烟 / 漂移 | 7 |
| `vendor/polartx/` | polar_tx@b007e60 的两点调制器、两点校准、嵌套的 pllsim 子树(pll_simulator@5564c64,逐字节校验) | — |
| `vendor/spec_sources/` | spec_sources@d7b4d1e 的读取器与一张表(`reader.py` + `data/frontend60.yaml`):60 GHz 雷达前端的数从这里读 | 5 |
| `vendor/mmw60/` | mmw60_trx@ef0f00c 的一个文件:×10 LO 相噪剖面(`configs/radar_60g_x10lo.yaml` 读它) | — |
| `vendor/arraytx/` | array_tx@e897c15 的阵列几何、波束宽 / 斜视、互耦矩阵三来源、Touchstone 读写(coupling 为改编副本) | — |

## 默认配置的数(示例 00–04,`examples/expected/` 存全量输出)

- 60 GHz、B = 4 GHz、100 µs × 64、10 MS/s、Hann:c/2B 3.75 cm,Hann 下 5.34 cm;最大距离 15 m(IF 4 MHz);速度分辨率 0.39 m/s,±12.5 m/s。
- 前端(0.2.8):发射 12 dBm、NF 12 dB、两个接收压缩点(带外 −12 dBm、带内 −34 dBm @ 40 dB 增益)、收发隔离 20 dB 是读过原文的数(一颗 60 GHz 雷达芯片的手册、一篇板上阵的文章,
  经共享库 spec_sources,最初经 mmw60_trx 的来源表);天线增益各 10 dBi、RX 增益 40 dB 仍是占位。
- 人体(−10 dBsm,spec:77 GHz 行人射线追踪仿真的同极化下端)5 m:P_r −85.1 dBm,C/N0 76.8 dBHz,格点 SNR 51.3 dB(矩形窗 54.9,窗损失 3.5 dB),Pd = 1 @ Pfa 1e-4;
  时域引擎在同一格读 50.96 dB,与统计引擎扣掉格点失配、带内相噪与拍频音相干损失后的期望 50.91 dB 差 +0.05 dB(三个距离 +0.18 / −0.01 / −0.04 dB;0.2.5 量的 12 个 seed 平均 ±0.06 dB 内,那时 TDC 是 5 ps)。
- LO(占位 15 GHz ADPLL ×4,TDC 12.2 ps(spec:一颗 60 GHz FMCW ADPLL 的原文)、抖动 1 ps(占位))L(1 MHz) −75.9 dBc/Hz,带内的底是 TDC 量化(−77.5);
  5 m 处残余 84.0 mrad(LO 自身 319.4);距离维旁瓣 +1 m −58.4、+5 m −47.7 dBc/格(单 chirp,
  高斯相位的精确谱;一阶 S_res/2 在近目标处低估:100 m 目标 +0.25 m 处差 8 dB),距离–多普勒格再低 16.3 dB。τ = 0 残余逐位为零;
  1 / 10 / 100 m 残余 PSD 闭式 vs 合成 0.11 dB;FFT 上量到的旁瓣 +1 / +2 / +5 m 差 +0.11 / −0.04 / −0.45 dB。
  0.2.11 及以前 TDC 是 5 ps 的占位:L(1 MHz) −79.6、残余 55.3 mrad、旁瓣 −63.3 / −51.4 dBc/格。
- 换成 mmw60_trx 的 ×10 LO(`configs/radar_60g_x10lo.yaml`,6 GHz 分数 N PLL ×10):文件本身 L(1 MHz) −98.6 dBc/Hz,但 chirp 仍由本库的两点 ADPLL 生成,
  它 12.2 ps TDC 的量化留在曲线里,加上后 −77.5;5 m 处残余 69.6 mrad(本库自己的 LO 84.0),+5 m 的底 −49.4 dBc/格(自己的 LO −47.7,文件单独 −69.9)。带内的底是发生器的 TDC,不是 LO(示例 01 末表)。
- chirp:匹配增益时误差底 1.25 MHz RMS(12.2 ps TDC 经环路;5 ps 时 0.54),ISLR −22.6 dB(5 ps 时 −28.6);5 % 两点失配 → 飞回 200 MHz 阶跃、1.06 µs 建立(到 ±6.2 MHz,量化底变宽了;5 ps 时 1.47 µs 到 ±4.0 MHz)、距离响应 ISLR −23 dB(IF 砖墙之后);
  离线校准两次把失配压到 1e-4 以下,在线校准(飞回后 20 周期的 LMS)四个 chirp 内到 ±0.07 %。event 与 response 在瞬态上逐周期一致(比值 1.02 ± 0.19,量化底 1.24 MHz 压在 40 个周期上;5 ps 时 1.005 ± 0.046);
  误差曲线喂统计引擎与时域引擎的剖面逐点相同;TDC 量化在斜坡上的图样:不抖动(noise=False 的曲线)−10.31 / ±2.81 m 处 −34.1 … −35.5 dBc;
  开环路噪声后一帧里相干留下的,TDC 抖动 0 / 0.5 / 1 / 2 ps 时 −35.7 / −36.3 / −37.5 / −41.1 dBc,全在检出限(−52 … −56 dBc)之上(32 个 ramp,示例 02):
  1 ps 只有 0.08 个量化格,打不散 12.2 ps 的量化(5 ps 时是 0.2 格:−49.1 / −50.7 / −54.8 dBc / 低于检出限)。ROADMAP P1 #1(a)。

## 里程碑 2 的数(示例 05–08,`configs/radar_60g_mimo.yaml`)

- 2 TX × 4 RX、RX 间距 0.5 λ、TX 间距 2 λ → 8 元填满的线,孔径 20 mm,波束宽 13.4°;20° 目标每元 39.3 dB,CRLB 0.023°;理想快拍 DBF 读 20.000°,Hann 角旁瓣 −32 dB。
  TDM 把不模糊速度减半到 ±6.25 m/s,2 m/s 的块间多普勒相位不补偿偏 +2.71°(时域 +2.73°),补偿后时域 32 个 seed 均值 +0.009°、RMS 0.044°(0.2.11 及以前 +0.010° / 0.042°:相噪的实现随 TDC 变了)。
  这个估计器不在界上(0.2.2 归因):期望散布 0.041° = 界 × 1.064(cos 元方向图 @ 20°)× 1.088(目标离多普勒格 0.36 格的刻度损失)× 1.523(8 元上的 Hann 角窗对均匀权)
  × 1.011(TDM 补偿用的多普勒估计);各向同性元 384 个 seed 的时域 RMS 0.0395° 对闭式 0.0386°(+2.3 %,抽样 ±3.6 %),同一批快拍用真多普勒 + 均匀权重读 0.0247° 对 0.0251°。
- 互耦(array_tx,相邻 −16 dB 占位):未校准偏 −0.29°、角旁瓣升到 −20.6 dB;校准后 +0.0002°(时域 32 个 seed 均值 +0.007°、RMS 0.042°,与无耦合的 0.042° 同)。扫频斜视:相移器对准 60 GHz 的 TX 波束在 ±2 GHz 边沿 +0.72 / −0.67°
  (FR2 28 GHz / 400 MHz ±0.15°);虚拟阵列边缘元的拍频只偏 0.04 格。
- TX 泄漏(发射 12 dBm、隔离 20 dB:不加隔离结构的板上阵,读过原文;τ 0.2 ns → 8 kHz;2 cm 反射体 −10 dB):接收端 −8 dBm,比高通之前的压缩点(−12 dBm)高 4 dB。
  0.2.9 起接收机有两级压缩(高通前后各一级 Rapp,`link/compression.py`,两个引擎都算):前级把泄漏压掉 5.2 dB,代价是回波掉 10.65 dB、热噪声掉 8.35 dB、**SNR 掉 2.3 dB**
  (`radar_60g_mimo` 格点 SNR 51.3 → 48.7 dB);两个引擎对同一帧差 ≤ 0.35 dB。2 阶 200 kHz 高通后 ADC 裕量 +33 dB、削波 3.6 %(飞回瞬态),5 m 人体在泄漏下 −28.3 dB 处;
  1 阶 200 kHz 也有 5.3 dB 裕量(线性接收机时它在满幅、78 % 削波——0.2.8 的"1 阶不够"是线性接收机的结论)。飞回瞬态:阶跃 8.8 V 穿过高通(时间常数 1.13 µs),
  预算推荐 blanking 4.8 µs(落进 ADC 在稳态泄漏之上还剩的量程 + 1 个时间常数;稳态泄漏本身到满幅时不给,改报还缺多少衰减),blank 后每 chirp 末尾剩 1 个削波样本(引擎的循环砖墙)。
  `frontend.compression: false` 是线性接收机:泄漏在 ADC 处 32 dBm,阶跃 16.1 V,推荐 5.5 µs。
- 四目标(人 5 m / 车 5.3 m / 人 9.9 m / −20 dBsm 点 5.42 m):统计引擎的遮蔽判断全为否(最强他者的窗裙 −43.7 … −7.7 dBc),时域各目标电平对统计 0.0 / 0.0 / +0.6 / +2.0 dB。
- CA-CFAR 对已知噪底(Pfa 1e-4,Pd 0.9):N = 16 损失 1.35 dB、N = 32 0.73 dB;Swerling 1 在 N = 16 要 20.0 dB。
- 图上的 CA-CFAR(0.2.3):窗与 ×4 零填充让 416 个训练格只值 33.4 个独立格(单看 Pfa 1e-4 → 2.7e-4),guard 2 个填充格 = 0.5 个距离格让训练格与被测格相关 0.015
  (单看 → 2.6e-5);两项几乎抵消,精确式 1.02e-4。白噪声经同样处理 1.54e7 格实测 1.062e-4(641 团,±4 %),时域纯噪声帧 6 帧 9.2e-5(25 团);32 chirp 一帧 51200 个带内格 = 3385 次独立观测,期望 5.2 个虚警格。
  TDC 鬼目标按稳态目标进虚警账(0.2.6 起取一帧里开噪声后仍相干的那部分):12.2 ps TDC、占位的 1 ps 抖动下 −37.3 … −39.7 dBc,
  5 m 人体(每 look 50.9 dB)的鬼目标 SNR +11 … +13.6 dB,每帧 **2.75** 个(视野内 +2.81 m、−2.81 m、+8.43 m 三个,Pd 0.98 / 0.98 / 0.79);
  示例 00 主瓣外 35 格(0.2.11 及以前 5 ps:−55 dBc、每帧 0.00 个、主瓣外 22 格);四目标的帧里 +10 dBsm 的车把超门限格从 70 推到 284(示例 05)。
  把抖动设成 0 时角反射器目标下视野内的全中,时域引擎同。

## 建模口径与已知边界

- 倍频器理想(相噪 +20 log N,无自身底噪);天线增益、RX 增益档、LO、互耦、77 GHz 一档的全部仍是占位(`source: assumed`);60 GHz 的发射功率 / NF / 压缩点 / 隔离是一颗雷达芯片与一篇文章的数,不是某个具体前端的;
  接收机不建模压缩(只报对两个压缩点的裕量,默认配置下泄漏比带外压缩点高 4 dB);泄漏只有直接路径 + 一个近端反射体。
- 时域引擎按 chirp 独立合成相噪(最低 10 kHz),chirp 间 LO 低频相关没有表示(论证见 `cairn/range-correlation.md`)。
- LO 的噪声在时域引擎里只算一遍(0.2.5):逐周期 chirp 曲线已经带的不再从剖面合成。0.2.6 起默认用带噪声的曲线(环路到 fref/2 的全部;TDC 抖动去打散量化,但 1 ps 对 12.2 ps 的 TDC 只有 0.08 格,打不散:ROADMAP P1 #1(a)),
  剖面只合成 fref/2 以上;`run_time(chirp_noise=False)` 是不抖动的确定性曲线 + 去掉量化项的剖面。TDC 抖动(占位 1 ps)在线性剖面里是与量化同形的一项。
  0.2.4 及以前把曲线叠在整份剖面上,1–5 m 的 LO 底比分工后高 1.1 dB(比闭式高 1.5–2.2 dB)。斜坡上逐周期引擎与线性剖面 0.6 dB 内一致(5 ps TDC 时;0.2.12 起默认的 12.2 ps / 1 ps 抖动下 100 / 300 kHz 差 ±3.5 dB,半格抖动时回到 1.2 dB 内);CW 下线性模型低估带内相噪 15 dB(TDC 死区)。
- chirp 每参考周期相位推进 495 % UI,曾超出 polar_tx 给 event 引擎声明的有效域(< 10 %);polar_tx#19 之后这个域取消了(真正的条件是 TDC 量程盖住一个 DCO 周期,
  本库 23 个(12.2 ps × 127 = 1549 ps);盖不住的配置 `build_adpll` 直接拒绝)。斜坡真正的代价是 DCO 偏离标称周期 ±3.3 %、TDC 按标称周期归一化:不抖动的鬼目标因此高约 2.4 dB(5 ps TDC 时量的),
  数与复现在 `cairn/chirp-engine.md`、ROADMAP P1 #2。`lo.engine: response` 是线性化引擎,不能背书杂散。
- CA-CFAR 是最简版(2-D 方窗,guard / train 按填充格数);`pd` 仍是已知噪底的闭式,CFAR 损失由示例 06 的蒙卡曲线给。0.2.4 起 MIMO 的非相干和图用 K-look 阈值因子(K = 8:4.6 dB 而不是 9.7 dB),训练窗按图的轴长裁剪,`StatResult.cfar` 给含目标自漏的 Pd(默认图上 Pd 0.9 要 12.24 dB,CFAR 损失 0.49 dB)。示例 00 的 64 chirp 帧里 CFAR 在目标主瓣外还报 35 个格(成团):期望 10.5 个噪声虚警格加 2.75 个鬼目标(0.2.4 更正:此前标成量化杂散;0.2.11 及以前 5 ps TDC 时主瓣外 22 格、鬼目标 0.00 个)。
- 测角只有 DBF(加窗 DFT + 抛物线插峰),没有 MUSIC / ESPRIT;TDM 的多普勒补偿在目标格上估单音频率,多目标同格时取其合成。
- blanking 只盖 chirp 开头;时域引擎的 IF 砖墙是逐 chirp 的循环 FFT 滤波,会把下一个 chirp 的阶跃环回到本 chirp 的最后一个样本(每 chirp 1 个样本仍削波,窗权 ~1e-5)。

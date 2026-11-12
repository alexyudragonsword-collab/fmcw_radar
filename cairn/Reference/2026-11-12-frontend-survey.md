# 60 GHz 雷达前端的公开数字:第一轮查到的(2026-11-12)

外部原始输入,只追加。起因:mmw60_trx#14 问 fmcw_radar 有没有 TX→RX 隔离、接收 NF / 压缩点、天线增益的带出处的数(没有),这是当天查的一轮,
已贴在该 issue 下。**全部未核实**:只读到搜索摘要,原文一份没打开(云会话的网络策略不放行 ti.com / infineon.com 等)。
本库的 `sources.yaml` 没有因此改动;占位等 mmw60_trx 的 `Frontend60` 落地后一次换掉。

| 项 | 数 | 出处 | 条件 / 备注 |
|---|---|---|---|
| RX 噪声系数 | 12 dB | TI IWR6843 数据手册 SWRS219F(2025-04 修订),RF specification 表 | 60–64 GHz。IWR6843AOP(SWRS237B)给"等效全向噪声系数"9 dB,含天线 |
| RX 输入压缩点 | −12 dBm | 同上 | **带外** P1dB,脚注:远低于最低高通截止的 10 kHz 连续波。带内 P1dB 随增益变,在一张图里,摘要读不出可靠的数 |
| RX 链增益 | 最大 48 dB,范围 18 dB,步进 2 dB | 同上 | IF 带宽 10 MHz |
| TX 输出功率 | 12 dBm,回退范围 26 dB | 同上 | TI 参考设计 TIDUEI1C 写 10 dBm,不一致。AOP 单发 EIRP 15 dBm |
| 天线增益(封装内天线) | 2.0 / 3.5 / 5.0 dBi(最小 / 典型 / 最大) | Infineon BGT60TR13C 应用笔记 AN600 | 单个 TX 天线;RX 半功率波束宽 50–80° |
| 天线增益(板上贴片阵) | 约 7 dBi | TI E2E 论坛帖转述 IWR6843ISK 文档 | 论坛转述,最弱 |
| TX→RX 隔离 | 无 EBG 约 20–25 dB,加 EBG 约 40 dB | TU/e 2018,*High-isolation array antenna integration for single-chip millimeter-wave FMCW radar* 摘要 | 57–64 GHz,TX / RX 微带阵,键合线互连。摘要:"40 dB,比不加 EBG 好 15–20 dB";20–25 是减出来的 |
| TX→RX 隔离(指标) | > 25 dB | 60 GHz BiCMOS 单芯片 FMCW 雷达(1 发 2 收片上天线) | 设计指标,不是测量值 |
| TX→RX 隔离(单天线) | 22 dB,加阻抗调谐器 49 dB | IEEE J. Microwaves 2025-01,60 GHz 单站多普勒雷达,130 nm SiGe | 收发共用一副天线经环形耦合器 |

没查到任何数据手册直接给 TX→RX 隔离度。旁证:TI 对 IWR6843AOP 早期硅片的勘误 SWRZ092B——所有发射链满功率时两个接收通道的 NF 因天线耦合恶化约 2.7 dB。
BGT60TR13C 自己的 NF、转换增益、发射功率没读到(要开 V2.4.9 手册的电气特性表)。

与本库占位(60 GHz 档,`assumed`)对照:NF 10 对 12 dB;P1dB −20 对 −12 dBm(带外);RX 增益 40 对 30–48 dB;TX 10 对 12 dBm;
天线增益各 10 dBi 对 3.5(封装内)… 约 7 dBi(板上阵)——占位偏高;隔离 25 对 20–25 dB(无 EBG)。

链接:
- https://www.ti.com/lit/ds/symlink/iwr6843.pdf (SWRS219)
- https://ti.com/document-viewer/lit/html/SWRS237B/GUID-E54FF503-F97F-4440-A9AF-E01B8AD9B96A
- https://www.ti.com/document-viewer/lit/html/SWRZ092B/GUID-FA555C09-1174-421F-8DC8-290A052026BB
- https://www.ti.com/document-viewer/lit/html/TIDUEI1C/key-features-of-iwr6843-id-9e530925-2c41-4da4-8f22-63a23e733ada.html
- https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1277468/iwr6843-information-needed-to-calculate-link-budget-with-6843-evm-series
- https://www.infineon.com/dgdl/Infineon-BGT60TR13C-DataSheet-v02_49-EN.pdf?fileId=8ac78c8c7d718a49017d94bac88e5d4
- https://www.mouser.com/datasheet/2/196/Infineon_BGT60TR13C_Shield_ApplicationNotes_v02_04-2944375.pdf
- https://research.tue.nl/en/publications/high-isolation-array-antenna-integration-for-single-chip-millimet/
- https://research.tue.nl/nl/publications/on-chip-antenna-integration-for-millimeter-wave-single-chip-fmcw-/
- https://doaj.org/article/aa50ab7e6d4742af9b893c36eb54eb8a

---

## 追加(2026-11-12 当天稍后):三份原文已对照

用户上传了三份 PDF(不入库:TU/e 那篇是 IEEE 授权下载)。下面是对着原文核的结果;上面那张表里与之冲突的地方以这里为准。图上的数是目读的,TI 的图 ±1 dB,TU/e 的图 ±2 dB。

### 1. TI IWR6843 / IWR6443 数据手册,SWRS219F(2018-10,2025-04 修订),7.9 节 "RF Specification",第 32 页 —— 表里的数全部属实

"over recommended operating conditions (unless otherwise noted)";都在 TYP 列,除注明的。

| 参数 | 值 | 备注 |
|---|---|---|
| Noise figure(60 to 64 GHz) | 12 dB | |
| 1-dB compression point (Out Of Band) | −12 dBm | 脚注 (1) 原文:"measured by feed a Continuous wave Tone (10 kHz) well below the lowest HPF cut-off frequency" |
| Maximum gain / Gain range / Gain step size | 48 dB / 18 dB / 2 dB | 即 30–48 dB |
| IF bandwidth | 10 MHz | MAX 列 |
| ADC | 12 bit;25 Msps(real / complex 2x)、12.5 Msps(complex 1x) | MAX 列 |
| Output power / Power backoff range | 12 dBm / 26 dB | |
| Ramp rate | 250 MHz/µs | MAX 列 |
| Phase noise at 1-MHz offset(60 to 64 GHz) | −93 dBc/Hz | 上一轮没查到的一项 |
| IF 高通(脚注 (2)) | 两个独立可配的一阶高通:HPF1 175 / 235 / 350 / 700 kHz,HPF2 350 / 700 / 1400 / 2800 kHz | |

图 7-2 "Noise Figure, In-band P1dB vs Receiver Gain"(目读):

| RX 增益 [dB] | 30 | 34 | 36 | 40 | 44 | 48 |
|---|---|---|---|---|---|---|
| NF [dB] | 15.6 | 13.2 | 12.2 | 11.0 | 10.5 | 10.3 |
| 带内 P1dB [dBm] | −24 | −28 | −30 | −34 | −38 | −42 |

带内 P1dB 是一条直线,每 dB 增益降 1 dB。**上一轮搜索摘要给的"8 dB 增益时 −48 dBm、18 dB 时 −18 dBm"是把坐标轴刻度读成了数据,作废。**
这份手册里没有天线增益,也没有 TX→RX 隔离或耦合的任何数(全文搜过 isolat / coupl / dBi)。

### 2. Infineon AN600 "BGT60TR13C shield",Revision 2.40(2023-02-14),板 V2.2 —— 上一轮引的天线增益不在这份文档里

- **"天线增益 2.0 / 3.5 / 5.0 dBi"在这份应用笔记里不存在**(全文没有 dBi)。搜索摘要把别处的数安到了它头上;那组数现在没有出处,作废,等有人读到 BGT60TR13C 数据手册本身再说。
- 它有的:5.1 节只给**归一化**方向图(图 12、14,60.5 GHz),原文"The datasheet of the BGT60TR13C only shows the 3-dB values"。E 面主瓣不垂直于芯片表面,偏约 25°(封装内天线靠得近);
  接收功率随中心频率变(图 14c,往返):59.5 GHz 最强,63 GHz 处低 5–6 dB。
- 5.2 节的实测相噪(图 16,60 GHz,目读):10 kHz 约 −77 dBc/Hz,30 kHz–500 kHz 基本平在 −81 … −83,1 MHz 约 −85。原文说典型 IF 在 10 kHz–1 MHz。

### 3. Adela, van Beurden, van Zeijl, Smolders, "High-Isolation Array Antenna Integration for Single-Chip Millimeter-Wave FMCW Radar", IEEE Trans. Antennas Propag., vol. 66, no. 10, pp. 5214–, Oct. 2018, DOI 10.1109/TAP.2018.2854286 —— 摘要属实,"不加 EBG"那一半要改说法

- 摘要原文:"Measurement results in the 57–64 GHz band show the TX–RX isolation of 40 dB, which is 15–20 dB better than the isolation between TX and RX arrays without EBG structures."
- **整机上"不加 EBG"的隔离度没有实测**:原文"we did not have prototypes of the complete radar without EBG structures available",图 17 里不加 EBG 的那条是仿真。
  所以上一轮写的"无 EBG 约 20–25 dB"不是测量值减出来的。准确的说法:
  - 整机(TX / RX 各一个 8 元阵,间距 15 mm),图 17:加 EBG **实测** −40 … −50 dB(57–64 GHz);不加 EBG **仿真** −21 … −27 dB。
  - 天线级(8 元阵对单个贴片,图注 8 mm、正文 6.4 mm,接头直接测 S21),图 16:不加 EBG **实测** 57–64 GHz 约 −21 … −28 dB(55 GHz 处 −14);加 EBG 实测 −30 … −48 dB。
- 设计要求原文:"the isolation between the TX and RX channels should be as high as possible, at least 40 dB"。
- 天线:8 元孔径耦合贴片阵(板上,Rogers 4350B),12° 波束宽,**实测增益约 12 dBi(60 GHz)**,57 / 64 GHz 略低。

### 对本库占位的含义(更正上面"对照"那一段)

- **天线增益 10 dBi"偏高"的说法撤回。** 板上 8 元阵实测 12 dBi;封装内天线的数现在没有出处。10 dBi 落在"板上小阵"的量级,但那样的阵是 12° 的扇形波束。
- **TX→RX 隔离 25 dB** 落在不加隔离结构的板上阵的实测 / 仿真范围里(21–28 dB)。
- **接收压缩点其实是两个量。** 带外(高通之前,−12 dBm)管的是泄漏:泄漏的拍频在高通截止以下,正是 TI 脚注里那种信号;带内(−24 … −42 dBm,随增益)管的是目标回波。
  本库只有一个 `p1db_dbm`(−20 dBm),泄漏预算和 ADC / IF 饱和都用它。按 TI 的数,40 dB 增益下带内 −34 dBm、带外 −12 dBm。
- **NF 10 dB**:TI 在 40 dB 增益下图上读 11 dB,表里典型 12 dB。
- **LO 占位(L(100 kHz) / L(1 MHz) = −82.5 / −79.6 dBc/Hz)**:BGT60TR13C 实测约 −82 / −85,TI −93(1 MHz)。占位在 100 kHz 处与 BGT60TR13C 相当,1 MHz 处比两者都差。

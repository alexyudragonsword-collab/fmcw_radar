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

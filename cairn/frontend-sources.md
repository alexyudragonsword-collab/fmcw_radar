---
type: project_topic
status: active
summary: "60 GHz 前端的数从哪来:发射功率 / NF / 两个接收压缩点 / 收发隔离读 mmw60_trx 来源表里读过原文的条目(一颗雷达芯片的手册、一篇板上阵的文章),天线增益与增益档仍是占位;为什么只 vendor 来源表不 vendor Frontend60;压缩点为什么是两个量;换数之后哪些结论变了(泄漏强 7 dB,1 阶高通不够,带外裕量 −4 dB)。"
tags: [frontend, sources, mmw60_trx, compression, leakage, vendor]
contains: [decision, lesson, experience]
created: "2026-11-12"
updated: "2026-11-12"
related: [architecture-invariants, mimo-angle]
authoring_mode: ai_generated
---
# 前端数字的出处(0.2.8)

## 背景

0.2.7 及以前前端是 13 项 × 两个频段的占位(`source: assumed`),等 mmw60_trx 的前端。消费清单提在 mmw60_trx#14;它在 main@`ef0f00c` 落地了三个面
(接收前端、收发隔离、发 / 收天线增益)和两个压缩点字段。过程中两边各查了一轮公开数字,三份原文由用户上传后对照过(`cairn/Reference/2026-11-12-frontend-survey.md`)。

## 当前结论

- **读什么**(60 GHz 档;`data/sources.yaml` 里带 `upstream:` 的五条,`source: spec`,各带引文与章节):

  | 量 | 值 | mmw60_trx 的条目 | 原文 |
  |---|---|---|---|
  | `tx_power_dbm` | 12 dBm | `rx60.radar_iwr6843#tx_power_dbm` | TI IWR6843 手册 SWRS219F 7.9 节 |
  | `nf_db` | 12 dB | `rx60.radar_iwr6843#nf_db` | 同上(表里的典型值) |
  | `p1db_oob_dbm` | −12 dBm | `rx60.radar_iwr6843#p1db_in_oob_dbm` | 同上,脚注 (1) |
  | `p1db_inband_dbm` | −34 dBm(40 dB 增益) | `rx60.radar_iwr6843_fig7_2#p1db_inband_dbm@gain_db=40` | 同上,图 7-2(目读 ±1 dB) |
  | `tx_rx_isolation_db` | 20 dB | `isolation.tx_rx_tue2018#with_ebg_db-improvement_max_db` | Adela 等,IEEE TAP 66(10) 2018 |

- **不读什么**:天线增益(各 10 dBi)与 RX 增益档(40 dB)仍是 `assumed`。天线增益是设计选择:读到的是封装内 2 dBi(mmw60_trx 的通信收发机条目)与板上 8 元阵实测约 12 dBi(Adela 2018),
  差 10 dB,而 MIMO 阵元两者都不是;对 SNR 是 1 dB 对 1 dB,所以不拿一个不对口的数冒充出处。LO、TDC、互耦、77 GHz 一档的全部也仍是占位(23 条 `assumed`,5 条 `spec`,9 条 `survey`)。
- **决定(contains:decision):只 vendor 来源表,不 vendor `Frontend60`。** `vendor/mmw60/` 只有 `spec.py` 与 `data/spec/survey.yaml`。理由:(1) `Frontend60` 站在 wifitrx 整条收发链上;
  (2) 它的基准前端 `surveyed_frontend` 取的是通信收发机(Asada 2011:增益 27 dB、NF 6.1 dB、天线 2 dBi、带外压缩点 None),雷达最要紧的带外压缩点在那一档是空的,只有它表里的雷达芯片条目有。
  代价是没有"同一个 `Frontend60` 实例",只有同一份数和出处;已在 #14 说明。
- **决定:数写两遍、加载时核对。** `sources.yaml` 的条目自己带 `value`(这张表要能单独读、`grep source:` 要数得对),`upstream:` 指向 vendored 表的条目与字段
  (`#字段`、`#a-b` 两字段之差、`#字段@键=值` 曲线上的一点);`load_sources` 发现两边不等就拒绝加载。重新 pin 之后上游的数动了,测试之前加载就先失败。
- **压缩点是两个量(contains:lesson)。** 雷达芯片的手册把接收压缩点分成带外(用远低于最低高通截止的 10 kHz 连续波测:高通之前的那几级)和带内(随增益每 dB 降 1 dB:输出端的固定电平)。
  0.2.7 及以前只有一个 `p1db_dbm`(−20 dBm),泄漏预算和回波裕量共用。现在:回波对带内点(`cfg.p1db_inband()`,config 改增益时沿图 7-2 的直线折算);
  泄漏的每一项按拍频在高通截止的哪一侧选点(`link/leakage.py`,`p1db_kind`)。77 GHz 一档两个点都沿用原来的 −20 dBm(没有出处)。

## 换数之后变了什么(numbers-move)

- **SNR 几乎不动**:发射 +2 dB、NF +2 dB 抵消,只剩量化份额变小的 +0.04 dB(5 m 人体 51.30 → 51.34 dB;C/N0 76.76 → 76.80 dBHz)。P_r −87.1 → −85.1 dBm。
- **泄漏强了 7 dB**(发射 +2、隔离 −5):接收端 −15 → −8 dBm,阶跃 7.2 → 16.1 V,推荐 blanking 4.5 → 5.4 µs(2 阶 200 kHz;0.2.9 的式子下 5.5)。结论层面的变化:
  - 1 阶 200 kHz 高通不再够:高通后泄漏正好在 ADC 满幅,稳态削波 78 %(占位时 2.7 %)。
  - 2 阶 200 kHz:ADC 裕量 +35 → +28 dB,削波 3.5 → 4.1 %,blanking 后每 chirp 末尾剩 3 个削波样本(原 1 个;引擎循环砖墙的环回)。
  - 对压缩点:无高通 −26 dB(带内),有高通 **−4 dB**(带外)。占位时报的是单一的 −5 dB。按这组有出处的数,不加隔离结构的板上阵 + 这颗芯片的前级吃不下自己的泄漏;加文章里的 EBG(40 dB)是 +16 dB。
- 机制类测试(高通、blanking、窗重配)固定在原来的一对数上(10 dBm、25 dB,`tests/test_leakage.py::_hpf`),阈值保持原义;默认档的新结论由 `test_sourced_leakage_level_and_what_the_high_pass_must_do` 守着。

## 经验

- **坑(contains:搜索摘要里的出处归属不可信)**:第一轮只读搜索摘要时,"AN600 给了天线增益 2.0 / 3.5 / 5.0 dBi"是摘要把别处的数安到了那份文档头上;"带内 P1dB:8 dB 增益 −48 dBm"是坐标轴刻度。
  两条都是对着 PDF 才发现的,第一条还被 mmw60_trx 转引进了它的表(后来删了)。数和"哪份文档说的"都要对原文;没对之前不要拿它下结论(当时已经写了"占位偏高")。
- **坑(contains:"不加 EBG 的隔离度"没有整机实测)**:摘要说"40 dB,比不加好 15–20 dB",读起来像两个实测相减。正文:没有不加 EBG 的整机样机,那条曲线是仿真(21–27 dB);
  不加 EBG 的实测只有天线级(21–28 dB)。取 20 dB 与 mmw60_trx 一致,比读到的范围低 1 dB。
- 没做的在 ROADMAP:NF 不随增益变(图 7-2 上 40 dB 增益是 11.0 dB,用的是表值 12);时域引擎不建模压缩;天线增益等一个对口的出处;77 GHz 一档全是占位。

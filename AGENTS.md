# fmcw_radar 协作规则

> 本项目使用 Project Cairn:`AGENTS.md` 是规则与导航入口,`cairn/` 是项目知识/状态层。同目录 `CLAUDE.md` 只有一行 `@AGENTS.md`,使 Claude Code 读到同一份规则;Codex 直接读本文件。

## 项目一句话

60 GHz 宽带 FMCW 雷达的行为级仿真框架:chirp 发生(vendored polar_tx 两点 ADPLL 喂斜坡)、TX / RX 共用 LO 经往返延迟的相噪相关抵消(range correlation)、雷达方程、距离–多普勒处理、统计 / 时域双引擎。它是 mmw60_trx 的姊妹库而不是扩展 —— 通信库的指标是 EVM / ACLR / MCS,这里是距离 / 速度分辨率、相噪旁瓣、虚警 / 检测概率;核心机制与 d2d_link 的"前向时钟跟踪发端 PLL 相噪"是同一个式子。

## Init 配置

- 毕业 provider:暂缓对接(首次毕业时再接知识库)
- 知识库索引 / 毕业目标:尚未配置

## 进入项目后的阅读顺序

1. 先读本文件(AGENTS.md)。
2. 读根目录 `ROADMAP.md`:只记没做的,每条附证据(复现方式与数字)。
3. 读 `cairn/LOG.md` 最新几条(新条目在顶部):每轮的数字原值与被推翻的判断。
4. 按任务需要读 `cairn/` 下相关知识专题文档(`cairn/architecture-invariants.md`、`cairn/chirp-engine.md`、`cairn/range-correlation.md`、`cairn/mimo-angle.md`、`cairn/cfar-statistics.md`、`cairn/frontend-sources.md`)。

## 文档职责

| 文件 | 角色 | 维护方式 |
|---|---|---|
| `AGENTS.md`(根) | 规则与导航 | 很少变,≤ 65 行 |
| `CLAUDE.md`(根) | 单行 `@AGENTS.md` 存根 | 写一次,不再改动 |
| `ROADMAP.md`(根) | 待办与优先级 | 只写没做的;完成即删除并在 LOG 记一笔;发现的问题带复现方式和数字 |
| `CHANGELOG.md`(根) | 已交付的演进 | 按里程碑追加 |
| `CONTRIBUTING.md`(根) | 命令、vendor 规矩、提交约定 | 约定变了才改 |
| `cairn/LOG.md` | 时间序日志 | 新条目加在顶部,每条 ≤ 20 行:数字原值、被推翻的判断、下一步 |
| `cairn/<topic>.md` | 知识专题文档(当前真相) | 就地更新;坑放正文小节并用 `contains` 标注 |
| `cairn/Reference/` | 外部原始输入 | 按需创建,只追加 |

> 工程资产(配置、来源表、期望输出)留在代码树里;`cairn/` 只放关于它们的知识。面向使用者的 `README.md`、`docs/` 与面向协作者的 `cairn/` 读者不同,不要互相搬运。

## 项目铁律(每条都有测试守着;论证见 `cairn/architecture-invariants.md`)

1. **配置是唯一真值** —— 频段、扫频、chirp、LO、前端、阵列、目标全在一个 frozen `RadarConfig` 里,示例和报表只读它(`tests/test_config.py`、`tests/test_invariants.py::test_law1_*`)。
2. **range correlation 是核心机制** —— TX 和 RX 的相噪是同一条序列,差的只是往返延迟 τ;残余 PSD = 2(1 − cos 2πfτ)·S_φ(f)。禁止任何"把 RX LO 当独立时钟"的捷径。τ = 0 残余逐位为零;τ → ∞ 趋于 2 倍单边;中间与闭式差 < 0.1 dB(`tests/test_range_correlation.py`、`tests/test_invariants.py::test_law2_*`)。
3. **统计引擎是主引擎** —— 距离–多普勒图的 SNR、旁瓣、检测概率解析算;时域引擎(真波形 → 真混频 → 真 FFT)只做一致性检查,LTI + 高斯噪声下检测 SNR 两者差 < 1 dB(`tests/test_engines.py`)。
4. **chirp 非线性从环路来,不从假设来** —— 频率误差曲线由 vendored ADPLL 在斜坡下的真实响应给出(环路建立、两点增益失配、TDC / DCO 量化);解析二次项只当参照组(`tests/test_chirp.py`、`test_invariants.py::test_law4_*`)。
5. **目标是输入不是模型** —— 点目标(距离、速度、角度、RCS)由 config 给,RCS 典型值标出处;外部来源的数全在 `src/fmcw_radar/data/sources.yaml`,`grep source:` 一次列全(`tests/test_sources.py`)。
6. **杂散结论只能来自逐周期引擎** —— `lo.engine: response` 是线性化引擎,结果带 `vouches_for_spurs = False`,不能背书杂散(`test_invariants.py::test_law6_*`)。
7. **数值指纹** —— 重构必须用 `tools/fingerprint.py` 证明逐位不变(`tests/test_fingerprint.py`,CI 的 fingerprint 作业)。

vendor 规矩照 polar_tx:`src/fmcw_radar/vendor/` 是可校验的改编副本,`tools/vendor_check.py --strict` + `tools/vendor_manifest.json`,CI 跑。不改 polar_tx / array_tx / mmw60_trx:需要它们改的报回各自 ROADMAP,合并后重新 pin。

## 冲突仲裁

- 代码事实 > 一切文档:数字是承重的,文档和实测冲突时以跑出来的数字为准,然后修文档。
- 文档之间:**知识专题文档 > LOG 历史**;规则层面的冲突由本文件裁定。

## 文档协作规则

- 动手前先判断用户要的是"讨论/建议"还是"直接改文档";说"先看看/先评估"时先给分析。
- 修正过去的判断时追加更正说明,不要静默覆盖。未经确认的判断不要写成既定事实;原文没读到的数写"未核实"。

## 知识沉淀规则

- 每次实质性推进后,在 `cairn/LOG.md` 顶部加一条(摘要+指针);结论沉淀进 `cairn/` 专题文档。
- **完成回复闸门**:在任何完成类声明之前,先执行 Project Cairn `references/maintenance.md` 的检查点,只更新其触发矩阵要求的记录并核验,再回复。明确的只读要求禁止 Cairn 写入。
- 每个里程碑结束:CHANGELOG 一条、LOG 一条、ROADMAP 删掉做完的条目并加上过程中发现的问题。

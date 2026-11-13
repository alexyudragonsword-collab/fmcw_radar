# 贡献指南 / Contributing

本文件把这个工程**已经在测试里强制执行**的约定写下来(polar_tx / d2d_link 的做法)。
每条都对应至少一个会失败的测试或一个 CI job。

## 0. 环境

```bash
pip install -e ".[plot,test]"
pytest -q                                   # 全绿是提交的前置条件(addopts 已有 -q)
python examples/00_single_target_rd_map.py  # 图写到 examples/output/
python tools/budget_report.py configs/radar_60g_sensing.yaml   # 预算一页
python tools/vendor_check.py --strict       # vendor 漂移(需要 polar_tx 与 array_tx 的 checkout,见下)
python tools/fingerprint.py record before.json && ... && python tools/fingerprint.py compare before.json after.json
python tools/run_examples.py --smoke        # 每个示例冒烟(n_chirps 截到 8)
```

姊妹库的只读 checkout 默认在 `/home/user/<repo>` 或 `/home/user/alexyudragonsword-collab/<repo>`
(云会话的 add_repo 落点),也可以 `--siblings polar_tx=/path` 或 `FMCW_SIBLING_polar_tx=/path`。
没有 checkout 时 `tests/test_vendor_check.py` 跳过;CI 的 `vendor-drift` 作业按 pin 的完整 SHA 检出,跳过即红。

## 1. 测试写物理量,不写快照

一个测试要么断言一个可以独立推导的物理量(c/2B、R⁻⁴、2(1 − cos 2πfτ)、Harris 的窗表),要么断言两条独立
实现一致(统计 vs 时域、event vs response、闭式 vs 合成)。不要把当前输出硬编码成期望值 —— 那是
`tools/fingerprint.py` 的事(铁律 7),它逐位比,测试比物理。

## 2. vendored 代码是改编副本,不是 fork

`src/fmcw_radar/vendor/` 下的每个文件头是 `# Vendored from <repo>@<完整 SHA>: src/...`(polar_tx、array_tx、mmw60_trx、spec_sources 四个来源;
spec_sources 只取读取器 `reader.py` 与本库读的表 `data/frontend60.yaml`,mmw60_trx 只取 ×10 LO 剖面;YAML 也带同样的头、同样逐字节比),
polar_tx 自己嵌套的 `# Vendored from pll_simulator@...` 头保留在下面;`tools/vendor_check.py` 只剥外层头,
剩下的与上游文件逐字节比。array_tx 的 `coupling.py` 是改编副本(去掉了对它自己 config 的 import),按 `adapted` 规则校验。要改 vendored 文件先问能不能在 `fmcw_radar` 侧包一层(chirp 引擎就是这么做的:
直接驱动 `ADPLL.simulate`,校准器按 `dp_cal` 契约另写);真要改就更新 `tools/vendor_manifest.json` 并写 `reason`。
需要上游改的报回对方(开 issue),合并后重新 pin。`data/sources.yaml` 里带 `upstream:` 的条目在重新 pin 之后若与上游不等,加载即失败——那是要你去改数并写 numbers-move。
`upstream:` 写 `spec_sources:<条目>[#<字段>[@<轴>=<值>]]`,只查找;要差、比、单位换算就在 spec_sources 加一条 derived。新加一条 `upstream:` 要在 spec_sources 开 issue 登记(它的 `consumers.yaml`:它看不到本库的表)。

## 3. 来源标签

不是用户设计决定的数全在 `src/fmcw_radar/data/sources.yaml`:`assumed`(前端占位,等 mmw60_trx)、
`survey`(二手转述,note 必须写"未核实")、`spec`(对过原文,要 quote)。`grep -c "source:"` 数出来的要等于条目数。
代码不许把表里的数写成字面量(`tests/test_sources.py`、`tests/test_invariants.py`)。

## 4. 引擎有适用域,越界要出声

`lo.engine: response` 是线性化的,结果带 `vouches_for_spurs=False`;杂散、量化的结论只能来自 `event`。
polar_tx 的 event 有效域指标(每参考周期相位推进)在 chirp 上读 495 %,`ChirpResult.ui_per_ref_cycle_p99` 报出来,
为什么仍可用见 `cairn/chirp-engine.md`。指标函数输入不够时抛异常,不返回 NaN。

## 5. 提交

- `main` 是默认分支(2026-11-07 起),只收 CI 全绿的工作;工作在 `feat/*` 分支上开 PR 合进 `main`,合并由人决定。
  `ccr-dd350ddf-xv24an` 是里程碑 1–2 的历史分支,与 main 同提交,不再往它推。
  CI 的 fingerprint 作业拿与 `origin/main` 的 merge-base 当 base(没有 main 时退回 `HEAD^`)。
- 提交前:`pytest -q` 全绿、`ruff check src/ tests/ examples/ tools/` 干净;碰过示例就重跑并用
  `tools/run_examples.py --save new/` + `tools/example_drift.py compare new/` 看哪些数动了,文档改完 `accept`。
- 动了数字的提交在信息里写 `(numbers-move: 为什么)`,CI 的 fingerprint 作业认这个标记。
- 提交信息写**为什么**,不写改了哪些文件。
- 里程碑结束:CHANGELOG 一条、`cairn/LOG.md` 一条、ROADMAP 删做完的、加发现的问题(带复现方式和数字)。

## 6. 风格

`ruff check`(只查 pyflakes 与语法错误,规则在 `pyproject.toml`),vendor 树排除。模块级 docstring 说这个文件在信号链里的位置;
公开 dataclass 的字段行尾注明单位;向量化优先,逐周期 Python 循环只在 vendored event 引擎里。docstring 里的物理断言必须是量过的。

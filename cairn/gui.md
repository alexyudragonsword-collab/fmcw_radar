---
type: project_topic
status: active
summary: "图形界面的决定与分层:一份网页界面三个宿主(桌面应用窗口 / 浏览器 / Android WebView),描述 guispec / 计算 guiutil / 分发与队列 webhost、appbridge / 画 webui,页面只画不算;界面方案是'方案 A 的风格 + 方案 B 的九处 + 系统框图页'(合并稿)。P1 已做:guispec(88 个控件 = 配置字段,默认值读出不手填,留空字段背后的数走库自己的查找,条件 when 与读数处 seen)和'每个旋钮拨一格'的测试。拨旋钮摸出四件事:一个没人读的字段、response 引擎静默不做在线校准、IF 高通只在时域引擎里起作用、两个虚拟阵元配 Hann 角窗测角是垃圾值。"
tags: [gui, guispec, web, android, form, provenance]
contains: [decision, lesson, pitfall]
created: "2026-11-19"
updated: "2026-11-19"
related: [architecture-invariants, regulatory-compliance, mimo-angle, chirp-engine]
authoring_mode: ai_generated
---
# 图形界面

## 决定(contains:decision)

- **做法照 polar_tx / array_tx**(它们的 `cairn/gui-redesign.md`、`cairn/gui.md`):一份网页界面,桌面应用窗口、浏览器、Android WebView 三个宿主共用;
  分层是 描述(`guispec`)/ 计算(`guiutil`)/ 分发与队列(`webhost`、`appbridge`)/ 画(`webui`)。**页面只画不算**:标签、单位、范围、默认值、哪个控件此刻不起作用,
  都从 Python 来。
- **形态是实时工作台**:统计引擎快(线性化 chirp 引擎下一份报告 0.1 s,逐周期引擎 8 个 chirp 1.2 s、默认 64 个 3.4 s),拨旋钮、图跟着变;只有时域引擎是长任务
  (单通道 6.7 s,MIMO 约 30 s),要进度与取消。
- **界面方案**(2026-11-19 用户定):两份效果图由两个独立的设计按同一份简报、同一份真实数据各出一份;用户选了方案 A 的风格,并要求补入方案 B 可取之处、加一张详细的系统框图。
  合并稿(私有页面)https://claude.ai/artifact/NBod3d8drNbQPbWy6v15k8 ,要点:
  - 结论先行:六个磁贴(合规、格点 SNR 与 Pd、鬼目标每帧期望检出、距离 / 速度分辨率、最大距离),左侧参数栏;
  - 引擎行:统计(主)/ 时域(只做一致性检查)/ chirp 引擎,每个写明"结论适用到哪里"(`guispec.ENGINES`);
  - 距离-多普勒图上真目标与鬼目标分形状画,图下检出清单;链路预算满功率 / 合规回退两列、按段分组、每个输入和标签在用到它的那一行;合规卡带 EIRP 的算式;
  - 每个外部数字旁边有出处标签,界面上改过的数标 `assumed`、结果标"已过期";可复现卡(seed、配置哈希、vendored pin、等价命令行);
  - 系统框图页:chirp 发生器 / 射频链路与信道 / 数字处理三条泳道 24 个环节,各带参数、标签与这一级之后的量;电平图;三个引擎各算哪一段;
  - 手机宽度(≤ 760 px)底部导航,页面不横向滚动;中英双语;浅色 / 深色。
  没有采用:单独的"运行(统计)"按钮(工作台是实时的)。还没画:MIMO 测角界面(框图里只是一个虚线框)。
- **分阶段**,每阶段单独 PR:P0 效果图(已做)→ **P1 界面规格层 guispec + "每个旋钮都拨得动"(已做,0.2.21)** → P2 guiutil(报告 + 图数据 + 引擎行 + 可复现卡)与本地宿主、新工作台
  → P3 系统框图页、频段取舍页、基线 / 扫描 → P4 Android。

## P1:`guispec.py`(只描述,不算物理)

- **控件就是配置字段**:清单取自 `config/form.py` 的 `SECTIONS`(`tests/test_config.py` 早就让它与 schema 双向一致),88 个控件 + 1 个 `HIDDEN`。
  guispec 在上面加页面要的东西:中英文标签(`ZH` / 表单自己的英文标签去掉方括号单位与括号说明)、显示单位与换算(`scale`)、显示范围与步进(`RANGES`,只管显示,合法性仍由配置层判)、
  常用 34 个(`COMMON`,展开显示)、分组(`GROUPS` = 表单的 13 段)。
- **默认值读出来,不手填**:`Control.default` 是 `RadarConfig()` 的值;测试要求"表单全取默认"与"空表单"都构造出 `RadarConfig()`,五个随库配置经表单往返不变。
- **留空字段背后的数**(18 个:发射功率、回退、天线、NF、压缩点、TDC、氧气、RCS、隔离 …):`resolve(cfg, path)` 走库自己的查找(`frontend_value`、`lo_value`、`p1db_inband`、
  `oxygen_db_per_km`、`rcs_dbsm` …),所以它跟着频段、目标类型走,带内压缩点还跟着接收增益走(增益 44 dB 时是 −38 dBm,不是表里的 −34)。带回值、出处标签和来源表里的键。
  留空只表示"不设"的 6 个字段(`lo.profile`、`regulatory.scenario` …)没有数也没有标签。
- **标签规则(contains:decision)**:`tags(values)` 给页面显示的标签——字段留空或填的正是来源表的那个数 → 来源表的标签;填了别的数 → `assumed`(界面上改的是设计取舍,不是引文)。
  没有占位数的控件是设计决定,不带标签。库的报告对配置里显式给的值标 `config`,页面不显示这个词。`values_to_config(canonical=True)` 把"填了来源表原数"的字段写回留空:
  往字段里敲 12(占位就是 12)什么都不变,配置逐值相等,哈希也就不变。
- **`when`:控件在什么设置下才起作用**(27 个控件)。原子是 `{path, op, value}`,`op` ∈ `in` / `gt` / `set`,全部成立才算。`inert(values)` 返回此刻不起作用的控件和没满足的那几条,
  页面据此置灰并写原因。`CHOICE_WHEN` 管选项:`lo.dp_cal: online` 只在 `lo.engine: event` 下成立。
- **`seen`:拨了以后在哪读到**:`report`(统计引擎的报告,默认)、`frame`(时域引擎的帧:seed、包络过采样、合成的 chirp 数、IF 高通两项)、`run`(一次运行里有什么:`sim.engine`)。
- `band_switch(values, kind)`:换频段不能只改 `band.kind`(60 GHz 的扫频在 77 GHz 窗外,配置层直接拒绝),它把扫频移进新窗口(放得下就保持带宽,居中);留空字段随后自己解析成新频段的占位。
- `METRICS`(13 个页面要读的数:在报告里的路径、单位、位数、哪个方向算改善)、`ENGINES`(五条:统计、时域、三个 chirp 引擎各自"做什么 / 结论适用到哪里")、`spec()`(整份契约的 JSON,38 kB)。

## "每个旋钮拨一格"的测试(`tests/test_guispec.py`,contains:lesson)

polar_tx 的经验:一个摆在那里却不起作用的控件、一个被库静默丢掉的设置,**读任何输出都读不出来**,只能靠"声明 + 拨动"抓。本库的做法:

- 每个控件按自己的 `step` 从默认值(留空的从占位数)拨一格,在 `when` 声明的设置下,要求 `seen` 指的那个输出变了;并且拨完的那一格是合法配置(步进本身受检)。
- 反过来:`when` 不成立时(默认设置下)拨同一格,输出必须逐位不变——置灰的依据是量出来的,不是猜的。
- **拨动要按物理来**(测试里的 `ALSO`):阵列类控件在目标 20° 上拨(0° 时元方向图为 1、互耦对角度的偏置由对称性为 0);校准类控件要先给 5 % 的两点失配;
  阵列用 4 个接收(2 个虚拟阵元配 Hann 是退化的,见下)。测试的基准设置是线性化引擎 + 8 个 chirp(一份报告 0.1 s),需要逐周期引擎的控件由 `when` 带上。
- 只有一个选项的选择(`chirp.shape`)显示但不拨;`band.kind` 经 `band_switch` 拨。
- break-check(改坏再恢复,各自变红):控件丢掉条件(1 条红)、把没人读的字段放回控件(4 条)、给一个本来总起作用的控件安上假条件(1 条)、把高通说成在报告里读(3 条)、
  步进改成不是整数个 ADC 样本(1 条)。

## 拨旋钮摸出来的四件事(都记在 ROADMAP;contains:pitfall)

1. **`sim.pn_bins_per_decade` 没人读**:schema 里有、表单里有,任何引擎都不读;20 / 60 / 120 给出逐位相同的报告与时域帧。进了 `HIDDEN`,不给页面;测试守着它"仍然什么都不动"。
2. **`lo.engine: response` 下 `lo.dp_cal: online` 被静默忽略**:5 % 失配时 `dp_gain_used` 仍是 1.05、没有任何提示,chirp 的读数与 `none` 逐项相同(逐周期引擎下在线校准到 1.0026)。
   规格里用 `CHOICE_WHEN` 声明,页面可以不让选这一对;库本身该给一条提示(没做)。
3. **IF 高通单独开时,统计引擎不认**:没开泄漏时,`rx.hpf_corner_hz` / `rx.hpf_order` 怎么改统计报告都不动;时域引擎照样滤——截止 1 MHz、2 阶,在 1.33 MHz 拍频的目标上掉 1.08 dB、
   底噪掉 1.29 dB。统计预算只在泄漏预算里用高通(`hpf_atten_at_target`)。所以这两个控件的 `seen` 是 `frame`。默认(高通关)与"截止远低于拍频"时无影响。
4. **两个虚拟阵元 + 默认的 Hann 角窗 = 垃圾角度**:`mimo.n_rx` 从 1 拨到 2(或 2 TX × 1 RX),Hann(2) 两个权都是 0,20° 的目标统计引擎读 −69.6°、时域引擎读 −57 … −70°,
   旁瓣 0.0、期望散布 NaN,没有报错。rect / hamming 下正常(20.01° / 19.99°),3 个阵元起 Hann 也正常。界面上一格就能拨到。

另:`sim.time_osr` 是时域引擎的参数,但统计引擎的"期望格点 SNR"按时域引擎看得到的带宽积相噪,所以它也让报告动一点(1.25 → 1.5:`cfar.snr_look_db` 差 0.0014 dB)——设计如此,不是问题。

## 给 P2 留的

- 库里还没有:配置哈希函数(效果图里用的是规范化 JSON 的 sha256)、CFAR 过门限格的分类(目标主瓣 / 鬼目标 / 泄漏 / 目标多普勒行 / 其余,效果图里是数据脚本按位置贴的)、
  距离-多普勒图与 L(f) 曲线的"图数据"接口。这些归 `guiutil`。
- 报告里的 `config` 标签到页面上按 `guispec.tags` 显示;满功率 / 合规回退两列对照要跑两份报告(回退 0 与当前值)。
- 页面的"此刻不起作用"用 `inert(values)` 的结果,不要在 JS 里重写条件。

## 复现

```
pytest tests/test_guispec.py                       # 契约与"每个旋钮拨一格"
python -c "from fmcw_radar import guispec as g; print(len(g.controls()), list(g.HIDDEN), sorted(g.inert({})))"
python -c "import json; from fmcw_radar import guispec as g; print(json.dumps(g.spec(), ensure_ascii=False)[:400])"
```

---
type: project_topic
status: active
summary: "图形界面的决定与分层:一份网页界面三个宿主(桌面应用窗口 / 浏览器 / Android WebView),描述 guispec / 计算 guiutil / 分发与队列 webhost、appbridge / 画 webui,页面只画不算;界面方案是'方案 A 的风格 + 方案 B 的九处 + 系统框图页'(合并稿)。P1 已做(guispec,0.2.21);P2 已做(guiutil、webhost、工作台页与浏览器测试,0.2.23);P3 系统框图 / 频段取舍 / 基线扫描、P4 Android 没做。"
tags: [gui, guispec, web, android, form, provenance]
contains: [decision, lesson, pitfall]
created: "2026-11-19"
updated: "2026-11-20"
related: [architecture-invariants, regulatory-compliance, mimo-angle, chirp-engine]
authoring_mode: ai_generated
---
# 图形界面

## 决定(contains:decision)

- **做法照 polar_tx / array_tx**(它们的 `cairn/gui-redesign.md`、`cairn/gui.md`):一份网页界面,桌面应用窗口、浏览器、Android WebView 三个宿主共用;
  分层是 描述(`guispec`)/ 计算(`guiutil`)/ 分发与队列(`webhost`、`appbridge`)/ 画(`webui`)。**页面只画不算**:标签、单位、范围、默认值、哪个控件此刻不起作用,
  都从 Python 来。
- **形态是实时工作台**:统计引擎快(线性化 chirp 引擎下一份报告 0.1 s,逐周期引擎 8 个 chirp 1.2 s、默认 64 个 3.4 s;**更正(0.2.23)**:3.4 s 只是第一次与动环路参数时,其余 0.9 s,见 P2 实测),拨旋钮、图跟着变;只有时域引擎是长任务
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
- **分阶段**,每阶段单独 PR:P0 效果图(已做)→ **P1 界面规格层 guispec + "每个旋钮都拨得动"(已做,0.2.21)** → **P2 guiutil(报告 + 图数据 + 引擎行 + 可复现卡)与本地宿主、工作台页(已做,0.2.23)**
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
  页面据此置灰并写原因。`CHOICE_WHEN` 管选项,从两头声明同一对:`lo.dp_cal: online` 要 `lo.engine` 不是 response,`lo.engine: response` 要 `lo.dp_cal` 不是 online;
  `refused_choices(values)` 给出此刻该在菜单里置灰的选项。
- **配置层拒绝的,页面原样显示**:`values_to_config` 走读 YAML 的那条路,schema 不收的改动抛它自己的 `ValueError`,那句话就是页面放在控件旁边的提示
  (比如"2 个虚拟阵元配 Hann:换 rect / hamming,或至少 3 个虚拟阵元")。页面不重写合法性判断。
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

## 拨旋钮摸出来的四件事(contains:pitfall;第 2、4 件 0.2.22 修了,第 1、3 件在 ROADMAP)

1. **`sim.pn_bins_per_decade` 没人读**:schema 里有、表单里有,任何引擎都不读;20 / 60 / 120 给出逐位相同的报告与时域帧。进了 `HIDDEN`,不给页面;测试守着它"仍然什么都不动"。
2. **`lo.engine: response` 下 `lo.dp_cal: online` 被静默忽略**:5 % 失配时 `dp_gain_used` 仍是 1.05、没有任何提示,chirp 的读数与 `none` 逐项相同(逐周期引擎下在线校准到 1.0026)。
   **0.2.22 起配置层拒绝这一对**(报错里写:换 offline / none,或用 event 引擎);`ideal` 引擎没有误差曲线,配什么校准都无所谓,不拒绝。
3. **IF 高通单独开时,统计引擎不认**:没开泄漏时,`rx.hpf_corner_hz` / `rx.hpf_order` 怎么改统计报告都不动;时域引擎照样滤——截止 1 MHz、2 阶,在 1.33 MHz 拍频的目标上掉 1.08 dB、
   底噪掉 1.29 dB。统计预算只在泄漏预算里用高通(`hpf_atten_at_target`)。所以这两个控件的 `seen` 是 `frame`。默认(高通关)与"截止远低于拍频"时无影响。
4. **两个虚拟阵元 + 默认的 Hann 角窗 = 垃圾角度**:`mimo.n_rx` 从 1 拨到 2(或 2 TX × 1 RX),20° 的目标统计引擎读 −69.6°、时域引擎读 −57 … −70°,
   旁瓣 0.0、期望散布 NaN,没有报错。rect / hamming 下正常(20.01° / 19.99°),3 个阵元起 Hann 也正常。界面上一格就能拨到。
   **更正(0.2.22)**:0.2.21 写"Hann(2) 两个权都是 0",不对。`processing.windows` 用周期形式,hann(2) = [0, 1](blackman 同,首权 −1.4e-17):是**只剩一个阵元**,
   一个阵元的波束形成器没有方向,读出来的角度是任意的。Hann(3) = [0, 0.75, 0.75] 还剩两个,所以 3 个起正常。
   **0.2.22 起配置层拒绝**"首权为零的窗(`schema.ZERO_FIRST_WINDOWS` = hann、blackman)+ 恰好 2 个虚拟阵元",报错里写两条出路。
   多普勒维同源的情形(每个发射通道 2 个 chirp)量了,没有拒绝:SNR 是老实的,只是速度读数无意义(ROADMAP P1 #8)。

另:`sim.time_osr` 是时域引擎的参数,但统计引擎的"期望格点 SNR"按时域引擎看得到的带宽积相噪,所以它也让报告动一点(1.25 → 1.5:`cfar.snr_look_db` 差 0.0014 dB)——设计如此,不是问题。

## P2:`guiutil` / `webhost` / 工作台页(0.2.23)

- **`guiutil.py` 只编排库自己的入口,不新算物理**。`run_report(values)` 里的 `report` 就是 `report.build(cfg)`(测试逐值比);满功率一列是同一份配置把回退设成 0
  再走 `link_budget` / `leakage_budget` / `with_compression` / `compliance_check`(测试要求它等于 `run_statistical(回退 0).budget`);图数据(L(f) 与分项、目标处残余、
  鬼目标、电平、帧时序)都取自库已经算出的对象。一次运行还带 `tags` / `inert` / `refused` / `resolved`(guispec 的)、13 个 `metrics`、引擎行、可复现卡。
  P1 说库里缺的三样在这里:`config_hash`(规范化 JSON 的 sha256;填来源表原数与留空哈希相同)、`classify_cells`(过门限格按位置贴标签,顺序:泄漏 → 目标主瓣 →
  别的目标主瓣 → 鬼目标 → 目标多普勒行 → 其余)、`run_frame`(时域引擎一帧,图按块取最大池化到 ≤ 64×150)。
- **`webhost.py`:`Api.call(route, req) -> (code, payload)` 是接口,HTTP 只是传输**(标准库 `http.server`,只听 127.0.0.1,只发 `webui/www/` 里的文件)。
  配置层拒绝的是一个回答(200,`ok: false` + schema 的原话 + 字段),不是错误状态。时域帧是任务:`JobQueue` 进程后端(桌面;取消 = 立标志,队列线程 0.1 s 内 terminate,只有它碰进程对象)/ 线程后端
  (没有多进程的宿主,跑完丢结果);新任务顶掉在跑的;上一帧的耗时作下一帧的 `eta_s`,第一次没有估计就写"没有耗时可估"。P4 的 Android 桥调同一个 `Api`。
- **页面 `webui/www/`(index.html 0.7 kB、app.js 56 kB、style.css 28 kB)是手写源文件,没有构建步骤、不引任何外部资源**(测试扫三份文件里没有 URL)。
  它只画:控件清单、标签、单位、置灰原因、被拒选项、每个数都来自 `/api/spec` 与 `/api/run`。改一个数 250 ms 后重算,同时只有一个请求在途(在途时再改,回来后补发最新的)。
  配置层拒绝时:原话放在页顶、字段标红、上一次合法结果留在屏上、时域按钮禁用。跑过的帧记着自己的配置哈希,参数一变图变淡并写"上一组参数"。
- **实测耗时**(本机,决定"实时"到什么程度):线性化引擎一份报告 0.2 s;逐周期引擎(默认)第一次 3.2 s,之后只改环路以外的旋钮 0.84–0.92 s(chirp 结果有缓存),
  改环路参数又是 3.3 s;时域一帧 6.5 s(64 chirp),回传 63 kB;一次运行的 JSON 31–36 kB。
- **浏览器测试 `tests/test_webui.py`(7 条,Playwright + Chromium,对着真的本地宿主)**:页面上的数等于 `guiutil` 给的;拨一个数结果跟着变、改过的数标 assumed、
  敲回原数标签复原;拒绝的原话到控件旁、旧结果保留;置灰集合等于 `guispec.inert`;时域任务跑完出图、换参数后标"上一组参数";取消;390 px 底部导航不横向滚动、中英、深浅。
  没装驱动时跳过;CI 的 `test-gui` 作业装驱动并设 `FMCW_REQUIRE_BROWSER=1`,跳过即红。

### P2 的坑(contains:pitfall)

- **取消的测试改了三遍才对**(更正:这一条的第一版写"去掉 `terminate()` 测试照过,因为 6.5 s 的帧自己跑完、落在 < 10 s 里",机制说错了):
  (a) 当时去掉的是 `cancel()` 里那一处,队列线程的循环里还有一处(0.1 s 内看到标志就终止),行为没坏,测试过是对的,我把它读成了测试的漏洞;
  (b) 随后补的断言从测试线程去 `join` / `is_alive` 同一个 `multiprocessing.Process`——它不是线程安全的,两个线程各自 `waitpid`,输的一方看到"还活着":
  正确的代码本机 3 次红 1 次,CI 上 3.11–3.13 红(另一个竞态:状态先变 running、进程后登记,`KeyError`)。它"抓到破坏"是碰巧。
  (c) 现在只有队列线程碰进程对象(`cancel()` 只立标志;terminate 后 5 s 还活着就 kill),测试看任务与进程号:取消到结束 < 3 s、进程号已不存在。
  真把循环里的终止去掉:原来的"< 10 s"照过(队列等 5 s 后放弃并标 cancelled,进程还在跑),新断言红;正确代码连跑 8 次全过。
- `guiutil` 把标签写死成默认的,guiutil 的测试照过(基准设置里没改带出处的数)——现在测 12 → 10 dBm 标 assumed、敲回 12 复原。
- 带 `display` 的类会盖掉 `hidden` 属性:"计算中"的提示一直亮着。每个这样的类配一条 `[hidden]{display:none}`。
- 完整版 Chromium 会去要 `/favicon.ico`,404 进控制台,"控制台无错误"的断言就红;页面声明一个空图标(`href="data:,"`)。
- 8 个 chirp 的多普勒格太粗(±12.5 m/s 只有 8 行):泄漏、目标多普勒行会吃掉本该是"其余"的格;分类规则的测试用 64 chirp。
- `tomllib` 是 3.11 才有的,CI 有 3.10;测试读 `pyproject.toml` 用字符串包含。

## 给 P3 留的

- 没做:系统框图页、频段取舍页、基线 / 扫描、MIMO 测角界面;`target.extra_targets`(表)在页面上只读;页面不能载入 / 导出 YAML。
- 距离-多普勒图上:多目标时主瓣框是一个包住所有目标的框;泄漏格没有单独的画法(并在"其余"的记号里)。
- 关掉应用窗口不会停本地服务(Ctrl+C 停)。polar_tx 有"窗口关了就退"的心跳,这里没搬。
- 默认是逐周期引擎:拨环路参数一次 3.3 s,不算"实时"。页面如实写耗时,没有替用户换引擎。

## 复现

```
pytest tests/test_guispec.py                       # 契约与"每个旋钮拨一格"
pytest tests/test_guiutil.py tests/test_webhost.py  # 一次运行 = 库自己的入口;Api、任务、取消
pip install -e ".[gui-test]" && python -m playwright install chromium && pytest tests/test_webui.py   # 页面在真浏览器里
fmcw-gui            # 应用窗口;--tab 浏览器标签页;--no-open 只起服务(默认 127.0.0.1:8766)
python -c "from fmcw_radar import guispec as g; print(len(g.controls()), list(g.HIDDEN), sorted(g.inert({})))"
python -c "import json; from fmcw_radar import guispec as g; print(json.dumps(g.spec(), ensure_ascii=False)[:400])"
```

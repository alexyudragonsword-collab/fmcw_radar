# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.2.32] — 2026-11-21 — 界面:多目标表格可编辑,频段表和扫描先出预览(数字不动)

- **多目标表格可以在页面上改了**(原来只能从 YAML 载入):"更多目标"一组里加 / 删行,每行五个字段照主目标同名字段的规格画;RCS 留空显示该类型在来源表里的数和出处标签,
  填了别的数标 `assumed`。规格层给列的规格与新行的初值(`guispec.table_columns`),每次运行带回每行的出处(`table_rows`)。
- **被配置层拒绝的行,标的是那一行**:配置层对一行的报错句子和主目标的逐字相同("target.range_m must be …"),原来会标到主目标的字段上。现在拒绝里带 `row` / `column`,
  页面只标那一行那一格,原话在行内。
- **频段表和扫描分两遍**:先带 `preview` 提交(每一步由线性化 chirp 引擎顶替),结果标着是顶替的就自动再算逐周期那一遍。默认配置:频段表 1.8 s 出预览、14.8 s 换上;
  9 点扫描 2.9 s / 11.3 s。预览条写明哪三个数还不是最终值、屏幕上的在不在其中;频段表在第二遍期间留在屏幕上,第二遍可取消、可再要。手机上第二遍要点按钮。
  配置不在逐周期引擎上时只有一遍。
- 测试 +6(全套 457 条,原 451);break-check 九处。指纹逐位不变。Android 的版本号跟着库走。
- 留下的(ROADMAP P3 #1):新行与默认主目标同格;行内字段没有"此刻不起作用"的提示;逐周期那一遍仍是整遍重算。

---

## [0.2.31] — 2026-11-21 — 图上的电平、所在处的噪底(每 look SNR 与鬼目标检出数会动)

- **dBc 是滤波前的,图上的要再过一次 IF 高通**:鬼目标和相噪底表多给一个"图上"的值——线和目标各自在自己的拍频处过滤波器,比目标远的抬高、近的压低
  (`hpf_map_shift_db`;1 MHz 2 阶、目标 5 m:+10 m 处 +1.17 dB,−2.8 m −8.6,0.32 m −41.8)。它脚下的热噪声跟着走,ADC 量化噪声不走(`hpf_noise_shift_db`)。
  没有滤波器时两个值相同。全图平均相噪底也逐格过滤波器(开高通时时域对统计的全图口径 SNR 之差:2 MHz 2 阶 −3.2 → +1.7 dB,与不开时的 +1.9 一样了)。
- **目标的每 look SNR 读它自己邻域的相噪底**(`pn_floor_local_cell`,与时域引擎读本地噪底的那些格一致)。range correlation 把靠近拍频的 LO 噪声抵消了,目标旁边比全图平均低 15 dB;
  原来加的是全图平均。热噪声主导时看不出来(默认配置 +0.03 dB),LO 噪声主导时差很多:角反射器满功率,统计 61.9 → 74.4 dB,时域读 75.1。
- **鬼目标的 SNR = 图上电平 − 它所在处的噪底**(`cfar["ghosts"]` 每行新增 `level_map_dbc`、`floor_dbc`、`noise_shift_db`、`pn_floor_dbc`):所在处的底是目标自己的底挪到鬼目标的拍频,
  加上目标的相噪边带在那个偏移处的电平。两引擎对照(角反射器、四个视野内鬼目标):图上电平差 ≤ 0.4 dB;2 MHz 2 阶高通下 0.32 m 那个两引擎都检不出了(每帧 4.00 → 3.00 个)。
- **更正**:0.2.25 写的"鬼目标检出数按本地 SNR 算,一阶上不受高通影响"只对比截止远的鬼目标成立,近处的会掉进量化噪声。
- **`cairn/mimo-angle.md` §4 线性接收机的时域数重跑了**(0.2.25 起标着"未核实"):削波百分比、削波段长度、blank 后剩的样本都没变,底差 0.2–0.7 dB,结论不变。
- 报表:相噪底表开高通时多一列,鬼目标表多"图上电平 / 所在处噪底"两列。界面:相噪页的表和检出清单同样。
- **哪些数动了**:指纹 2476 个值里 26 个,全是 `cfar.snr_look_db` 与 `cfar.ghost_detections_per_frame`:热噪声主导的用例 +0.02–0.05 dB,77 GHz +0.24,7 GHz 扫频 +0.16,
  远目标(LO 主导)+4.8 dB;鬼目标检出数相对变化 ≤ 1.4 %。示例输出不动。
- **过程中发现、没有改**:LO 噪声主导的场景里两引擎的相噪底差 1–2.7 dB,方向取决于谁带 LO 噪声(ROADMAP P2 #6)。
- 测试 +12(全套 451 条,原 439);break-check 七处各自变红。

---

## [0.2.30] — 2026-11-21 — 互耦下两个引擎的每阵元 SNR 对上了(开了互耦的 MIMO 配置数字会动)

- **统计引擎**:互耦改变每个阵元上的回波功率,随来波方向变(邻元 −16 dB 反相:0° −3.26 dB、20° −0.51、40° +1.25 dB;`VirtualArray.coupling_power`)。
  图上一个 look 的 SNR(新的 `angle.snr_look_db`、`angle.coupling_power_db`)带上它,图上 CA-CFAR 的检测概率用它。原来只算了互耦对角度读数的偏置。
- **时域引擎**:接收机的噪声改在互耦之后加。原来噪声和回波一起乘了互耦矩阵;每个接收通道的噪声是自己的,天线间的耦合不该搅它。
- 两引擎每 look SNR 之差(ROADMAP P1 #8,0.2.27 量出来的):0° −3.61 → −0.09 dB,10° −2.61 → −0.16,20° −0.88 → −0.15,40° +0.87 → −0.14;与不开互耦时一样。
- **连带露出来的**:用逆矩阵校准互耦要付噪声的账。示例 07 的 32 个 seed:校准后角度 RMS 0.109° → 0.131°(期望散布 0.103° 里没有这一项,记在 ROADMAP P1 #8)。
- **哪些数动了**:不开互耦的配置逐位不变。指纹里三个开互耦的 MIMO 用例:统计侧 `cfar.snr_look_db` −0.51 dB(20° 的两个)/ +1.05 dB(−35° 的一个);
  时域侧 SNR +0.2 dB、峰旁瓣 ±0.7 dB 内、检出格数 ±1–2;新增两个键。示例 07 两行。
- 界面的测角卡多一行"图上一个 look 的 SNR"和互耦的功率因子。测试 +5(全套 439 条,原 434);break-check 三处各自变红。Android 的版本号跟着库走。

---

## [0.2.29] — 2026-11-21 — Android:WebView 外壳、桥接、APK 工作流(设备上未核实)

- **`android/`**:Chaquopy 工程(Python 3.10、插件 15.0.1、AGP 8.1.4,polar_tx / array_tx 同一组)。Activity 不含逻辑:WebView 载入同一份页面,一个异步桥接进
  `fmcw_radar.appbridge`(线程后端的 `webhost.Api`)。清单无权限。*Android APK* 工作流按需、以及 `android/` 有改动的 PR 时构建,产物约 72 MB。
- **页面在手机上不同的三处**:逐周期全量结果点了才算;配置文件是可复制 / 可粘贴的文本;顶栏给状态栏留位置。
- **手机上跑的是 numpy 1.26.2、scipy 1.8.1**——低于库声明的 `scipy>=1.11`,Chaquopy 的 pip 不拦,构建照样成功。这个下限是真的(1.10.1 上 `ncx2.sf` 中止进程);
  1.8.1 不中止,但参数到 1e9 量级时 `ncx2.sf` 返回 −1.66e-06:MIMO 配置"Pd 0.9 所需 SNR"成了无穷大。`processing.detection.ncx2_sf` 在 scipy 给出的不是概率时换成正态极限
  (正常的 scipy 上不触发,桌面的数逐位不变)。
- **CI 新作业 `test-android-versions`**:在手机那组版本上跑全套;APK 工作流核对装进去的就是那一对。
- 测试 +10(全套 434 条,原 424):桥接、Android 工程的静态检查、仿真桥接下的页面、`ncx2_sf` 的保护。指纹逐位不变。
- **没有在真机或模拟器上跑过**(`docs/android.md` 写明了证明了什么、没证明什么)。

---

## [0.2.28] — 2026-11-21 — 界面:测角卡(MIMO 配置下出现;数字不动)

- 工作台多一张"测角"卡,只在虚拟阵元 ≥ 2 时出现:阵列几何(发射 / 接收 / 虚拟阵元位置);主目标的角谱(统计引擎按配置的互耦、同一阵列无互耦、时域引擎这一帧);
  读数表(读出角度、互耦偏置、TDM 多普勒补偿的偏置、波束宽、峰旁瓣、CRLB σ、估计器的期望 σ 与四个因子、TDM 不模糊速度);时域引擎在每个目标自己的格上读出的角度。
- 数都是库自己的:`VirtualArray` 的位置与 `estimate` 的谱(`guiutil` 的 `plots.angle`)、报告的 `angle` 一节;时域引擎多存了每个找到的目标的角谱(只是多存)。
- 合并稿里没有这一页的效果图;沿用已定的卡片与图表样式做的。
- 测试 +2(全套 424 条,原 422);break-check 三处各自变红。指纹逐位不变。

---

## [0.2.27] — 2026-11-21 — 时域引擎读目标自己的 SNR(指纹多一个键,原有的值不动)

- **`TimeResult.snr_cell_local_db`**:目标被找到的那一格比它自己距离邻域的噪底(`processing.rd.local_noise_floor`)。原有的 `snr_cell_db`(图上的峰 / 全带平均噪底)不变,
  但它在两种情形下不是目标的 SNR:噪底有斜率(IF 高通),以及图上的峰不是目标(开了泄漏时是泄漏)。MIMO 图上读出的是单个 look 的 SNR。
- 对统计侧(线性化引擎、32 chirp):无滤波 +0.09 dB;高通 2 MHz 2 阶 −0.27 dB(全带口径在这里比本地低 4.7 dB);泄漏 + 200 kHz 2 阶 −0.15 dB(同一帧里"峰"的读数是泄漏的 61.8 dB)。
- 界面:引擎行和"时域 vs 统计"卡比的是目标自己的 SNR;图上的峰不是目标时写明,不再拿泄漏峰的读数去和目标的期望值比(以前 MIMO 配置在这里显示一个没有意义的差)。
- **新发现(没修,ROADMAP P1 #8)**:开了互耦的阵列上,两个引擎的每阵元 SNR 随目标角度相差 −3.6 dB(0°)到 +0.9 dB(40°);关掉互耦 0.2 dB 内。统计引擎没算接收互耦对阵元上回波功率的影响。
- 测试 +8(全套 422 条,原 414);break-check 三处各自变红。指纹:多 `time / snr_cell_local_db` 一个键,原有的值逐位不变。ROADMAP P2 #6 删掉做完的一条。

---

## [0.2.26] — 2026-11-20 — 界面:逐周期引擎先出预览;配置文件载入 / 导出(数字不动)

- **预览先出**:默认配置用逐周期 chirp 引擎,以前拨一次环路参数要等全量结果(0.2.23 量的 3.3 s)屏上才有东西。现在页面先拿到同一组参数在线性化引擎上的统计报告,
  标明"预览",逐周期结果算完自动换上。真浏览器里量:改数后 0.8–0.9 s 有数(含 250 ms 防抖)。
- **预览里哪些数还不是最终值写在屏上**:鬼目标每帧期望检出、目标处相噪残余、chirp 频率误差 RMS(`guispec.METRICS` 的 `chirp_engine` 标记),以及鬼目标清单与误差曲线。
  其余十个结论数两个引擎逐值相同(五份随库配置上有测试)。预览不改表单:表单里的引擎、配置哈希、可复现卡都是真配置的。线性化引擎顶替不了时(在线校准)不出预览。
- **全量结果在常驻的工作进程里算**(`webhost.ReportWorker`):预览不排在它后面;等着的全量请求只留最新的;chirp 引擎的缓存留在那个进程里。
  页面只在序号最新、哈希与屏上一致时才换上全量结果。
- **配置文件**:参数栏顶上"载入 YAML""导出 YAML"和随库配置菜单。导出的就是 `dump_config` 写的内容(`load_config` 读回同一份配置),首行注释带库版本与配置哈希;
  载入走 `config_from_dict`,schema 不收的原话显示在按钮下面,表单不动。
- 测试 +16(全套 414 条,原 398):预览 = 线性化引擎对真配置的运行、非 chirp 引擎的数已是最终值(五份配置);导出再载入得到同一份配置;工作进程"只做最新的";
  浏览器里预览 → 全量的替换、进程后端下旧参数的全量结果不上屏、文件下载再载入。break-check 十处各自变红。
- 没有改任何物理:指纹逐位不变。没做的记在 ROADMAP P3 #1(频段表与扫描没有预览;预览与全量争 CPU;`configs/` 不在安装包里;Android 的导出出口)。

---

## [0.2.25] — 2026-11-20 — IF 高通进了统计引擎,两个引擎用的是同一个滤波器(开了高通的配置数字会动)

- **统计引擎认高通了**(ROADMAP P1 #7,0.2.21 拨旋钮时发现的):`link_budget` 在目标拍频处把高通的衰减(`LinkBudget.hpf_db`,预算表多一行)从回波和热噪声上各扣一次,
  ADC 量化噪声在滤波器之后,不扣。本地 SNR 只损失量化噪声相对热底抬高的那一点(衰减 7.8 dB 时 0.33 dB,14.2 dB 时 1.45 dB);每个目标按自己的拍频扣。
  泄漏预算里原来单独扣的那一次去掉(否则扣两次)。
- **时域引擎的滤波器换成模型说的那个**(修的时候发现的):它原来是在 ADC 采样率上设计的数字 Butterworth,不是闭式描述的模拟滤波器——截止 3 MHz 时 1.33 MHz 处多衰 5.4 dB。
  现在在波形采样率上滤(抽取之前),峰值衰减与闭式差 ≤ 0.04 dB。
- **两种 SNR**:高通让噪底有斜率,全带平均的噪底不等于目标处的噪底。统计侧给两个:`snr_cell_expected_db`(时域引擎的全带平均口径,用于两引擎对照)与
  `snr_cell_local_db`(目标处,检测概率用它)。没有滤波器时是同一个数。
- 两引擎的 SNR 对照(时域 − 统计期望;线性化引擎、16 chirp、无泄漏):1 MHz 2 阶 −0.30 → +0.07 dB;1.5 MHz 2 阶 −3.15 → −0.04;2 MHz 2 阶 −7.2 → −0.03;3 MHz 2 阶 −15.5 → −0.16。
- **哪些数动了**:没开高通的配置逐位不变(指纹里除三个开了高通的用例外全部相同)。开了高通的三个用例(MIMO 配置、两个合成用例,截止都是 200 kHz):
  统计侧回波与热噪声各 −0.0022 dB;时域侧 SNR +0.01 … +0.03 dB、检出格数各少 1、峰旁瓣 ≤ 0.03 dB。示例 08 的时域表:2 阶 200 kHz 削波 3.3 → 3.2 %,
  blank 后的无噪声底 −43.3 → −45.3 dB(参照 −48.6 → −48.1)。
- 界面:高通两个控件拨了在报告里就能读到(`seen` 从 frame 回到 report);预算卡多一行中文。
- 测试 +19(`tests/test_hpf.py`;全套 398 条,原 379):截止处任意阶 3.01 dB;衰减同扣回波与热噪声;近处目标扣得多;六组截止 / 阶数下两引擎的峰、底、SNR 一致;
  泄漏开时只扣一次。break-check 六处各自变红。一条既有断言放宽并写明数(blanking 改善量 8.0 → 7.5 dB)。
- 没做的记在 ROADMAP P2 #6:dBc 类读数仍是滤波前的相对电平;时域引擎没有本地口径的 SNR;飞回瞬态的底对滤波顺序敏感;`cairn/mimo-angle.md` §4 的线性接收机时域数没有重跑。

---

## [0.2.24] — 2026-11-20 — 图形界面 P3:系统框图页、频段取舍页、扫描页、基线对比(数字不动)

- **系统框图页**:从 chirp 发生到检测结果的 25 个环节、四条泳道,每一级写着当前参数下的数、出处标签和这一级之后的量;同一条 LO 去发射和混频画成一条蓝线;
  没启用的可选环节(泄漏、IF 高通、测角;规则不适用时的合规)画虚线框;下面是电平图(当前 / 满功率)、三个引擎各算哪一段、逐级参数表。
  环节在 `guispec.STAGES` 里声明(控件 / 从运行读的数 / 说明),`guiutil.system()` 填数,页面只管位置和连线。
- **频段取舍页**:当前扫频加示例 09 的四个候选,**每一行是一份真的配置**(扫频移进去、场景声明、回退到刚好压在治理档上限、帧周期够关断时间),
  行里的数是那份配置自己的统计引擎报告;"用这一档"把表单改成那一行。另有九档限值图、上限下的天线增益表、随库配置的现状。规则不适用的频段写原因。
- **扫描页**:一个数值控件从一头拨到另一头(2–41 点),看一个结论数;每点一份完整报告,配置层不收的值是带原话的 ×,IF 带外的点空心;"用这个值"写回表单。
- **基线**:工作台上钉住当前一组参数,之后每次改动列出变了哪些控件、13 个结论数各朝哪边动了多少。
- **宿主**:任务三种(时域帧 / 扫描 / 频段表),后两种报进度,线程后端的取消落在两步之间;`run` 路由可带基线。页面顶部四个页签,`pages.js` 新增。
- **测试 +15**(全套 379 条,原 364):`test_guispec` +1、`test_guiutil` +8(其中框图一条按五份随库配置各跑一遍)、`test_webhost` +2、`test_webui` +4(并把手机宽度那条扩到四页)。频段行按示例 09 的算法
  (EIRP 封顶的预算)独立核对;距离扫描核对 R⁻⁴ 加氧气;上限高 6 dB 的档 SNR 高 6 dB。break-check 八处各自变红。
  框图文字的宽度随机器字体变(CI 第一轮因此红):画完后量每行、宽了压进框,测试另换等宽字体量一遍。
- 实测:线性化引擎下频段表 1.2 s、9 点扫描 2 s;默认逐周期引擎下 18.4 s / 9.3 s(扫环路带宽 35.4 s)。
- 没有改任何物理:指纹 2451 个值逐位不变,十个示例照跑。没做的记在 ROADMAP P3 #1(Android、MIMO 测角界面、表格编辑、YAML 载入导出)。

---

## [0.2.23] — 2026-11-20 — 图形界面 P2:`guiutil`、本地宿主 `webhost`、实时工作台页(`fmcw-gui`;数字不动)

- **`guiutil.py`**:页面的一次运行,只编排库自己的入口。`run_report(values)` = `report.build` 的报告(逐值相同)+ 满功率一列(回退 0 的预算,等于 `run_statistical` 的)
  + 图数据(L(f) 与分项、目标处残余、鬼目标、电平、帧时序)+ 标签 / 置灰 / 被拒选项(guispec 的)+ 13 个指标 + 引擎行 + 可复现卡(seed、配置哈希、vendored pin、等价调用)。
  `config_hash`、`classify_cells`(CFAR 过门限格的分类)、`run_frame`(时域引擎一帧,图池化到 ≤ 64×150)、`validate`(拒绝时带 schema 的原话与它点名的字段)。
- **`webhost.py`**:`Api.call(route, req)` 是接口,标准库 HTTP 只是传输(127.0.0.1,只发页面目录里的文件)。时域帧是任务:进程后端取消即终止、线程后端跑完丢结果;
  新任务顶掉在跑的;上一帧耗时作下一帧的估计。入口 `fmcw-gui`(应用窗口 / `--tab` / `--no-open`,默认端口 8766)。
- **工作台页 `webui/www/`**(三份手写文件,无构建、无外部资源、图是内联 SVG):左侧 88 个控件按 13 段(常用展开),标签、单位、置灰原因、被拒选项都来自规格;
  六个结论磁贴;引擎行(各自"结论适用到哪里");距离-多普勒图(真目标 / 鬼目标 / 其余分形状)与检出清单;链路预算满功率 / 当前两列;合规卡(EIRP 算式、帧时序、九档限值);
  鬼目标与 L(f);时域 vs 统计;可复现卡。改数 250 ms 后重算;改过的数标 `assumed`;配置层拒绝时原话在页顶、字段标红、旧结果保留;时域任务有进度与取消;
  中英、深浅色;≤ 760 px 底部导航,不横向滚动。
- **测试 22 条**:`test_guiutil.py` 9、`test_webhost.py` 6、`test_webui.py` 7(真 Chromium 对真宿主;没装驱动时跳过,CI 新作业 `test-gui` 里跳过即红)。新增可选依赖 `gui-test`。
  break-check:标签写死、取消不终止进程、被拒选项不置灰,各自变红。取消那一条改了三遍:第一次破坏没破坏到(终止有两处,只去了一处),补的断言又跨线程读进程对象、
  在 CI 上偶发红;现在只有队列线程碰进程,测试看"取消到结束 < 3 s、进程号已不存在"(经过见 `cairn/gui.md` P2 的坑)。
- 实测:线性化引擎一份报告 0.2 s;逐周期引擎第一次 3.2 s、不动环路 0.84–0.92 s、动环路 3.3 s;时域一帧 6.5 s。
- 没有改任何物理:指纹 2451 个值逐位不变,十个示例照跑;全套 364 条通过(原 342)。没做的记在 ROADMAP P3 #1(系统框图 / 频段取舍 / 基线扫描、表格编辑、YAML 载入导出、Android)。

---

## [0.2.22] — 2026-11-19 — 配置层拒绝两种"收下却没照办"的设置(拨旋钮查出来的;数字不动)

- **2 个虚拟阵元 + 首权为零的角窗(hann、blackman)被拒绝**。原来:`mimo.n_rx: 2`(或 2 TX × 1 RX)配默认的 Hann,20° 的目标两个引擎都读成 −69.6° 左右、不报错。
  原因是 `processing.windows` 用周期形式,hann(2) = [0, 1],只剩一个阵元,波束形成器没有方向。报错写明两条出路:`angle_window` 换 rect / hamming,或至少 3 个虚拟阵元;
  按它说的改,读数回到 20.0°(±0.02°)。**更正**:0.2.21 的记录写"两个权都是 0",实际是 [0, 1]。新常量 `schema.ZERO_FIRST_WINDOWS`,测试要求它与窗函数自己的行为一致。
- **`lo.engine: response` + `lo.dp_cal: online` 被拒绝**。原来:线性化引擎没有在线校准,收下设置后不校准也不提示(5 % 失配时 `dp_gain_used` 仍 1.05)。
  `ideal` 引擎没有误差曲线,不拒绝;逐周期引擎照常校准到 1.0026。
- 界面规格跟着改:`CHOICE_WHEN` 从两头声明这一对,新函数 `refused_choices(values)` 给页面要置灰的选项;配置层的报错原样到页面。
- 多普勒维同源的情形量了、没改(ROADMAP P1 #8):每个发射通道 2 个 chirp 配 Hann 只剩一个 chirp,SNR 27.04 dB 两个引擎一致(rect 30.05),速度读数无意义(+2 m/s 读成 −12.49)。
- 随库配置、示例、指纹用例里都没有这两种组合:指纹 2451 个值逐位不变,十个示例照跑;全套 342 条通过(原 340)。break-check:两处拒绝各关掉一次,各 2 条红。
  ROADMAP 删掉 P1 #7 的 (a)(c),留下高通那一条,新增 #8。

---

## [0.2.21] — 2026-11-19 — 图形界面 P1:界面规格层 `guispec` 与"每个旋钮拨一格"的测试(数字不动)

- **界面方案定了**(用户):方案 A 的风格,补入方案 B 的九处,加系统框图页(合并稿见 `cairn/gui.md`)。做法照 polar_tx / array_tx:一份网页界面三个宿主,
  描述 guispec / 计算 guiutil / 分发与队列 / 画;页面只画不算。这一版只做描述层,没有界面代码。
- **`guispec.py`**:88 个控件 = `config/form.py` 的字段(另 1 个 `HIDDEN`);中英文标签、显示单位与换算、显示范围与步进(69 个数值控件)、常用 34 个;
  默认值读自 `RadarConfig()`;留空字段背后的数(18 个)经库自己的查找解析,带出处标签与来源表的键,跟着频段、目标类型、接收增益走;
  `when`(27 个控件在什么设置下才起作用)与 `inert(values)`;`seen`(拨了在哪读到:报告 / 时域帧 / 一次运行);`tags`(界面上改过的数是 `assumed`);
  `values_to_config`(经 `config_from_dict`;填了来源表原数的字段写回留空,配置逐值不变);`band_switch`;`METRICS` 13 个、`ENGINES` 5 条;`spec()` 38 kB 的 JSON。
- **测试 `tests/test_guispec.py` 102 条**:控件与表单字段一一对应;表单全取默认 / 空表单都构造出 `RadarConfig()`;五个随库配置经表单往返不变;
  **每个控件按自己的步进拨一格,它声明的那个输出必须变**(86 条);条件不成立时拨同一格输出逐位不变;标签规则;规格是 JSON。
  break-check(改坏再恢复):丢条件 1 条红、空字段放回控件 4 条、假条件 1 条、高通读数处写错 3 条、步进不合法 1 条。
- **拨旋钮摸出来的四件事**(都没改库,记进 ROADMAP):`sim.pn_bins_per_decade` 没有任何引擎读(P2 #5);`lo.engine: response` 下 `lo.dp_cal: online` 被静默忽略(P1 #7a);
  IF 高通单独开时统计引擎不认,时域引擎在 1 MHz 截止下目标掉 1.08 dB(P1 #7b);2 个虚拟阵元 + 默认 Hann 角窗,20° 的目标读成 −69.6°,没有报错(P1 #7c)。
- 指纹 2451 个值逐位不变;全套 340 条通过(原 238)。新专题文档 `cairn/gui.md`;ROADMAP 的"GUI 与 Android"改写成还剩的 P2–P4。

---

## [0.2.20] — 2026-11-18 — 默认配置改到合规:发射机回退 8 dB(EIRP 22 → 14 dBm),帧周期 1/30 s(numbers-move)

- **用户的决定**(看了 0.2.19 的取舍表,选项 (a)):留在 58–62 GHz,把 EIRP 降到 47 CFR §15.255(c)(2) 57–64 GHz 档的 14 dBm,声明帧周期。不换频段,不动天线占位。
- **新配置量 `frontend.tx_backoff_db`**(≥ 0,空 = 频段的占位):发射机从 `tx_power_dbm` 回退多少。60 GHz 档 8 dB(`assumed`,设计取舍 = 12 + 10 − 14,测试守着这个等式和手册的 26 dB 回退范围);
  77 GHz 档 0。12 dBm(spec)与 10 dBi(assumed)没有动。链路预算、泄漏预算、合规检查都按 `tx_power_dbm − tx_backoff_db`(`RadarConfig.tx_conducted_dbm()`)。
- **`chirp.frame_period_s` 默认 1/30 s**(原来不声明):最坏的 33 ms 里关断 26.6 ms(要求 25.5)。五个随库配置都写了这一项。帧比它长的配置加载时报错,要自己给帧周期或置空。
- **默认配置的判定**:治理档 57–64 GHz,EIRP 14.0 dBm,余量 **+0.0 dB**,关断满足 → 合规(0.2.19:超 8.0 dB,关断无法判断)。mimo / x10lo / dither 同;77 GHz 档仍"不适用",现有值逐位不变。
- **跟着动的数(5 m 人体)**:EIRP 22 → 14 dBm;P_r −85.11 → −93.11 dBm;C/N0 76.80 → 68.80 dBHz;格点 SNR 51.34 → 43.34 dB(15 m 处 24.0 dB,图上 Pd 0.9 要 12.24);
  时域 43.10 对期望 43.07(+0.03 dB;2 / 5 / 10 m +0.09 / −0.03 / −0.08)。
  鬼目标:电平不变(−37.3 dBc),每帧 2.75 → **0.18** 个(Pd 0.98 → 0.08;示例 00 主瓣外 35 → 12 格,期望 10.5 个噪声虚警格);32 chirp 1.40 → 0.026;
  dither 1 / 2 / 3 LSB 0.0004 / 0.0010 / 0;`radar_60g_mimo` 回退后仍 0.79 个,`radar_60g_x10lo` 0.52 个。示例 05 四目标帧 284 → 159 格。
  测角(2 × 4,20°):每元 39.3 → 31.3 dB,界 0.023° → 0.058°,期望散布 0.041° → 0.103°,时域 32 个 seed 0.044° → 0.110°。
  泄漏:接收端 −8 → −16 dBm,对带外压缩点 −4 → **+4 dB**;回波被压 10.65 → 1.49 dB,热噪声 8.35 → 1.44 dB,SNR 损失 2.30 → 0.05 dB(`radar_60g_mimo` 48.66 → 43.27 dB);
  2 阶 200 kHz 后 ADC 裕量 33.2 → 36.4 dB,阶跃 8.78 → 6.04 V,推荐 blanking 4.77 → 4.34 µs。分辨率、相噪、chirp 的数不动。
- **示例 09** 改成"发射机满功率时各频段允许什么"(表里的数与 0.2.19 相同)加"随库配置现在的判定";示例 00 / 08 打出回退量。示例 00 / 04 / 05 / 07 / 08 / 09 的期望输出重新生成。
- **测试**:机制类测试(泄漏、压缩、鬼目标进虚警账、dither、检查的各档逻辑)固定在满功率(`tx_backoff_db: 0`)上,断言不变;默认配置的新结论另加断言。
  `tests/test_compliance.py` 22 → 24 条(默认合规且余量 0、回退量的等式、1/32 s 就不合规、回退量进链路与泄漏预算);全套 238 条通过。
  break-check(改坏再恢复):回退量占位改成 7 dB → 4 条红;泄漏预算不读回退量 → 3 条红。
- **指纹(numbers-move)**:原有 2400 个值里 476 个变了(全是跟发射功率走的:SNR、P_r、目标电平、时域帧、检出数、泄漏与压缩、合规判定),1924 个逐位不变;
  新增 51 个 `compliance.*` 键(`tx_power_dbm`、`tx_backoff_db` 各 17,原来没声明的 `frame_period_s` 17)。77 GHz 配置的原有值全部不变。

---

## [0.2.19] — 2026-11-18 — 规管合规检查(47 CFR §15.255(c)(2))与频段取舍表:默认配置超限 8 dB(现有数字不动)

- **合规检查** `link/compliance.py`:输入扫频范围、EIRP、传导功率、一帧的发射段、帧周期、使用场景;输出每一档(频段包不包得住扫频、场景、关断、余量、最短帧周期)、
  治理档(能用的里面上限最高的)、超没超、差多少 dB、关断够不够。限值 44 个数全在 `data/sources.yaml`(`fcc15255.*`,`source: spec`,`upstream:` 指向 spec_sources 的条目,加载时核对);
  模块里没有一个限值。57–71 GHz 之外回答"不适用"。
- **默认配置**(58–62 GHz、22 dBm EIRP、6.4 ms 的帧):治理档 57–64 GHz,上限 14 dBm,**超 8.0 dB**;关断要求 ≥ 25.5 ms / 33 ms → 帧周期 ≥ 31.90 ms(≤ 31.3 帧/秒),
  帧周期没声明时写"无法判断"。帧周期 31.8 ms 时这一档不能用,只剩默认档(传导 −10 dBm → 0 dBm EIRP)。**这一轮不改默认配置**(ROADMAP P0)。
- **新配置量**(只进检查,不进信号处理):`chirp.frame_period_s`(空 = 不声明)、`regulatory.scenario`(`indoor` / `outdoor` / `outdoor_fixed` / `vehicular` / `uav`,空 = 不声明)。
- **链路预算多一列"按合规上限"**:`link_budget(cfg, eirp_cap_dbm=...)`,EIRP 取 `min(pt + gt, 上限)`,其余不变;默认 5 m 人体 51.34 → 43.34 dB。原来那一列逐位不变。
  报表(JSON 与 Markdown)多"Regulatory check"一节,每个数带出处标签,并列出条文没说的五件事各按什么读。
- **示例 09 频段取舍表**(同一目标、同样的帧,EIRP 取上限):58–62 GHz 14 dBm / 5.39 cm / 43.34 dB / ≤ 31.3 帧/秒;57–59.4 GHz 室内 20 dBm / 8.98 cm / 49.60 dB / 不限;
  57–61.56 GHz 20 dBm / 4.73 cm / 49.44 dB / ≤ 68.3;57–64 GHz 14 dBm / 3.08 cm / 43.27 dB / ≤ 31.3;57–64 GHz 室外固定 20 dBm / 49.27 dB / ≤ 68.3。
- **发射天线增益在上限下不起作用**:`tx_gain_dbi` 2 / 6 / 10 dBi 按上限的 SNR 逐位相同(43.34 dB);`rx_gain_dbi` 8 / 10 / 12 dBi → 41.34 / 43.34 / 45.34。预期先写进测试再跑,一次通过。
  ROADMAP"等上游"#1 改写:不确定只剩接收侧。
- 其它配置:mimo(TDM,同一时刻一个发射通道,按单通道 22 dBm)、x10lo、dither 同默认;77 GHz 档(76.5–78.5 GHz)不适用,不套 60 GHz 的限值。
- 测试 `tests/test_compliance.py` 22 条;break-check(改坏再恢复):去掉关断判据 10 条红、上限不作用到预算 3 条红、读错档的上限也红;另有一条 monkeypatch 改表、判定跟着变。
- 指纹(numbers-move):只新增 247 个 `compliance.*` 键;原有 2153 个值逐位不变。新专题文档 `cairn/regulatory-compliance.md`。

---

## [0.2.18] — 2026-11-18 — spec_sources 重新 pin:§15.255(c)(2) 的雷达限值进了副本(还没读,数不动)

- spec_sources#50(本库发起):重新 pin 到 `18241cd`,多 vendor `data/regulatory.yaml`(14 条:原有 `fcc15255.*` 4 条 + 新建的雷达限值 10 条);
  其余 6 个文件正文没变,只换出处头里的 SHA。按它的要求先单独换 pin:指纹 2153 个值逐位不变;`vendor_check --strict` 38 个文件,37 verbatim / 1 adapted。
- 本库还没有引用这些条目(合规检查在下一个 PR)。

---

## [0.2.17] — 2026-11-18 — 扣除式 TDC dither 接进配置(默认关):开了鬼目标消失,相噪电平不变

- **新配置字段** `lo.tdc_dither_lsb`(均匀 dither 的宽度,LSB,默认 0 = 关)与 `lo.tdc_dither_gain_error`(DTC 增益误差)。pll_simulator#80 的扣除式 dither:
  TDC 处注入已知伪随机偏移、数字域减掉。**默认关**(用户定):这颗 60 GHz ADPLL 有没有它没有出处,默认配置的鬼目标(每帧 2.75 个)照旧报。
  `configs/radar_60g_dither.yaml` 是开 1 LSB 的同一个雷达。
- **开了以后**(默认 64 chirp、5 m 人体):dither 1 / 2 / 3 LSB → 每帧鬼目标 0.0021 / 0.0089 / 0.0000 个(关 2.7506),最强 −50.9 / −51.8 dBc / 检出限以上没有(关 −37.3);
  L(1 MHz) −75.89 dBc/Hz 不动。14 个斜坡的相干分量 300 kHz 以上回到 −10 … −16 dB(纯随机 −11.5;关时 300 kHz −1.3),电平对剖面 0.6 dB 内。
- **dither 在 `noise=False` 下也生效**:文件剖面配置(×10 LO,ROADMAP P1 #1(b))开 1 LSB 后每帧 2.96 → 0.0023 个,鬼目标从不开噪声但抖动的 ramp 上搜;
  `ghosts_quiet` 在 dither 开着时改由关掉 dither 的同一环路给(仍是 −34.1 dBc 的那个图样)。
- **LO 剖面多两项**:`tdc_dither_mod`(TDC 按标称周期归一化 × 斜坡的频偏,dither 把这个图样变成噪声;距离窗加权后比 `tdc_quant` 低 25.6 dB)、
  `tdc_dither_gain`(ε² 倍)。时域引擎不开噪声的曲线带 `lo.CURVE_TERMS` 四项,不重复合成。
- **停泊段**:CW `simulate − analyze` 关 / 1 LSB / 3 LSB = +14.9 / +2.8 / +0.65 dB;1 LSB 不够(每 DCO 周期 5.46 个码,不是整数),死区标记 1 LSB 仍在、3 LSB 不在。
- **报表**:环路 `simulate()` 自己的 notes 打在 chirp 一节下(默认配置会看到"TDC quantization follows the modulation");鬼目标一段写明 dither 的宽度和噪声开没开。
- 示例 02 末尾多一张 dither 表。测试 `tests/test_tdc_dither.py` 8 条。
- 指纹(numbers-move):只多了新配置 `radar_60g_dither` 的 118 个值;原有 2035 个值逐位不变。

---

## [0.2.16] — 2026-11-18 — polar_tx 重新 pin:扣除式 TDC dither 进了副本(默认关,数不动)

- polar_tx#26(本库发起)了结:`vendor/polartx/` 重新 pin 到 polar_tx `48b7f41`,它的 pllsim 子树在 pll_simulator `3d8611f`(pll_simulator#80 的 #81 / #82)。
  26 个文件里 23 个 pllsim 文件换了嵌套头,正文变的是 `arch/adpll.py`、`blocks/tdc.py`、`core/boundaries.py`、`core/engine.py`;本库直接 vendor 的 3 个 polar_tx 文件只改外层头。
- 带进来的:`TDCConfig.dither_lsb` / `dither_gain_error`(默认 0)、`analyze()` 的 `tdc_dither_gain` 项、`ADPLL.tdc_dither_mod_residual`、`simulate()` 的斜坡提示、
  锁定检测先减 `mod_freq`、死区判据计入 dither 的 RMS。**都还没接进本库的配置**(ROADMAP P1 #1(a) 列了六件要做的)。
- 指纹 2035 个值逐位不变;`vendor_check --strict` 37 个文件,36 verbatim / 1 adapted,无漂移;pytest、ruff 绿。

---

## [0.2.15] — 2026-11-18 — 更正"斜坡上线性剖面差 ±3.5 dB":稳的是相干分量(数不动)

- pll_simulator#80(本库发起)的答复:在它的 main 上用本库的环路复现,按频带平均电平与 `analyze()` 差 1 dB 左右;0.2.12 的 ±3.5 dB 是单个 seed、±25 % 频带的读数,
  300 kHz 那个带套住了一条每个斜坡都重复的谱线(±15 % 频带、seed 7–9:−0.7 … −3.3 dB)。本库重量后同意。
- 稳的量是**相干分量**:1 ps 抖动、16 个斜坡,300 kHz 处 −1.3 … −1.5 dB、1–10 MHz −3.7 … −5.6 dB(纯随机 −12);6.5 ps 回到随机水平。两边独立量的一致。这正是一帧积出鬼目标的部分。
- `test_the_default_tdc_is_not_dithered_enough_for_the_profile` 改为断言相干分量(默认 300 kHz > −3 dB、300 kHz 以上都 > −6 dB;半格抖动 < −9 dB),电平只留宽界;README、ROADMAP、`cairn/chirp-engine.md` 追加更正。
- ROADMAP P1 #1(a):dither 改为等 pll_simulator#80 的扣除式 TDC dither(默认关、幅度按 LSB、DTC 增益误差单列、`analyze()` 补失配项)。指纹不动(只改测试与文档)。

---

## [0.2.14] — 2026-11-17 — spec_sources 0.6.0 重新 pin(数不动)

- fmcw_radar#21(spec_sources 发起):重新 pin 到 `a9af261`(spec_sources 0.6.0)。本库拷的 6 个文件里只有 `data/frontend60.yaml` 变了:
  `rx60.comm_iscas2015` 与 `antenna60.okada2013_dbi` 由 survey 改 spec,值不变,都不是本库读的条目;其余 5 个只改出处头里的 SHA。
- 指纹 2035 个值逐位不变;`vendor_check --strict` 37 个文件,36 verbatim / 1 adapted,无漂移。
- ROADMAP"等上游"#1 记上 Okada 2013 的封装内 6 dBi(读过原文,但不是阵元,不替换天线增益占位);#2 删掉已办完的"#19 由它登记"。

---

## [0.2.13] — 2026-11-14 — 最后 6 条 survey 读了原文;来源表不再有 survey(数不动)

- fmcw_radar#19(spec_sources 发起):spec_sources 重新 pin 到 `f87cc9b`,多 vendor `data/windows.yaml`,`data/radar_targets.yaml` 多 4 条;其余四个文件只改出处头里的 SHA。
- **窗宽 4 条**(`window.{rect,hann,hamming,blackman}_3db_bins`):survey → spec,`upstream: spec_sources:harris1978.<窗>#bw_3db_bins`,quote 是表 I 那一行。值不变。
  **更正**:Blackman 那条的 cite 原写 "exact Blackman",1.68 是 Blackman 那一行(exact Blackman 是 1.52)。
- **乘用车** `rcs.car_dbsm` 10 dBsm:survey → derived,`upstream: spec_sources:target_rcs.iso19206_3_car_rear_far_lower_dbsm`(ISO 19206-3 车尾、40 m 以外那条带子的下界 20 − 10)。
  保持下界不取中心 20:ISO 的中心近处下降,本库的距离(≤ 15 m)上 4–12 dBsm。
- **角反射器** `rcs.corner_reflector_dbsm` 20 dBsm:survey → assumed(本库自选的测试目标)。**更正**:原 cite 的"10 cm 边、~10² m²"按同一公式只有 12.2 dBsm;
  数保持 20,尺寸改成 15.6 cm 三角形三面角(60 GHz;77 GHz 档相当于 13.8 cm),公式出处 Doerry,Sandia SAND2008-0396。
- 来源表 25 assumed / 11 spec / 0 survey / 3 derived。ROADMAP"等上游"#2 的 6 条删掉;新 P1 #5:RCS 不随距离、视角、频段变。
- 示例 03 的表头改读条目自己的标签(原来写死 "survey")。指纹 2035 个值逐位不变。

---

## [0.2.12] — 2026-11-14 — 60 GHz 的 TDC 读原文的 12.2 ps;默认配置出现鬼目标检出

- fmcw_radar#17(spec_sources 发起):spec_sources 重新 pin 到 `e49979f`,多 vendor 一张表 `data/adpll60.yaml`(其余四个文件相对 `dfaa36b` 不变)。
- **`60g_sensing.tdc_res_s` 5 ps(assumed)→ 12.2 ps(spec)**:Wu、Staszewski、Long,IEEE JSSC 49(5) 2014 §VI.A,一颗 56.4–63.4 GHz FMCW ADPLL,
  `upstream: spec_sources:adpll60.wu_jssc2014_tdc#tdc_res_s`。时间步长照搬到本库的 15 GHz ×4 环路:带内底只由步长和载频决定,本库剖面的 TDC 项 −77.5 dBc/Hz
  对原文理论 −78、实测 −77。77 GHz 频段不套,仍 5 ps 占位;TDC 抖动仍 1 ps 占位(两篇原文都没给,cite 里写明)。来源表 24 assumed / 7 spec / 6 survey / 2 derived。
- 后果(默认 config):L(1 MHz) −79.6 → −75.9 dBc/Hz,5 m 残余 55.3 → 84.0 mrad,+1 / +5 m 底 −63.3 / −51.4 → −58.4 / −47.7 dBc/格,期望格点 SNR 51.09 → 50.91 dB;
  chirp 量化底 0.54 → 1.25 MHz RMS,ISLR −28.6 → −22.6 dB。**鬼目标结论翻了**:1 ps 抖动只有 0.08 格(5 ps 时 0.2 格),打不散量化,
  最强 −54.8 → −37.3 dBc,每帧检出 0.00 → **2.75** 个(示例 00 主瓣外 22 → 35 格;示例 05 四目标帧 70 → 284 格)。ROADMAP P1 #1(a) 改写。
- CW 死区:1 ps 时 `simulate − analyze` 均 +14.9 dB(5 ps TDC 时 +5.5 … +10.9),半格要 6.1 ps;测试的"不被标"对照从 5 ps 换成 6.5 ps。
- 同一个原因,斜坡上逐周期引擎对线性剖面在 100 / 300 kHz 差 ±3.5 dB(5 ps 时 0.6 dB 内,半格抖动回到 1.2 dB 内;**0.2.15 更正**:那是一种读法,稳的是相干分量)。测试:`test_lo_noise_split` 的账目检查改在
  "12.2 ps + 半格抖动"上,量化形状两条留在 5 ps,新加一条守着默认的偏离;鬼目标、死区、chirp 的机理测试改写成新数并保留 5 ps 的对照。
- `data/clock_profiles/adpll_15g_fingerprint.yaml` 用 `tools/export_lo_profile.py` 从新默认重新导出;示例 01 的说明行改读 config 的 TDC 值(原来写死 "5 ps")。
- 指纹(numbers-move):2035 个值里 720 个动(1979 → 2035:过检出限的鬼目标多了);全部经 LO / chirp 传下来。77 GHz 配置、response 引擎的 chirp、接收功率与热噪声逐位不变。

---

## [0.2.11] — 2026-11-13 — 氧气衰减与人体 RCS 对上原文;新增 `derived` 标签

- fmcw_radar#15(spec_sources 发起):spec_sources 重新 pin 到 `dfaa36b`,多 vendor 两张表(`data/atmosphere.yaml`、`data/radar_targets.yaml`)。
- **氧气衰减改成 ITU-R P.676-13 逐线法**(干空气、海平面,频段中心):60 GHz 15.0 → **14.651** dB/km,77.5 GHz 0.4 → **0.091** dB/km。
  旧的 15.0 是 60.81 GHz 处的峰值(15.06),0.4 接近 77 GHz 的总气体衰减(氧气 + 水汽);用 itur 0.4.0 独立复算一致。只算氧气,不含水汽(选项 (a))。
- **人体 RCS** 仍是 −10 dBsm,出处从转述换成读过原文的 arXiv:1910.13706(77 GHz 行人射线追踪仿真,同极化 −10 … +5 dBsm 的下端),标 `spec`。
- **新标签 `derived`**:原文印的是谱线表和公式、没有直接印这个数,所以氧气两条标 `derived`;derived 条目必须带 `upstream` 和写公式的 note。来源表 25 assumed / 6 spec / 6 survey / 2 derived。
- 指纹(numbers-move):只有经接收功率传下来的值动(氧气损耗 → P_r → SNR、目标电平、时域帧);噪声、相噪、chirp、CFAR 统计逐位不变。5 m 人体格点 SNR +0.004 dB。

---

## [0.2.10] — 2026-11-13 — 前端的五个数改读共享库 spec_sources(只搬家,数不动)

- fmcw_radar#13(spec_sources 发起):vendor spec_sources@`d7b4d1e` 的 `reader.py` 与 `data/frontend60.yaml`(`vendor/spec_sources/`);
  删掉 `vendor/mmw60/` 的 `spec.py` 与 `data/spec/survey.yaml`,那里只剩 ×10 LO 剖面(仍 pin 在 mmw60_trx@`ef0f00c`)。
- `data/sources.yaml` 的 5 条 `upstream:` 改成 `spec_sources:<引用>`;`value` / `cite` / `quote` / `section` / `note` 不动。隔离度的减法换成 spec_sources 的
  derived 条目 `isolation.tx_rx_tue2018_no_ebg_min_db`(40 − 20 = 20 dB)。`sources.upstream_value` 只剩查找(读取器的 `ref()`,`KeyError` 转 `ValueError`),
  不再自己解析 `@` 和 `-`;引用里的减法现在被拒。
- 测试:来源守卫换读 spec_sources、坏引用多一条"减法";vendored 表的四个标签数得准(`audit_tags`);vendor 检查的 pin 表加 spec_sources。CI 的 vendor-drift 多检出 spec_sources。
- 指纹:逐位不变(1979 个值)。

---

## [0.2.9] — 2026-11-12 — 接收机的两级压缩;×10 LO 的配置;推荐 blanking 不再给无效值

- **接收机压缩模型**(ROADMAP 原 P1 #4,`link/compression.py`):高通之前一级(带外 P1dB)、之后一级(带内 P1dB),各是一个 Rapp 限幅(膝部 `frontend.rx_rapp_p`,占位 2)。
  时域引擎逐样本过两级;统计引擎用闭式(弱信号在强信号旁:回波保留 (F′ + F/B)/2、噪声 (F′² + (F/B)²)/2),泄漏造成的压缩进所有 SNR(`LinkBudget.compression_*`、
  `LeakageBudget.compression_*`)。默认档:泄漏 −8 dBm 比带外点高 4 dB → 前级压掉泄漏 5.24 dB,回波 −10.65 dB,SNR −2.3 dB;两个引擎对同一帧差 ≤ 0.35 dB。
  `frontend.compression: false` 是原来的线性接收机。**更正 0.2.8 的结论**:"1 阶 200 kHz 高通不够、78 % 削波"是线性接收机的;有压缩时 ADC 还有 5.3 dB,代价在回波上。
- **×10 LO**:`configs/radar_60g_x10lo.yaml` 用 mmw60_trx 的 ×10 剖面(vendored,逐字节校验)。文件剖面下 chirp 发生器的量化只算一次(外来文件在 event 引擎下加上两项量化,
  导出的文件带分项)——之前时域比闭式高 10–15 dB。结论:带内的底是发生器的 5 ps TDC(L(1 MHz) −85.1),不是 ×10 LO(−98.6)。
- **推荐 blanking**(原 P1 #5):瞬态要落进 ADC 在稳态泄漏之上还剩的量程;稳态泄漏本身到满幅时不给推荐(`steady_clipping`),改报还缺多少衰减。示例 08 列出没 blank 的情形和原因。
- 新配置字段 `frontend.rx_rapp_p`、`frontend.compression`;来源表多两条 `rx_rapp_p`(占位,两个频段)。
- 指纹(numbers-move):带泄漏的三个用例(`radar_60g_mimo`、`leakage_hpf`、`leakage_hpf_blanked`)、文件剖面用例的鬼目标表、新配置;其余逐位不变。

---

## [0.2.8] — 2026-11-12 — 前端的数有了出处:读 mmw60_trx 的来源表;接收压缩点拆成两个

- **vendor mmw60_trx 的来源表**(`vendor/mmw60/`:`spec.py` + `data/spec/survey.yaml`,pin `ef0f00c`;不 vendor `Frontend60`)。漂移检查现在也逐字节比 vendored 的 YAML;CI 多检出一个姊妹库。
- **60 GHz 档五个数从占位换成读过原文的**(`source: spec`,带引文;`upstream:` 指向上游条目,加载时核对相等):发射 10 → 12 dBm、NF 10 → 12 dB、收发隔离 25 → 20 dB、
  接收压缩点 −20 dBm → 带外 −12 dBm 与带内 −34 dBm(40 dB 增益)。前三条与两个压缩点来自一颗 60 GHz 雷达芯片的手册(TI SWRS219F 7.9 节),隔离来自 Adela 等 2018。
  天线增益与 RX 增益档仍是占位(设计选择,没有对口的出处)。来源表 26 → 23 条 `assumed`,0 → 5 条 `spec`。
- **接收压缩点是两个量**:`frontend.p1db_dbm` 拆成 `p1db_oob_dbm`(高通之前;泄漏碰到的)与 `p1db_inband_dbm`(回波碰到的;留空时随增益每 dB 降 1 dB,`RadarConfig.p1db_inband()`)。
  泄漏预算按每一项的拍频在高通截止的哪一侧选点(`LeakageBudget.p1db_kind`)。**配置里写了 `frontend.p1db_dbm` 的要改成这两个字段。**
- 结论的变化:SNR 几乎不动(+0.04 dB:发射与 NF 各 +2 dB 抵消);泄漏强 7 dB(接收端 −15 → −8 dBm)——对带外压缩点 −4 dB;2 阶 200 kHz 高通的 ADC 裕量 +35 → +28 dB、推荐 blanking 4.5 → 5.4 µs;
  **1 阶 200 kHz 高通不再够**(高通后泄漏在 ADC 满幅,稳态削波 78 %)。
- 指纹(numbers-move):60 GHz 的预算、所有带热噪声 / 泄漏的时域帧、两个改名的预算行;chirp 曲线、相噪、77 GHz 的数逐位不变。示例期望输出重新接受。

---

## [0.2.7] — 2026-11-12 — 重新 pin polar_tx(b007e60):上游的 TDC 抖动项、内核里的 dp_cal、有效域的定论

- **vendor 重新 pin**:polar_tx `7057738` → `b007e60`(嵌套的 pllsim 整体到 pll_simulator@5564c64;多一个 `core/tdcspurs.py`)。polar_tx#19 的答复(B1 的真因、C5)都在里面。
- **TDC 抖动项用上游的**:`analyze()` 自带 `tdc_jitter`(pll_simulator#77),本库 `lo.py` 自己加的那段删了(同一个式子,相对差 2e-16);`simulate()` 的 TDC 抖动跨边沿回绕(#78)。
- **`ChirpFlybackLMS` 改成步进内核**(`flyback_dp_step` + `kernel_view` / `kernel_done`):polar_tx 把 `dp_cal` 搬进了 ADPLL 的逐周期内核,只有 `.step/.value` 的对象会抛 `TypeError`。
  校准轨迹与改前逐位相同;装了 numba 时编译与解释逐位一致。
- **有效域**:495 % UI/周期不再是越界——polar_tx 查到真正的条件是 TDC 量程盖住一个 DCO 周期(本库 9.5 个)。`build_adpll` 拒绝盖不住的 TDC(三个引擎都拒绝);
  报表的措辞改成描述量,并多一个 `ChirpResult.dco_dev_frac_p99`(DCO 偏离标称 ±3.3 %)。
- **量了上游的一条推断**:TDC 按标称周期归一化在斜坡上不是"被环路吃掉":不抖动时频率误差 513.8 对 498.4 kHz RMS,最强静态鬼目标 −45.7 对 −48.1 dBc;
  带 1 ps 抖动时看不出。保持建模,记在 ROADMAP P1 #2(可接 vendored 的 `TdcPeriodCal`)。
- **报表说明剖面在哪里不再是答案**(P1 #1(c) 的标注部分):`lo.parked_lo` 与 `LOProfile.notes` 把上游 `analyze()` 的 TDC 死区提示接进相噪一节——
  LO 停在载波(CW)或斜坡起点(`chirp.idle_s`)时,若那个频率是整数 N 且 TDC 输入的抖动不到半格,带内相噪高于线性剖面(默认 1 ps:+5.5 … +10.9 dB)。不动任何数。
- 指纹(numbers-move):1838 值里 253 个。chirp 曲线与静态鬼目标逐位不变;相噪旁瓣只动末位(≤ 1.75e-11 dB);带噪声的曲线只在抖动非零时动(回绕),
  随之时域帧 SNR ≤ 0.09 dB、峰值旁瓣 ≤ 0.43 dB、检测数 ±3,示例 02 的 1 ps 行 −54.6 → −54.8 dBc(换了位置)。

---

## [0.2.6] — 2026-11-12 — TDC 抖动:占位、剖面里的一项、相干杂散(P1 #1(a))

- **`lo.tdc_jitter_s`**(None → 占位 1 ps RMS,`assumed`):进 `TDCConfig.jitter_rms_s`。之前它是 0,且不在 `sources.yaml` 里——一个没登记的占位。来源表 24 → 26 条 `assumed`。
- **LO 剖面多一项 `tdc_jitter`**:与量化同形,功率是 `tdc_quant` 的 12σ²/t_res²(pllsim 的 `analyze()` 没有,pll_simulator#76)。L(1 MHz) −80.2 → −79.6 dBc/Hz。
  斜坡上逐周期引擎对这个剖面,抖动 0–5 ps、0.3–10 MHz 差 ≤ 0.4 dB。
- **鬼目标改成"一帧里什么是相干的"**(`coherent_spurs`):开环路噪声跑一帧的 ramp,距离谱相干平均里显著的局部极大(CA-CFAR 式的判据,给出检出限)。
  不抖动的图样 −45.3 dBc;抖动 0 / 0.5 / 1 / 2 ps:−49 / −51 / −55 dBc / 低于检出限。人体目标每帧鬼目标检测 0.03 → 0.00。原来的单 ramp 列表留作 `ghosts_quiet`。
- **时域引擎默认用带噪声的逐周期曲线**(LO 是 vendored 环路本身时),与统计引擎的鬼目标表共用一次运行(`noisy_chirp` 缓存)。示例 02 多一张抖动表。
- 被推翻的判断:"TDC 鬼目标是物理的,要等 pll_simulator 的 dither"——是抖动为零这个占位造成的。`tools/export_lo_profile.py` 改为导出含抖动项的剖面,bundled 的剖面文件重出。
- 指纹(numbers-move):所有相噪值(剖面多一项)、鬼目标表、带相噪的时域帧动了;预算、chirp 曲线、CFAR 的 Pfa 逐位不变。

---

## [0.2.5] — 2026-11-10 — LO 噪声在 chirp 曲线与剖面之间的分工(P1 #1(b))

- **时域引擎把 TDC 量化算了两遍**:noise=False 的逐周期曲线就是剖面的 `tdc_quant` + `dco_quant`(1 MHz 处 −85.2 对 −85.3 dBc/Hz),却叠在整份剖面上,
  1–5 m 的 LO 底比分工后高 1.1 dB(比闭式高 1.5–2.2 dB)。现在曲线带什么、剖面就不合成什么(`ChirpResult.lo_noise_in_curve`、`LOProfile.components` / `without` / `above`、`info["lo_noise_split"]`)。
- **带噪声的 chirp 曲线修对了**:`freq_out` 是调谐字的频率,不含 DCO 自己的相噪;积分它在 30 kHz 处多读 45 dB。`phase_err_carrier_rad()` 加上
  `osc_phase_dco_rad`(从 `phase_err_out` 减指令相位得到)。修后斜坡上逐周期引擎与线性剖面 0.1–10 MHz 差 ≤ 0.6 dB。
- `run_time(cfg, chirp_noise=True)`:环路到 fref/2 的噪声由逐周期引擎带,剖面只留 fref/2 以上;LO 底对闭式 −0.02 … +0.47 dB。示例 04 多一张三种分法的表。
- 发现:CW 整数 N 下 `simulate` 的带内相噪比 `analyze` 高 15 dB(TDC 死区,0.133 rad @ DCO);斜坡自带 dither 所以 chirp 时一致。并入给 pll_simulator 的条目。
- 时域 SNR 对期望的差(原 P2 #1)了结:12 个 seed 平均 +0.06 / −0.04 / +0.06 dB(2 / 5 / 10 m),单 seed 标准差 0.10–0.21 dB。指纹(numbers-move):带相噪的时域帧全部动了(少合成了量化两项),统计值与 chirp 值逐位不变。

---

## [0.2.4] — 2026-11-10 — K-look 阈值、训练窗裁剪、含自漏的 Pd、鬼目标进虚警账(P1 #3、P1 #1(c))

- **MIMO 图的 CFAR**:非相干和的格是 Gamma(K),`threshold_factor(n, pfa, n_looks)` 取 Beta(K, K·N) 的分位数(K = 8:4.6 dB 而不是 9.7 dB);`_process_cube` 用它。
  修之前 Pfa 1.2e-23,`mimo_2x4_coupled` 的 39 dB 目标 0 个检测格(现在 12 个)。精确 Pfa 推广到 K 重特征值(K 阶极点的留数)。
- **训练窗裁剪**(`cfar_window`):每轴半宽不超过 (len − 1)//2。8 chirp 帧不再绕回到被测格:设计 1e-4 实际 1.4e-6 → 6.3e-5。32 / 64 chirp 不裁,逐位不变。
- **Pd**(`cfar_pd`、`cfar_snr_for_pd`):阈值的抖动、被测格相关与目标自己漏进训练格(c_w = 0.0062)都在内;默认图 Pd 0.9 要 12.24 dB,CFAR 损失 0.49 dB。
- **鬼目标进虚警账**:每个 TDC 鬼目标当作 SNR + 电平的稳态目标,`StatResult.cfar["ghosts"]` 与 `ghost_detections_per_frame`;人体 0.03 / 帧,车 5 / 帧,时域引擎同。
- 被推翻的判断:示例 00 主瓣外的 12 个过阈格是"量化杂散"——是噪声虚警(期望 10.5 格 + 0.20 个鬼目标)。示例 00 的那行改了。
- 指纹(numbers-move):14 个用例的 `n_detections`(8 chirp 的裁剪与 MIMO 的阈值)和 8 chirp 配置的 `cfar.*` 动了,其余旧值逐位不变;多了 `cfar.*` 新键。

---

## [0.2.3] — 2026-11-10 — CFAR 有效格数(P2 #0 第三项)

- `processing/cfarstats.py`:窗与零填充后的格相关(w² 的谱)、训练集有效格数 N² / Σρ、训练格与被测格的相关、每格 Pfa 的**精确式**
  (Hermitian 型 |x|² − (α/N)Σ|y|² 的特征值:Π 1/(1 + |λ_j|/λ₊))、一帧的带内格数 / 独立观测数 / 期望虚警格。进 `StatResult.cfar`、报表与示例 06。
- 默认(Hann / Hann、距离 ×4、guard 2 + train 8):416 个训练格值 33.4 个;guard 只有 0.5 个距离格,c = 0.015;两个效应单看 2.7e-4 / 2.6e-5,合起来精确 1.02e-4。
  白噪声 1.54e7 格实测 1.062e-4(641 团,±4 %;六组配置比值 0.89–1.04);时域纯噪声帧 6 帧 1.022e-2 / 9.57e-4 / 9.2e-5 对精确式 0.98 / 0.92 / 0.90。
- 被推翻的判断:"按独立格算的闭式 Pfa 是上界"(里程碑 2 的 4 个虚警是抽样;guard 8 时实际 1.8e-4,高于设计)。
- 发现并记入 ROADMAP P1 #3:MIMO 非相干和图用单通道阈值因子(K = 8:Pfa 1.2e-23,多丢 5.1 dB);帧短于训练窗时 Pfa 塌到 1.4e-6。指纹只多 `cfar.*` 新键(numbers-move)。

---

## [0.2.2] — 2026-11-10 — 测角 RMS 归因(P2 #0 第二项)

- `VirtualArray.angle_error_budget`:本估计器(加窗 DBF + 脉冲对多普勒补偿)的一阶误差闭式,拆成四个因子乘在 CRLB 上——元方向图、格点刻度损失、
  角窗对均匀权、TDM 补偿的多普勒估计(含它与快拍的相关)。默认 2 × 4:0.0231° × 1.088 × 1.523 × 1.011 = 0.0386°(cos 元再 × 1.064 = 0.041°)。
  进 `StatResult.angle`(`sigma_expected_deg`、`factor_*`、`snr_element_cell_db`)、报表与示例 07。
- 核对:快拍级蒙卡 9 组配置 ≤ 1.5 %;时域引擎 384 个 seed 0.0395° 对 0.0386°(+2.3 %,抽样 ±3.6 %)。ADC 量化、相噪、多普勒估计都不是那 2 倍的来源。
- 示例 07:32 个 seed、期望列、同一批快拍用真多普勒 / 均匀权重读;报表的"目标角度"原来恒打 0(`report["target"]` 没带 `angle_deg`),已修。
- 被推翻的判断:"时域测角误差贴着 CRLB,差的是 ADC 量化与多普勒估计噪声"(`cairn/mimo-angle.md` 2b)。指纹只多新键(numbers-move)。

---

## [0.2.1] — 2026-11-07 — 飞回 blanking(里程碑 2 的 P2 #0 第一项)

- `rx.blank_s`:每个 chirp 开头 blanking 的时长;距离窗按剩下的样本重配(`processing.windows.range_window`,所有距离 FFT 与窗统计共用),
  近旁瓣不变、主瓣宽 n/(n − k)、SNR 损 10 log(n/(n − k));时域引擎把那些样本置零并另报 `clipped_fraction_after_blanking`。
- 泄漏预算多五行:锯齿重启的泄漏相位跳变在 ADC 的阶跃(2A|sin(Δφ/2)| 求和,7.2 V)、高通最慢极点的时间常数(1.13 µs @ 2 阶 200 kHz)、
  推荐 blanking(阶跃落到满幅以下 + 1 个时间常数:4.5 µs)、配置值、blanking 的 SNR 损失。1 / 2 / 3 阶的推荐值盖住时域量到的削波段(余量 1.2–1.3 倍)。
- 示例 08 多 blanking 行与无噪声的远底对照;指纹 1235 → 1367 值,旧值逐位不变(numbers-move:只有新键与新用例 `leakage_hpf_blanked`)。
- 被推翻的判断:"blanking = 把样本清零"——不变的窗下清零 80 个样本把远旁瓣抬 20 dB 以上(`cairn/mimo-angle.md`)。

---

## [0.2.0] — 2026-11-07 — 里程碑 2:TDM-MIMO 测角、TX 泄漏、多目标与 CFAR 曲线

- **TDM-MIMO 虚拟阵列**(`mimo.py`,config `mimo.*`,vendored array_tx@e897c15 的 geometry / beam / coupling / touchstone):TX + RX 位置之和(默认填满的线),
  u 格点加窗 DFT 测角,TDM 多普勒相位补偿(2 m/s 不补偿偏 2.71°)、互耦三来源(analytic / survey / touchstone,相邻 −16 dB 占位 `assumed`;
  未校准偏 −0.29°,`coupling.calibrated` 后 0.0002°)、CRLB、array_tx 的波束宽与扫频斜视(60 GHz ±2 GHz 斜视 ±0.7°,FR2 的 5 倍)。
  时域引擎出 (chirp, RX, 样本) 立方,每 TX 块各自 FFT 后非相干合成,目标格 DBF:20° 目标 6 个 seed 均值 +0.014°、RMS 0.050°(界 0.023°)。
- **TX 泄漏**(`link/leakage.py`,config `leakage.*`、`rx.hpf_*`,`processing/iffilter.py`):直接泄漏(隔离 25 dB 占位)+ 近端反射体经同一 LO(τ ≈ 0,
  相噪几乎全抵消)的预算:P1dB 裕量 −5 dB、ADC 裕量 −21 dB → 2 阶 200 kHz 高通后 +35 dB;时域引擎削波 100 % → 3.5 %(飞回瞬态),
  目标在泄漏下 −18.1 dB 处被找到(预算 −16.2 dB)。
- **多目标与 CFAR 曲线**:`extra_targets` 列表进 config;统计引擎每目标一行(电平、SNR、最强他者的窗裙 / 相噪、遮蔽判断),
  时域引擎 `found_targets` 分格找峰;CA-CFAR 的蒙卡(Swerling 0 / 1)对闭式:Pd 0.9 处损失 N = 16 1.35 dB、N = 32 0.73 dB,Swerling 1 闭式与蒙卡 0.02 内。
- **修过的坑**:TDM 补偿用粗多普勒格留 −1.48° 偏差(改为相邻同 TX chirp 的相位推进);边缘波束的角旁瓣读到绕回的主瓣(谱按周期滚动);
  邻目标的主瓣被当成本目标(分格 + 局部极大);示例输出路径按仓库相对打印。
- 示例 05–08,`configs/radar_60g_mimo.yaml`,报表三节,`tests/` +25 项;指纹 691 → 1235 值,旧值逐位不变(numbers-move:只有新键)。
  CI 的 vendor-drift 作业多检出 array_tx。

---

## [0.1.1] — 2026-11-06 — 鬼目标与在线校准(里程碑 1 的 P1 余项)

- `StatResult.nonlinearity["ghosts"]`:chirp 频率误差曲线的确定性杂散,从单 ramp 的距离响应里提(主瓣外、−70 dBc 以上的局部极大),
  `ghosts_vouched` 只在 event 引擎下为真(铁律 6);报表多一张表。默认 5 ps TDC 在 ±4.85 m 处 −45.3 dBc,2 ps 时 −54.9 dBc,与时域图 3 dB 内一致。
- 在线两点校准换成飞回后 20 周期的幅值加权 LMS(`ChirpFlybackLMS`):±5 % 四个 chirp 内到 ±0.05 %,无偏;新字段 `lo.dp_cal_window_cycles`,
  `lo.dp_cal_mu` 改为窗口内增益(默认 1e-2)。四条弯路记在 `cairn/chirp-engine.md`。
- CI:单提交历史上的 fingerprint base、依赖下限的 `np.trapezoid`。指纹:在线用例与新 ghost 键动了,其余逐位不变(numbers-move)。

---

## [0.1.0] — 2026-11-06 — 里程碑 1:单 chirp、单目标

- **配置层**(`fmcw_radar.config`):frozen `RadarConfig`(频段 / chirp / LO / 前端 / 信道 / 目标 / 接收 / 处理 / 仿真),YAML 严格加载、
  dotted 覆盖、表单字段声明;两个 bundled 配置(60 GHz 感知、77 GHz 车载一档,后者只换数)。
- **来源表**(`data/sources.yaml`):前端占位 20 条 `assumed`、氧气吸收 / RCS / Harris 窗表 9 条 `survey`;`grep -c "source:"` 一次列全。
- **LO**(`lo.py`):vendored polar_tx(main 7057738)两点 ADPLL,PI 环按 (UGB, PM) 综合;相噪剖面 = analyze() ×N²(fref/2 以上取 DCO 自身),
  或 pll_simulator 剖面文件;`tools/export_lo_profile.py` 导出。
- **range correlation**(`phase_noise`):残余 PSD = 2(1 − cos 2πfτ)·S_φ;τ = 0 逐位为零;闭式与合成 0.1 dB 内;旁瓣 = 残余 L(f) + 窗每格噪声带宽,
  以及高斯相位的精确谱(`beat_sideband`:exp(R(t) − R(0)) 的变换,含各阶、拍频音相干损失 e^{−σ²})—— 残余不小时(100 m,0.3 rad)一阶在近目标处低估 8–20 dB。
- **chirp 引擎**(`chirp`):event(逐周期,`ADPLL.simulate` 直驱)、response(线性化参照)、ideal;离线 LS 两点校准(默认,两次到 1e-4)与
  差分 sign-sign 在线校准;解析二次项只作参照组。polar_tx 的 event 有效域指标在 chirp 上 495 %,判断见 `cairn/chirp-engine.md`。
- **雷达方程**(`link`):EIRP、(4π)³R⁴/λ²、氧气按 2R、RCS、NF、ADC 量化噪声、窗的相干增益、P1dB 裕量、Swerling 0 检测概率。
- **处理**(`processing`):rect / Hann / Hamming / Blackman、距离 FFT + 多普勒 FFT、峰值读数、CA-CFAR(1-D / 2-D)最简版。
- **引擎**:统计(主)与时域(5 GS/s 包络真混频 → 砖墙 IF → ADC 量化 → FFT);`run_radar(cfg)` 一个入口。
- **验收**(示例 00–04,`tests/` 120 项):矩形窗 Rayleigh 宽 3.73 cm 对 c/2B 3.75 cm(0.5 %);Hann / Hamming / Blackman 的 −3 dB 宽对窗谱 < 0.1 %、对 Harris 表 < 2.3 %;
  τ = 0 残余为零;1 / 10 / 100 m 闭式 vs 合成 0.114 dB;FFT 上 +1 / +2 / +5 m 旁瓣 +0.11 / −0.02 / −0.44 dB;三个距离 SNR 差 −0.07 … −0.10 dB
  (扣格点失配、带内相噪均值、拍频音相干损失);ADPLL 曲线(峰 199 MHz、RMS 6.2 MHz、建立 1.47 µs @ 5 % 失配;匹配时底 0.54 MHz RMS)
  喂统计引擎与时域引擎逐点相同(宽 5.39 cm,旁瓣 −31.5 dB,差 0.00 dB)。
- **工具**:`tools/budget_report.py`(一页)、`fingerprint.py`(639 值)、`vendor_check.py --strict`、`run_examples.py --smoke`、`example_drift.py`;
  CI:lint + 4 个 Python + 依赖下限 + 示例冒烟 + vendor 漂移 + 指纹。

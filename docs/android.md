# Android 应用

同一份页面的第三个宿主:一个 WebView 外壳加 APK 里的 CPython(Chaquopy),计算全在手机本地,**清单里没有任何权限**。

## 怎么得到 APK

- **CI 构建**:仓库的 *Android APK* 工作流(`.github/workflows/android.yml`)。手动触发,或 `android/` 有改动的 PR 自动跑;产物 `fmcw-radar-debug-apk` 是一个约 72 MB 的 debug APK(arm64 手机 + x86_64 模拟器两个 ABI),下载后侧载安装。
- **本地构建**(需要 Java 17、Python 3.10、Android SDK,并且能访问 `chaquo.com`):

```bash
python -m build --sdist --outdir android/app/pysrc .     # 每次改了 Python 都要重做:Gradle 看不穿 tarball
gradle -p android :app:assembleDebug                     # -> android/app/build/outputs/apk/debug/app-debug.apk
```

## 手机上与桌面不同的三处

| | 桌面 | 手机 |
|---|---|---|
| 逐周期引擎的全量结果 | 预览之后自动算(在另一个进程里) | 预览条上点"算逐周期结果"才算:手机上只有一条 Python 线程,它算的时候别的都得等 |
| 配置文件 | 文件下载 / 文件选择 | 一块文本:导出是可复制的 YAML,载入是把 YAML 粘贴进去 |
| 长任务(时域帧、扫描、频段表) | 各自的进程,取消即终止 | 线程:扫描和频段表在两步之间停,时域帧跑完丢结果 |

随库配置菜单在手机上没有(`configs/` 不在安装包里)。

## 版本:手机上跑的是哪组依赖

Chaquopy 的二进制 wheel 只能从它自己的仓库装。Python 3.10 是那里有 scipy 的最新版本,给到的是 **numpy 1.26.2、scipy 1.8.1**。

- 本库声明 `scipy>=1.11`(在 1.10.1 上 `ncx2.sf` 会直接中止进程),但 **Chaquopy 的 pip 不按 sdist 声明的下限拦**:构建照样成功,装进去的是 1.8.1。
- 1.8.1 早于那个会中止的实现,整套测试在这组版本上通过;它有另一个毛病:参数到 1e9 量级时 `ncx2.sf` 返回 −1.66e-06,`processing.detection.ncx2_sf` 在那里换成正态极限。
- CI 的 `test-android-versions` 作业在 Python 3.10 + numpy 1.26.2 + scipy 1.8.1 上跑全套;APK 工作流核对装进去的就是这一对,仓库换了版本它会红。

## 没有核实的

**没有在真机或模拟器上跑过。** CI 证明的是:工程能构建、页面文件进了 APK、库在手机的那组依赖上通过测试、页面经同一套桥接契约(在 Chromium 里仿真)能用。证明不了的:应用启动、首次导入的耗时、手势、刘海与安全区、手机上各项计算要多久。第一次侧载后做一次真实计算才算数。

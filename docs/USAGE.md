# 使用说明

## 配置

一个 YAML 一个雷达(`configs/*.yaml`),字段与默认值在 `src/fmcw_radar/config/schema.py`,每个字段的表单声明在 `config/form.py`。
留空(`null` / 不写)的前端、LO 噪声、氧气、RCS 字段按频段从 `src/fmcw_radar/data/sources.yaml` 取,带来源标签;写了就是配置自己的主张。
`frontend.p1db_oob_dbm`(高通之前的输入压缩点,泄漏碰到的)与 `frontend.p1db_inband_dbm`(带内,回波碰到的;留空时随 `rx_gain_db` 每 dB 降 1 dB,`cfg.p1db_inband()`)是两个字段;0.2.7 及以前的 `frontend.p1db_dbm` 没有了。

```python
from fmcw_radar.config import load_config, apply_overrides, RadarConfig
cfg = load_config("configs/radar_60g_sensing.yaml", {"target.range_m": 8.0, "lo.dp_gain": 1.02})
cfg2 = apply_overrides(RadarConfig(), {"band.sweep_hz": 7e9, "band.center_hz": 60.5e9})
```

派生量:`cfg.slope_hz_per_s`、`range_resolution_m`(c/2B)、`max_range_m`(IF 带宽决定)、`velocity_resolution_mps`、`max_velocity_mps`(TDM 下除以 n_tx)、
`beat_hz(R)`、`doppler_hz(v)`、`tau_s(R)`。

里程碑 2 的段:`extra_targets`(目标列表,`cfg.targets` 把主目标排在前面)、`mimo.*`(`n_tx` / `n_rx` / 间距 / 元方向图 / 角窗 / `tdm_doppler_compensation` /
`coupling.{source, c1_db, calibrated, touchstone}`)、`leakage.*`(`enabled` / `isolation_db` / `path_delay_s` / 反射体)、`rx.hpf_corner_hz` / `rx.hpf_order`、`rx.blank_s`(每个 chirp 开头
blanking 的时长,0.2.1:距离窗按剩下的样本重配,`cfg.n_blank` 是样本数;预算里 `LeakageBudget.blank_recommended_s` 给推荐值)。
`configs/radar_60g_mimo.yaml` 把它们都打开了。

## 引擎

- `run_radar(cfg)` → `RadarResult(cfg, chirp, stat, time)`;`sim.engine` 选 `statistical` / `time` / `both`。
- `run_statistical(cfg, chirp=None)` → `StatResult`:`budget`(雷达方程逐行)、`snr_cell_db`、`pd`、`range_res_*`、`pn_floor{offset: (per bin, per cell)}`、
  `nonlinearity`、`chirp`、`extras["snr_cell_expected_db"]`(扣格点失配、带内相噪、拍频音相干损失后时域引擎该读到的数);
  里程碑 2:`targets`(每目标一行:电平、格点 SNR、最强他者的裙边、`masked`)、`angle`(孔径、波束宽、CRLB、TDM 偏差、互耦偏差、斜视;0.2.2 起还有本估计器的期望散布 `sigma_expected_deg` 与四个因子 `factor_*`)、`leakage`(`LeakageBudget`)、
  `cfar`(0.2.3:训练集有效格数、与被测格的相关、每格精确 Pfa、带内格数 / 独立观测数 / 每帧期望虚警格;0.2.4:`n_looks`、`pd_target`、`snr_pd90_db`、
  `cfar_loss_db`、`ghosts`(每个鬼目标的 SNR 与 Pd)、`ghost_detections_per_frame`)。
- `run_time(cfg, chirp=None, chirp_noise=None, noise=True, phase_noise=True, quantise=True, leakage=True, hpf=True)` → `TimeResult`(`chirp_noise`:
  逐周期引擎带噪声跑,环路到 fref/2 的噪声由它带、TDC 抖动把量化打散、剖面只合成 fref/2 以上;缺省在 event 引擎且没有 `lo.profile` 文件时为真。
  `extras["lo_noise_split"]` 写明这一帧怎么分的):`rd_db`、轴、峰值位置、`snr_cell_db`、
  最后一个 chirp 的距离剖面与宽度、CFAR 检测;`extras["targets_found"]`(每目标 `(距离, 速度, 相对电平[, 角度])` 或 None)、`clipped_fraction`;
  MIMO 时 `frame` 是 (chirp, RX, 样本) 立方,`extras` 多 `angle_deg`、`angle_spectrum`、`snapshot`、`doppler_fine_hz`。开关只为一致性检查,config 里没有。
- `VirtualArray(cfg)`:`x_v`、`filled`、`snapshot(theta, doppler)`、`estimate(snapshot, doppler)`、`beamwidth_deg`、`crlb_sigma_deg`、`angle_error_budget(snr_chirp_db, theta, doppler)`、`coupling_bias_deg`、
  `tdm_bias_deg`、`sweep_squint`。`leakage_budget(cfg)` 与 `leakage_tones(cfg)`;`cfar_pd_monte_carlo(snr_db, pfa, n_train, trials, swerling=0|1)`、
  `cfar_pd_swerling1`、`cfar_statistics(cfg)` / `cfar_statistics_2d(..., n_looks)` / `cfar_pd(snr_db, stats)` / `cfar_snr_for_pd`(`processing.cfarstats`)、
  `threshold_factor(n, pfa, n_looks)` / `ca_cfar_2d(..., n_looks)` / `cfar_window(shape, guard, train)`、`hpf_attenuation_db` / `apply_hpf`;`range_window(name, n, n_blank)` 是 blanking 后的距离窗(所有距离 FFT 与窗统计都走它)。
- `ChirpEngine(cfg).run(noise=False, n_chirps=None)` → `ChirpResult`:`f_err_dco_hz` 整帧曲线、`ramp(k)` / `ramp_carrier(k)`、`metrics(k)`
  (峰值、RMS、底、建立时间)、`dp_cal_passes` / `dp_cal_trace`、`ui_per_ref_cycle_p99` / `dco_dev_frac_p99`(斜坡的两个描述量:每参考周期相位推进、DCO 偏离标称的比例)、`vouches_for_spurs`;`run(noise=True, seed=…)` 时 `noise`、`osc_phase_dco_rad`、
  `lo_noise_in_curve`(all / quantisation / none / unverified)。`noisy_chirp(cfg, seed, n_chirps)` 是带缓存的 noise=True 运行;`coherent_spurs(cfg, chirp)`
  (`engine.statistical`)在它上面找一帧里相干的杂散。`lo.tdc_jitter_s`(TDC 抖动,None → 占位 1 ps)。
- `RangeCorrelation(profile, tau)`:`residual_psd(f)`、`sidelobe_dbc(offset_hz, enbw_hz)`、`synthesize_residual(n, fs, rng)`、`measured_residual_psd`。
- `parked_lo(cfg)`(`fmcw_radar.lo`):LO 停着不扫时线性剖面是否还成立(TDC 死区;载波处与斜坡起点分开判),报表相噪一节下的那段话的来源。
- `LOProfile.from_config(cfg)`:`psd(f)` / `l_dbc(f)` 在载波处;`components`(ref / dco / tdc_quant / dco_quant / tdc_jitter 分项)、`without(*names)`、`above(f)`;`lo.profile` 指向 pll_simulator 剖面文件时按 (DCO/f0)² N² 缩放;文件带 `components` 时按它拆分,不带时在 event 引擎下加上 chirp 发生器的两项量化(`file` / `tdc_quant` / `dco_quant`),ideal 引擎下原样。
  `configs/radar_60g_x10lo.yaml` 是同一个雷达换成 mmw60_trx 的 ×10 LO(vendored 的 `pllsim_wu19_x10_60p48g_floor150.yaml`)。

## 工具

| 命令 | 作用 |
|---|---|
| `python tools/budget_report.py cfg.yaml [-o out.md] [--json out.json] [--sources]` | 预算一页 |
| `python tools/fingerprint.py record a.json` / `compare a.json b.json` | 数值指纹(铁律 7) |
| `python tools/vendor_check.py --strict [--siblings polar_tx=/path]` | vendor 漂移 |
| `python tools/run_examples.py --smoke` / `--save new/` | 示例冒烟 / 全量存输出 |
| `python tools/example_drift.py compare new/` / `accept new/` | 哪些文档数字过期 |
| `python tools/export_lo_profile.py cfg.yaml out.yaml` | 导出 LO 剖面文件 |

## 示例

| 文件 | 内容 |
|---|---|
| `00_single_target_rd_map.py` | 单目标距离–多普勒图,SNR 对雷达方程 |
| `01_phase_noise_vs_range.py` | 相噪旁瓣随 τ(0.1–100 m),闭式 vs 合成 |
| `02_chirp_nonlinearity.py` | ADPLL 曲线(event / response / 校准)对距离分辨率与旁瓣,解析二次项参照 |
| `03_bandwidth_window_resolution.py` | 扫频宽度 × 窗 → 分辨率表,时域实测对 c/2B 与 Harris 表 |
| `04_statistical_vs_time.py` | 统计 / 时域一致性:SNR 三距离、相噪旁瓣、非线性剖面 |
| `05_multi_target_masking.py` | 四目标的遮蔽表(窗裙 / 相噪)与时域 `found_targets` |
| `06_cfar_curves.py` | CA-CFAR 的 Pd / Pfa 蒙卡对闭式,CFAR 损失;图上的格相关:有效训练格数、guard 表、每格精确 Pfa 对噪声图与时域纯噪声帧 |
| `07_mimo_angle.py` | 2 × 4 TDM-MIMO:互耦三来源与校准、TDM 补偿、CRLB 与估计器的期望散布(四个因子)、斜视、双目标各自的角 |
| `08_tx_leakage.py` | 泄漏预算,高通前后的削波与目标 |

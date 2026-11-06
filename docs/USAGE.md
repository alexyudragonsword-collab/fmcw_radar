# 使用说明

## 配置

一个 YAML 一个雷达(`configs/*.yaml`),字段与默认值在 `src/fmcw_radar/config/schema.py`,每个字段的表单声明在 `config/form.py`。
留空(`null` / 不写)的前端、LO 噪声、氧气、RCS 字段按频段从 `src/fmcw_radar/data/sources.yaml` 取,带来源标签;写了就是配置自己的主张。

```python
from fmcw_radar.config import load_config, apply_overrides, RadarConfig
cfg = load_config("configs/radar_60g_sensing.yaml", {"target.range_m": 8.0, "lo.dp_gain": 1.02})
cfg2 = apply_overrides(RadarConfig(), {"band.sweep_hz": 7e9, "band.center_hz": 60.5e9})
```

派生量:`cfg.slope_hz_per_s`、`range_resolution_m`(c/2B)、`max_range_m`(IF 带宽决定)、`velocity_resolution_mps`、`max_velocity_mps`、
`beat_hz(R)`、`doppler_hz(v)`、`tau_s(R)`。

## 引擎

- `run_radar(cfg)` → `RadarResult(cfg, chirp, stat, time)`;`sim.engine` 选 `statistical` / `time` / `both`。
- `run_statistical(cfg, chirp=None)` → `StatResult`:`budget`(雷达方程逐行)、`snr_cell_db`、`pd`、`range_res_*`、`pn_floor{offset: (per bin, per cell)}`、
  `nonlinearity`、`chirp`、`extras["snr_cell_expected_db"]`(扣格点失配、带内相噪、拍频音相干损失后时域引擎该读到的数)。
- `run_time(cfg, chirp=None, noise=True, phase_noise=True, quantise=True)` → `TimeResult`:`rd_db`、轴、峰值位置、`snr_cell_db`、
  最后一个 chirp 的距离剖面与宽度、CFAR 检测。开关只为一致性检查,config 里没有。
- `ChirpEngine(cfg).run(noise=False, n_chirps=None)` → `ChirpResult`:`f_err_dco_hz` 整帧曲线、`ramp(k)` / `ramp_carrier(k)`、`metrics(k)`
  (峰值、RMS、底、建立时间)、`dp_cal_passes` / `dp_cal_trace`、`ui_per_ref_cycle_p99`、`vouches_for_spurs`。
- `RangeCorrelation(profile, tau)`:`residual_psd(f)`、`sidelobe_dbc(offset_hz, enbw_hz)`、`synthesize_residual(n, fs, rng)`、`measured_residual_psd`。
- `LOProfile.from_config(cfg)`:`psd(f)` / `l_dbc(f)` 在载波处;`lo.profile` 指向 pll_simulator 剖面文件时按 (DCO/f0)² N² 缩放。

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

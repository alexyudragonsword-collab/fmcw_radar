"""Invariant #1: one frozen config, validated at construction, round-tripping through YAML, with a form row per field."""

import dataclasses

import pytest
from conftest import REPO

from fmcw_radar.config import (RadarConfig, apply_overrides, config_from_dict, config_to_dict, dump_config,
                               load_config)
from fmcw_radar.config.form import form_paths, schema_paths


def test_bundled_configs_load_and_round_trip(tmp_path):
    for p in sorted((REPO / "configs").glob("*.yaml")):
        cfg = load_config(p)
        out = tmp_path / p.name
        dump_config(cfg, out)
        assert load_config(out) == cfg, p.name


def test_defaults_equal_the_60g_config(cfg60):
    assert cfg60 == RadarConfig()


def test_unknown_key_is_refused():
    with pytest.raises(KeyError, match="unknown config key"):
        config_from_dict({"band": {"centre_hz": 60e9}})


def test_frozen_and_replace():
    cfg = RadarConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.band.center_hz = 1.0  # type: ignore[misc]
    c2 = apply_overrides(cfg, {"band.sweep_hz": 7e9, "band.center_hz": 60.5e9, "target.range_m": 3.0})
    assert c2.band.sweep_hz == 7e9 and c2.target.range_m == 3.0 and cfg.band.sweep_hz == 4e9


@pytest.mark.parametrize("bad", [
    {"band.center_hz": 70e9},                       # leaves the 57-64 GHz window
    {"band.sweep_hz": 8e9},                         # 56-64: leaves it too
    {"rx.if_bw_hz": 6e6},                           # above fs/2
    {"chirp.duration_s": 33.33e-6},                 # not a whole number of ADC samples
    {"lo.loop_bw_hz": 50e6},                        # > fref/6
    {"lo.engine": "magic"},
    {"processing.window_range": "kaiser"},
    {"target.kind": "custom"},                      # custom needs an RCS
    {"sim.time_osr": 0.5},
    {"lo.dp_cal": "sometimes"},
    {"processing.cfar_pfa": 1.5},
    {"rx.blank_s": 30e-6},                          # more than a quarter of the chirp
])
def test_bad_values_fail_by_name(bad):
    with pytest.raises(ValueError):
        apply_overrides(RadarConfig(), bad)


def test_derived_quantities(cfg60):
    c = cfg60
    assert c.slope_hz_per_s == pytest.approx(4e9 / 100e-6)
    assert c.range_resolution_m == pytest.approx(299_792_458.0 / 8e9)
    assert c.n_samples == 1000 and c.n_ref_cycles == 10_000 and c.n_idle_cycles == 0
    assert c.beat_hz(10.0) == pytest.approx(c.slope_hz_per_s * 20.0 / 299_792_458.0)
    assert c.max_range_m == pytest.approx(c.rx.if_bw_hz / c.slope_hz_per_s * 299_792_458.0 / 2)
    assert c.velocity_resolution_mps == pytest.approx(c.band.wavelength_m / (2 * 64 * 100e-6))
    assert c.max_velocity_mps == pytest.approx(c.band.wavelength_m / (4 * 100e-6))
    assert c.dco_center_hz == 15e9 and c.lo_mult == 4 and c.dco_sweep_hz == 1e9
    assert c.doppler_hz(2.0) == pytest.approx(2 * 2.0 / c.band.wavelength_m)


def test_sourced_fields_resolve_with_their_source(cfg60):
    v, src = cfg60.frontend_value("nf_db")
    assert src == "assumed" and v == 10.0
    c2 = apply_overrides(cfg60, {"frontend.nf_db": 7.0})
    assert c2.frontend_value("nf_db") == (7.0, "config")
    assert cfg60.rcs_dbsm()[1] == "survey" and cfg60.oxygen_db_per_km()[1] == "survey"
    assert apply_overrides(cfg60, {"target.rcs_dbsm": 0.0}).rcs_dbsm() == (0.0, "config")


def test_extra_targets_round_trip_and_the_targets_property(tmp_path):
    from fmcw_radar.config import config_from_dict, config_to_dict

    cfg = apply_overrides(RadarConfig(), {"extra_targets": [{"kind": "car", "range_m": 8.0, "velocity_mps": -3.0}]})
    assert len(cfg.targets) == 2 and cfg.targets[0] is cfg.target and cfg.targets[1].kind == "car"
    assert cfg.rcs_of(cfg.targets[1]) == (10.0, "survey")
    out = tmp_path / "t.yaml"
    dump_config(cfg, out)
    assert load_config(out) == cfg
    assert config_from_dict(config_to_dict(cfg)) == cfg
    with pytest.raises(ValueError):
        apply_overrides(RadarConfig(), {"extra_targets": [{"kind": "custom", "range_m": 1.0}]})   # custom needs an RCS


def test_form_declares_every_field_and_nothing_else():
    assert sorted(form_paths()) == sorted(schema_paths())
    assert len(form_paths()) == len(set(form_paths()))


def test_config_to_dict_carries_the_schema_version(cfg60):
    d = config_to_dict(cfg60)
    assert d["schema_version"] == 1 and d["band"]["kind"] == "60g_sensing"

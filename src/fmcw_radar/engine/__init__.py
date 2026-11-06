"""The two engines behind one entry point: ``run_radar(cfg)`` (invariant #1:
every public ``run_*`` takes the config first and nothing else it needs)."""

from __future__ import annotations

from dataclasses import dataclass

from ..chirp import ChirpEngine, ChirpResult
from ..config.schema import RadarConfig
from .statistical import StatResult, run_statistical
from .timedomain import TimeResult, run_time


@dataclass
class RadarResult:
    cfg: RadarConfig
    chirp: ChirpResult | None
    stat: StatResult
    time: TimeResult | None


def run_radar(cfg: RadarConfig) -> RadarResult:
    """The chirp engine once (its curve goes to both engines), the
    statistical engine always, the time engine when ``sim.engine`` asks."""
    chirp = None
    if cfg.lo.engine != "ideal":
        n = cfg.time_chirps() if cfg.sim.engine != "statistical" else min(3, cfg.chirp.n_chirps)
        chirp = ChirpEngine(cfg).run(noise=False, n_chirps=n)
    stat = run_statistical(cfg, chirp)
    time = run_time(cfg, chirp) if cfg.sim.engine in ("time", "both") else None
    return RadarResult(cfg, chirp, stat, time)


__all__ = ["run_radar", "run_statistical", "run_time", "RadarResult", "StatResult", "TimeResult"]

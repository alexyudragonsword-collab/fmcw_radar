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
    # the time engine takes the loop's own noise-on curve when the LO is the vendored loop (run_time's default);
    # the deterministic curve above is the statistical engine's (settling, mismatch, the undithered pattern)
    live = chirp is not None and chirp.engine == "event" and cfg.lo.profile is None
    time = run_time(cfg, None if live else chirp) if cfg.sim.engine in ("time", "both") else None
    return RadarResult(cfg, chirp, stat, time)


__all__ = ["run_radar", "run_statistical", "run_time", "RadarResult", "StatResult", "TimeResult"]

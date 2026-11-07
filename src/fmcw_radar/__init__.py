"""fmcw_radar: behavioural simulation of a 60 GHz wideband FMCW radar.

The one config (``fmcw_radar.config.RadarConfig``) is the only truth
(invariant #1); ``fmcw_radar.engine.run_radar`` takes it and returns the
statistical result (the main engine, invariant #3) and, when asked, the
time-domain cross-check.  The LO's phase noise reaches the beat signal only
through range correlation (``fmcw_radar.phase_noise``, invariant #2) and the
chirp's frequency error only from the vendored ADPLL loop
(``fmcw_radar.chirp``, invariant #4).
"""

__version__ = "0.2.1"

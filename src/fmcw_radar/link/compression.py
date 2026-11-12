"""Receiver compression: one memoryless envelope limiter per stage (ROADMAP P1 #4).

A receiver has two input compression points (cairn/frontend-sources.md):
the stages ahead of the IF high-pass (the LNA, the mixer, the first IF
amplifier: ``p1db_oob_dbm``, what the TX leakage meets, since its beat lies
below the high-pass corner) and the IF stages after it (``p1db_inband``,
what the echo and the ADC drive meet).  Each is modelled as a Rapp limiter
on the complex beat envelope -- for the first stage that *is* the RF
envelope the LNA sees -- whose 1 dB point is the stage's::

    F(A) = A / (1 + (A / A_sat)^(2p))^(1 / 2p),   A_1dB = A_sat (10^(p/10) - 1)^(1 / 2p)

``p`` is the knee's smoothness (a placeholder, ``rx_rapp_p``).  Which 1 dB
point the radar chip's datasheet means for its "out of band" figure is not
stated beyond the test signal (a 10 kHz tone below the high-pass corner);
this library reads it as the stage's own, the tone's compression.  Read as
the blocker level that takes 1 dB off the in-band gain, the same figure
would put the stage's own point 2.7 dB higher (p = 2), and every effect
below would be weaker.

A weak signal riding with a strong one (the echo with the leakage) sees,
at its own frequency, the mean of ``(F'(B) + F(B) / B) / 2`` over the
strong signal's envelope ``B``, and an image mirrored about the strong
signal's frequency at ``(F'(B) - F(B) / B) / 2`` (the in-phase part of a
small perturbation sees the slope, the quadrature part the chord).  White
noise at the same input is a weak signal at every frequency and gets both
halves: ``(F'^2 + (F/B)^2) / 2`` of its power.  The signal-to-noise ratio
therefore loses less than the signal does: up to 3 dB for a hard limiter
(F' = 0).  The strong signal itself keeps ``mean(F(B)^2) / mean(B^2)`` of
its power.  ``tests/test_compression.py`` holds these against the limiter
applied to synthesised samples.
"""

from __future__ import annotations

import math

import numpy as np


def rapp_saturation(a1: float, p: float) -> float:
    """The saturation amplitude of a Rapp limiter whose input 1 dB compression amplitude is ``a1``."""
    return a1 / (10.0 ** (p / 10.0) - 1.0) ** (1.0 / (2.0 * p))


def rapp(x: np.ndarray, a1: float, p: float) -> np.ndarray:
    """The limiter on a complex envelope: the phase is kept, the amplitude compressed (AM/AM only)."""
    a_sat = rapp_saturation(a1, p)
    u = (np.abs(x) / a_sat) ** (2.0 * p)
    return x * (1.0 + u) ** (-1.0 / (2.0 * p))


def small_signal(env: np.ndarray, a1: float, p: float, weights: np.ndarray | None = None) -> dict:
    """What the limiter does to a weak signal and to white noise riding with a
    strong signal of envelope ``env`` (one value per sample of the window the
    weak signal is read over; ``weights`` the window, amplitude weights for
    the signal, their squares for the noise).  Returns, in dB: ``signal`` (its
    amplitude at its own frequency), ``image`` (the mirror's amplitude, an
    upper bound when the strong signal is not one tone), ``noise`` (the
    noise's power), ``snr`` (signal less noise), and ``strong`` (the strong
    signal's own power ratio)."""
    env = np.asarray(env, dtype=float)
    w = np.ones_like(env) if weights is None else np.asarray(weights, dtype=float)
    a_sat = rapp_saturation(a1, p)
    u = (env / a_sat) ** (2.0 * p)
    g = (1.0 + u) ** (-1.0 / (2.0 * p))                     # F(B) / B, the chord
    d = (1.0 + u) ** (-1.0 / (2.0 * p) - 1.0)               # F'(B), the slope
    sig = float(np.sum(w * (d + g) / 2.0) / np.sum(w))
    img = float(np.sum(w * np.abs(d - g) / 2.0) / np.sum(w))
    noi = float(np.sum(w * w * (d * d + g * g) / 2.0) / np.sum(w * w))
    strong = float(np.sum((g * env) ** 2) / max(float(np.sum(env ** 2)), 1e-300))
    db20 = lambda v: 20.0 * math.log10(max(v, 1e-300))      # noqa: E731
    db10 = lambda v: 10.0 * math.log10(max(v, 1e-300))      # noqa: E731
    return {"signal": db20(sig), "image": db20(img), "noise": db10(noi), "snr": db20(sig) - db10(noi), "strong": db10(strong)}


__all__ = ["rapp", "rapp_saturation", "small_signal"]

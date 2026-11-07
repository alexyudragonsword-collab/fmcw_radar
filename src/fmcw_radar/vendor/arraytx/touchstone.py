# Vendored from array_tx@e897c159e5fc5b2e26af6336cf9f6164461ff7f5: src/arraytx/touchstone.py
# Adapted-copy policy: see src/fmcw_radar/vendor/__init__.py
"""A minimal Touchstone v1 (.sNp) reader / writer for N-port S-parameters.

Only what the coupling matrix needs: the option line (frequency unit,
``S``, ``RI`` / ``MA`` / ``DB`` format, reference impedance), comment lines,
and the per-frequency blocks.  For N >= 3 ports a block is N rows of N
complex pairs (2-port blocks use the v1 column order S11 S21 S12 S22) (Touchstone wraps rows beyond four pairs; the reader just
keeps reading numbers until it has N*N pairs, so any wrapping is fine).

The writer emits ``Hz`` and ``RI`` with ``repr`` floats so a matrix written
and read back is bit-identical — the property the ``touchstone`` coupling
source is tested against the ``analytic`` one with.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_UNITS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}


@dataclass
class Touchstone:
    freqs_hz: np.ndarray       # (F,)
    s: np.ndarray              # (F, N, N) complex
    z0: float = 50.0
    comments: tuple[str, ...] = ()

    @property
    def n_ports(self) -> int:
        return int(self.s.shape[1])


def read_touchstone(path: str | Path) -> Touchstone:
    path = Path(path)
    m = re.search(r"\.s(\d+)p$", path.name.lower())
    if not m:
        raise ValueError(f"{path}: not a .sNp file")
    n = int(m.group(1))
    unit, fmt, z0 = 1e9, "MA", 50.0
    comments: list[str] = []
    numbers: list[float] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("!", 1)[0].strip()
        if "!" in raw:
            comments.append(raw.split("!", 1)[1].strip())
        if not line:
            continue
        if line.startswith("#"):
            toks = line[1:].upper().split()
            for i, t in enumerate(toks):
                if t in _UNITS:
                    unit = _UNITS[t]
                elif t in ("RI", "MA", "DB"):
                    fmt = t
                elif t == "R" and i + 1 < len(toks):
                    z0 = float(toks[i + 1])
                elif t == "S":
                    pass
                elif re.match(r"^[-+0-9.]", t):
                    continue
                else:
                    raise ValueError(f"{path}: unsupported option {t!r} (only S-parameters)")
            continue
        numbers.extend(float(t) for t in line.split())
    per_block = 1 + 2 * n * n
    if len(numbers) % per_block:
        raise ValueError(f"{path}: {len(numbers)} numbers is not a whole number of {n}-port blocks")
    blocks = np.asarray(numbers, dtype=float).reshape(-1, per_block)
    freqs = blocks[:, 0] * unit
    a = blocks[:, 1::2].reshape(-1, n, n)
    b = blocks[:, 2::2].reshape(-1, n, n)
    if n == 2:
        # Touchstone v1 writes 2-port blocks as S11 S21 S12 S22 (column
        # order), unlike the row order used for 3+ ports
        a = a.transpose(0, 2, 1)
        b = b.transpose(0, 2, 1)
    if fmt == "RI":
        s = a + 1j * b
    elif fmt == "MA":
        s = a * np.exp(1j * np.deg2rad(b))
    else:  # DB
        s = 10.0 ** (a / 20.0) * np.exp(1j * np.deg2rad(b))
    if np.any(np.diff(freqs) <= 0):
        raise ValueError(f"{path}: frequencies must be strictly increasing")
    return Touchstone(freqs_hz=freqs, s=s.astype(complex), z0=z0, comments=tuple(comments))


def write_touchstone(path: str | Path, freqs_hz, s, *, z0: float = 50.0,
                     comments=()) -> Path:
    """Write ``s`` (F, N, N) at ``freqs_hz`` (F,) as Hz / RI with repr floats."""
    path = Path(path)
    freqs = np.asarray(freqs_hz, dtype=float)
    s = np.asarray(s, dtype=complex)
    n = s.shape[1]
    if s.shape != (freqs.size, n, n):
        raise ValueError("s must be (F, N, N)")
    if not path.name.lower().endswith(f".s{n}p"):
        raise ValueError(f"file name must end in .s{n}p for {n} ports")
    lines = [f"! {c}" for c in comments]
    lines.append(f"# Hz S RI R {z0:g}")
    for fi, f in enumerate(freqs):
        for row in range(n):
            vals = []
            for col in range(n):
                # 2-port files are column-ordered (S11 S21 S12 S22), see reader
                v = s[fi, col, row] if n == 2 else s[fi, row, col]
                vals.append(f"{float(v.real)!r} {float(v.imag)!r}")
            fr = repr(float(f))
            head = f"{fr} " if row == 0 else " " * (len(fr) + 1)
            lines.append(head + "  ".join(vals))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

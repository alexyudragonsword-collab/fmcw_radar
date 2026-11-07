# Vendored from array_tx@e897c159e5fc5b2e26af6336cf9f6164461ff7f5: src/arraytx/coupling.py
# Adapted-copy policy: see src/fmcw_radar/vendor/__init__.py
"""Mutual coupling as a complex N x N matrix that enters the CHAIN
(invariant 3), from one of three sources that all produce the same object
and all go through the one ``apply_coupling``.

Model (milestone 1: linear leakage)
-----------------------------------
radiated_k(f) = y_k(f) + sum_{j != k} S_kj(f) * y_j(f)

* ``y_j`` is element j's PA forward output (conducted port).
* ``S_kj(f)`` is the coupled transfer from port j to port k at RF frequency
  f; the diagonal (return loss) is carried but NOT applied — a load
  mismatch needs a PA model with load dependence (ROADMAP A2).
* S == 0 (all off-diagonal exactly zero) returns the input array object
  itself, so one element with no coupling is bit-identical to polar_tx.

Sources
-------
``analytic``   flat c1 (adjacent), c2 = c1 * ratio (next-adjacent), 0 beyond.
``survey``     c1 magnitude from the published lambda/2 patch-array values,
               phase linear in frequency = the free-space delay over the
               distance between the two elements (source: assumed; the
               papers do not publish the phase).
``touchstone`` an N-port .sNp file, interpolated onto the baseband grid.

All three put the matrix on a frequency grid and ``CouplingMatrix.at``
interpolates it (real and imaginary parts separately, ends held) onto the
burst's RF grid f0 + fftfreq.  The analytic source uses a two-point grid so
that writing it to .sNp and reading it back is bit-identical.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import C0, ArrayGeometry
from .touchstone import read_touchstone, write_touchstone

TWO_PI = 2.0 * np.pi


@dataclass
class CouplingMatrix:
    freqs_hz: np.ndarray        # (F,) RF, increasing
    s: np.ndarray               # (F, n, n) complex
    source: str

    def __post_init__(self):
        self.freqs_hz = np.asarray(self.freqs_hz, dtype=float)
        self.s = np.asarray(self.s, dtype=complex)
        if self.s.ndim != 3 or self.s.shape[1] != self.s.shape[2] or self.s.shape[0] != self.freqs_hz.size:
            raise ValueError(f"s must be (F, n, n) with F = len(freqs); got {self.s.shape}")
        if self.freqs_hz.size > 1 and np.any(np.diff(self.freqs_hz) <= 0):
            raise ValueError("freqs_hz must be strictly increasing")

    @property
    def n(self) -> int:
        return int(self.s.shape[1])

    def offdiag(self) -> np.ndarray:
        m = self.s.copy()
        idx = np.arange(self.n)
        m[:, idx, idx] = 0.0
        return m

    @property
    def is_zero(self) -> bool:
        return bool(np.all(self.offdiag() == 0.0))

    def max_gain(self) -> float:
        """Largest singular value of the OFF-DIAGONAL matrix over the grid: the
        most any drive vector can be amplified by the leakage alone.  A
        passive network has |S| <= 1 whole; a leakage-only matrix above 1
        means the neighbours add up to more than the element itself -- a
        sign the phases are not physical (all farther neighbours in phase)."""
        od = self.offdiag()
        return float(max(np.linalg.svd(od[i], compute_uv=False)[0] for i in range(od.shape[0]))) if self.n > 1 else 0.0

    def max_offdiag_db(self) -> float:
        mx = float(np.abs(self.offdiag()).max()) if self.n > 1 else 0.0
        return -np.inf if mx == 0.0 else 20.0 * np.log10(mx)

    def at(self, f_rf) -> np.ndarray:
        """Interpolate onto RF frequencies ``f_rf`` (any shape); ends held."""
        f_rf = np.asarray(f_rf, dtype=float)
        if self.freqs_hz.size == 1:
            return np.broadcast_to(self.s[0], f_rf.shape + self.s.shape[1:]).copy()
        out = np.zeros(f_rf.shape + self.s.shape[1:], dtype=complex)
        for k, j in self.nonzero_pairs():
            out[..., k, j] = self.at_pair(k, j, f_rf)
        return out

    def nonzero_pairs(self) -> list[tuple[int, int]]:
        """(k, j) pairs whose S_kj is not identically zero over the grid, in
        row-major order.  A zero column interpolates to exactly 0, so the
        pairs left out contribute nothing; skipping them is what keeps the
        neighbour-only matrices O(n) instead of O(n^2) at 64+ elements."""
        nz = np.any(self.s != 0.0, axis=0)
        return [(int(k), int(j)) for k, j in zip(*np.nonzero(nz))]

    def at_pair(self, k: int, j: int, f_rf) -> np.ndarray:
        """S_kj interpolated onto ``f_rf`` (real and imaginary parts
        separately, ends held) -- the one interpolation every path uses."""
        f_rf = np.asarray(f_rf, dtype=float)
        if self.freqs_hz.size == 1:
            return np.full(f_rf.shape, self.s[0, k, j], dtype=complex)
        re = np.interp(f_rf, self.freqs_hz, self.s[:, k, j].real)
        im = np.interp(f_rf, self.freqs_hz, self.s[:, k, j].imag)
        return re + 1j * im

    def scaled(self, db: float) -> "CouplingMatrix":
        """Off-diagonal terms scaled by ``db`` (``-inf`` -> zero coupling)."""
        if db == 0.0:
            return self
        g = 0.0 if db == -np.inf else 10.0 ** (db / 20.0)
        idx = np.arange(self.n)
        s = self.offdiag() * g
        s[:, idx, idx] = self.s[:, idx, idx]
        return CouplingMatrix(self.freqs_hz, s, f"{self.source}*{db:+g}dB")


# ------------------------------------------------------------- the sources
def _neighbour_classes(geom):
    """(k, j, rel) for every coupled pair: ``rel`` names the class --
    'x1' adjacent along the row, 'x2' next-adjacent along the row, 'y1'
    adjacent across rows, 'y2' two rows away, 'd1' the diagonal neighbour.
    Along one row only x1 / x2 occur: the milestone-1 shape, same order."""
    dix, diy = geom.grid_offsets()
    out = []
    for k in range(geom.n):
        for j in range(geom.n):
            dx, dy = int(dix[k, j]), int(diy[k, j])
            if dy == 0 and dx == 1:
                out.append((k, j, "x1"))
            elif dy == 0 and dx == 2:
                out.append((k, j, "x2"))
            elif dx == 0 and dy == 1:
                out.append((k, j, "y1"))
            elif dx == 0 and dy == 2:
                out.append((k, j, "y2"))
            elif dx == 1 and dy == 1:
                out.append((k, j, "d1"))
    return out


def _class_gains(c2_rel_db: float, c1y_rel_db: float = 0.0, c_diag_rel_db: float = -6.0) -> dict[str, float]:
    """Magnitude of each class relative to c1 (linear).  'x1' is exactly 1."""
    r2 = 10.0 ** (c2_rel_db / 20.0)
    ry = 10.0 ** (c1y_rel_db / 20.0)
    rd = 10.0 ** (c_diag_rel_db / 20.0)
    return {"x1": 1.0, "x2": r2, "y1": ry, "y2": ry * r2, "d1": rd}


def _extra_phase_rad(geom, k: int, j: int, f0: float, phase_from_distance: bool) -> float:
    """Phase a farther neighbour has beyond the adjacent one: the free-space
    electrical length of the extra distance, 2 pi f0 (d_kj - d_x1) / c0.
    Exactly 0.0 for the adjacent class along the row, and for every class
    when the switch is off (the milestone-1 reading: all classes at
    c1_deg)."""
    if not phase_from_distance:
        return 0.0
    extra = geom.pair_distance_m(k, j) - geom.spacing_m
    return 0.0 if extra == 0.0 else TWO_PI * f0 * extra / C0


def _neighbour_shape(geom, c1: complex, g: dict[str, float], *, f0: float | None = None,
                     phase_from_distance: bool = False) -> np.ndarray:
    """The frequency-flat matrix: c1 on the adjacent class, c1 x ``g[rel]``
    (from ``_class_gains``) on the others."""
    m = np.zeros((geom.n, geom.n), dtype=complex)
    for k, j, rel in _neighbour_classes(geom):
        v = c1 if rel == "x1" else c1 * g[rel]
        if rel != "x1" and phase_from_distance:
            v = v * np.exp(1j * _extra_phase_rad(geom, k, j, f0, True))
        m[k, j] = v
    return m


def analytic_matrix(geom, c1_db: float, c1_deg: float, c2_rel_db: float,
                    f_lo: float, f_hi: float, *, c1y_rel_db: float = 0.0, c_diag_rel_db: float = -6.0,
                    phase_from_distance: bool = False) -> CouplingMatrix:
    """``geom`` is an ArrayGeometry (an int is read as a one-row array of that size)."""
    geom = _geom(geom, f_lo, f_hi)
    c1 = 10.0 ** (c1_db / 20.0) * np.exp(1j * np.deg2rad(c1_deg))
    g = _class_gains(c2_rel_db, c1y_rel_db, c_diag_rel_db)
    m = _neighbour_shape(geom, c1, g, f0=geom.f0_hz, phase_from_distance=phase_from_distance)
    return CouplingMatrix(np.array([f_lo, f_hi]), np.stack([m, m]), "analytic")


def survey_matrix(geom, c1_db: float, c1_deg_at_f0: float, c2_rel_db: float,
                  f0: float, spacing_m: float, f_grid, *, path_delay: bool = True,
                  c1y_rel_db: float = 0.0, c_diag_rel_db: float = -6.0,
                  phase_from_distance: bool = False) -> CouplingMatrix:
    """Published-magnitude coupling with a linear-phase (pure delay) frequency
    dependence: phi_kj(f) = phi0_kj - 2 pi (f - f0) * d_kj / c0, d_kj the
    centre-to-centre distance (|k - j| d along a row).  With
    ``phase_from_distance`` phi0 of a farther class carries the electrical
    length beyond one pitch (so the farther neighbours do not all add in
    phase at f0: on a 2-D grid they would sum past 1 otherwise).
    ``spacing_m`` is kept for the one-row callers; an ArrayGeometry carries
    its own pitches."""
    f_grid = np.asarray(f_grid, dtype=float)
    geom = _geom(geom, f0, f0, spacing_m)
    a1 = 10.0 ** (c1_db / 20.0)
    g = _class_gains(c2_rel_db, c1y_rel_db, c_diag_rel_db)
    s = np.zeros((f_grid.size, geom.n, geom.n), dtype=complex)
    for k, j, rel in _neighbour_classes(geom):
        mag = a1 if rel == "x1" else a1 * g[rel]
        tau = (geom.pair_distance_m(k, j) / C0) if path_delay else 0.0
        ph = np.deg2rad(c1_deg_at_f0) - TWO_PI * (f_grid - f0) * tau
        if rel != "x1" and phase_from_distance:
            ph = ph + _extra_phase_rad(geom, k, j, f0, True)
        s[:, k, j] = mag * np.exp(1j * ph)
    return CouplingMatrix(f_grid, s, "survey")


def _geom(geom, f_lo, f_hi, spacing_m: float | None = None):
    """Accept an ArrayGeometry, or an int (one row) for the older callers."""
    if isinstance(geom, (int, np.integer)):
        f0 = 0.5 * (f_lo + f_hi)
        lam = C0 / f0
        pitch = (spacing_m / lam) if spacing_m else 0.5
        return ArrayGeometry(int(geom), 1, pitch, pitch, f0)
    return geom


def touchstone_matrix(path: str) -> CouplingMatrix:
    ts = read_touchstone(path)
    return CouplingMatrix(ts.freqs_hz, ts.s, f"touchstone:{path}")


def write_matrix_touchstone(path: str, m: CouplingMatrix, comments=()) -> str:
    write_touchstone(path, m.freqs_hz, m.s, comments=tuple(comments) + (f"arraytx coupling source: {m.source}",))
    return str(path)


def build_coupling(cfg: ArrayConfig, geom: ArrayGeometry, fs: float) -> CouplingMatrix:
    """The config's coupling matrix on a grid covering the burst (f0 +- fs/2),
    scaled by ``coupling.scale_db``.  One entry point for all three sources."""
    c = cfg.coupling
    f0 = geom.f0_hz
    f_lo, f_hi = f0 - fs / 2.0, f0 + fs / 2.0
    if c.source == "analytic":
        a = c.analytic
        m = analytic_matrix(geom, a.c1_db, a.c1_deg, a.c2_rel_db, f_lo, f_hi,
                            c1y_rel_db=a.c1y_rel_db, c_diag_rel_db=a.c_diag_rel_db,
                            phase_from_distance=a.phase_from_distance)
    elif c.source == "survey":
        s = c.survey
        grid = np.linspace(f_lo, f_hi, 257)
        m = survey_matrix(geom, s.c1_db, s.c1_deg_at_f0, s.c2_rel_db, f0,
                          geom.spacing_m, grid, path_delay=s.path_delay_from_spacing,
                          c1y_rel_db=s.c1y_rel_db, c_diag_rel_db=s.c_diag_rel_db,
                          phase_from_distance=s.phase_from_distance)
    elif c.source == "touchstone":
        m = touchstone_matrix(c.touchstone.path)
        if m.n != geom.n:
            raise ValueError(f"touchstone has {m.n} ports, array has {geom.n} elements")
    else:
        raise ValueError(f"unknown coupling source {c.source!r}")
    m = m.scaled(float(c.scale_db))
    g = m.max_gain()
    if g > 1.0:
        raise ValueError(f"coupling matrix is not passive: the leakage alone has gain {g:.2f} > 1 (source {m.source}, "
                         f"{geom.n_x} x {geom.n_y}); lower c1_db / scale_db, or do not put every neighbour class at the "
                         f"same phase (phase_from_distance)")
    return m


# ------------------------------------------------------------ the one path
def apply_coupling(ys, m: CouplingMatrix, fs: float, f0: float) -> np.ndarray:
    """radiated = ys + S_offdiag(f) @ ys, in the frequency domain.

    ``ys`` is (n, N).  When the matrix has no coupling at all the INPUT
    OBJECT is returned (no FFT round trip): S = 0 is bit-identical to no
    array.  The diagonal is never applied (see the module docstring).
    """
    ys = np.asarray(ys)
    if ys.ndim != 2 or ys.shape[0] != m.n:
        raise ValueError(f"ys must be (n={m.n}, N), got {ys.shape}")
    if m.is_zero:
        return ys
    Y = np.fft.fft(ys, axis=1)                                  # (n, N)
    f_rf = f0 + np.fft.fftfreq(ys.shape[1], 1.0 / fs)
    # leak_k(f) = sum_j S_kj(f) Y_j(f), accumulated pair by pair in j order
    # over the non-zero off-diagonal pairs only: the same sum as a dense
    # (N, n, n) @ Y, term for term (a zero term adds exactly 0), without
    # the n^2 x N array that would be 9 GB at 64 elements and 8 symbols.
    # Real and imaginary parts are accumulated separately, which is what
    # numpy's complex einsum does; the dense form this replaced is then
    # reproduced bit for bit (a complex multiply-then-add differs in the
    # last bit).  Checked by tools/fingerprint.py, not assumed.
    leak_re = np.zeros(Y.shape)
    leak_im = np.zeros(Y.shape)
    for k, j in m.nonzero_pairs():
        if k == j:
            continue
        skj = m.at_pair(k, j, f_rf)
        ar, ai, br, bi = skj.real, skj.imag, Y[j].real, Y[j].imag
        leak_re[k] += ar * br - ai * bi
        leak_im[k] += ar * bi + ai * br
    return np.fft.ifft(Y + (leak_re + 1j * leak_im), axis=1)

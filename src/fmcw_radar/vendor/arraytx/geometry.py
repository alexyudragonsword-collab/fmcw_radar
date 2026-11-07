# Vendored from array_tx@e897c159e5fc5b2e26af6336cf9f6164461ff7f5: src/arraytx/geometry.py
# Adapted-copy policy: see src/fmcw_radar/vendor/__init__.py
"""Array geometry: a uniform rectangular grid in the x-y plane (a single row
is the linear array of milestone 1), phase centre at the middle, so a
far-field observation at any angle carries no net delay.

Element order is ROW-MAJOR: k = iy * n_x + ix, the first row first.  That is
what makes a one-row planar array the linear array bit for bit, and what
lets an extra row be added without moving the existing elements' seed
streams (``seeds.SeedTree`` spawns per index).  Touchstone ports follow the
same order.

Directions are (theta, phi) with theta from broadside (the z axis) and phi
the azimuth of the scan PLANE measured from the x axis (the row direction):
u = (sin theta cos phi, sin theta sin phi, cos theta), tau_k = (x_k u_x +
y_k u_y) / c0.  The plane is a property of the geometry (``plane_phi_deg``),
so every function that takes a theta -- steering, far field, array factor,
sidelobe search -- works in that plane without carrying a second angle; a
cut in another plane is ``with_plane(phi)``.

The element pattern is an input, not a computation (ROADMAP D: no EM here):
``isotropic`` (source: assumed) or ``cos`` (a cos(theta) element factor,
the textbook patch-like envelope; source: assumed).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

C0 = 299_792_458.0   # m/s, exact by definition of the metre


@dataclass(frozen=True)
class ArrayGeometry:
    n_x: int                              # elements per row (along x)
    n_y: int = 1                          # rows (along y)
    spacing_lambda: float = 0.5           # x pitch in carrier wavelengths
    spacing_y_lambda: float = 0.5         # y pitch in carrier wavelengths
    f0_hz: float = 28e9
    element_pattern: str = "isotropic"
    plane_phi_deg: float = 0.0            # azimuth of the scan / observation plane

    def __post_init__(self):
        if self.n_x < 1 or self.n_y < 1:
            raise ValueError("n_x and n_y must be >= 1")
        if self.element_pattern not in ("isotropic", "cos"):
            raise ValueError(f"unknown element pattern {self.element_pattern!r}")

    # ------------------------------------------------------------ shape
    @property
    def n(self) -> int:
        return self.n_x * self.n_y

    @property
    def is_linear(self) -> bool:
        return self.n_y == 1

    @property
    def wavelength_m(self) -> float:
        return C0 / self.f0_hz

    @property
    def spacing_m(self) -> float:
        return self.spacing_lambda * self.wavelength_m

    @property
    def spacing_y_m(self) -> float:
        return self.spacing_y_lambda * self.wavelength_m

    @property
    def ix(self) -> np.ndarray:
        """Column index of each element (row-major order)."""
        return np.arange(self.n) % self.n_x

    @property
    def iy(self) -> np.ndarray:
        """Row index of each element (row-major order)."""
        return np.arange(self.n) // self.n_x

    @property
    def x_m(self) -> np.ndarray:
        """x of each element, centred: (ix - (n_x-1)/2) * dx.  A single
        element, or a single column, sits at exactly 0.0."""
        return (self.ix.astype(float) - (self.n_x - 1) / 2.0) * self.spacing_m

    @property
    def y_m(self) -> np.ndarray:
        return (self.iy.astype(float) - (self.n_y - 1) / 2.0) * self.spacing_y_m

    @property
    def positions_m(self) -> np.ndarray:
        """The x coordinates (the linear array's positions; kept for the
        callers and tests written for one row)."""
        return self.x_m

    # ------------------------------------------------------------ plane
    @property
    def plane_unit(self) -> tuple[float, float]:
        """(cos phi, sin phi) of the scan plane; exactly (1.0, 0.0) at phi = 0."""
        if self.plane_phi_deg == 0.0:
            return 1.0, 0.0
        p = np.deg2rad(self.plane_phi_deg)
        return float(np.cos(p)), float(np.sin(p))

    @property
    def plane_m(self) -> np.ndarray:
        """Each element's coordinate along the scan plane's in-plane axis,
        x cos phi + y sin phi -- the 'position' a 1-D array factor sees."""
        cx, sy = self.plane_unit
        if sy == 0.0:
            return self.x_m if cx == 1.0 else self.x_m * cx
        return self.x_m * cx + self.y_m * sy

    def with_plane(self, phi_deg: float) -> "ArrayGeometry":
        return replace(self, plane_phi_deg=float(phi_deg))

    @property
    def aperture_m(self) -> float:
        """Extent along the scan plane plus one pitch (n d for a row): the
        length the 0.886 lambda / L beamwidth rule uses."""
        p = self.plane_m
        cx, sy = self.plane_unit
        pitch = abs(self.spacing_m * cx) + abs(self.spacing_y_m * sy)
        return float(p.max() - p.min()) + pitch

    def delays_s(self, theta_deg: float) -> np.ndarray:
        """Arrival-time ADVANCE of element k's wave at a far-field observer at
        theta in the scan plane: tau_k = (x_k u_x + y_k u_y) / c0 with
        u = sin(theta) (cos phi, sin phi).  Exactly 0.0 at broadside."""
        s = np.sin(np.deg2rad(theta_deg))
        if s == 0.0:
            return np.zeros(self.n)
        cx, sy = self.plane_unit
        if sy == 0.0 and cx == 1.0:
            return self.x_m * s / C0            # the one-row expression, bit for bit
        return (self.x_m * (s * cx) + self.y_m * (s * sy)) / C0

    def element_gain(self, theta_deg: float) -> float:
        if self.element_pattern == "isotropic":
            return 1.0
        return float(max(np.cos(np.deg2rad(theta_deg)), 0.0))

    # ------------------------------------------------------------ pairs
    def grid_offsets(self) -> tuple[np.ndarray, np.ndarray]:
        """(|dix|, |diy|) between every pair, (n, n) each: the neighbour
        classes the analytic / survey coupling matrices are built from."""
        dix = np.abs(self.ix[:, None] - self.ix[None, :])
        diy = np.abs(self.iy[:, None] - self.iy[None, :])
        return dix, diy

    def pair_distance_m(self, k: int, j: int) -> float:
        """Centre-to-centre distance; along one row it is |dix| dx exactly
        (no hypot round-off), so the one-row matrices do not move."""
        dx = abs(self.ix[k] - self.ix[j]) * self.spacing_m
        dy = abs(self.iy[k] - self.iy[j]) * self.spacing_y_m
        if dy == 0.0:
            return float(dx)
        if dx == 0.0:
            return float(dy)
        return float(np.hypot(dx, dy))


def LinearArray(n: int, spacing_lambda: float, f0_hz: float,       # noqa: N802 (kept as a class-like name)
                element_pattern: str = "isotropic") -> ArrayGeometry:
    """The milestone-1 constructor: one row of ``n`` elements."""
    return ArrayGeometry(n, 1, spacing_lambda, spacing_lambda, f0_hz, element_pattern)

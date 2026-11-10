"""TDM-MIMO virtual array and the angle estimate (milestone 2).

``n_tx`` transmitters take the chirps in turn, ``n_rx`` receivers sample
every one; the pair (TX m, RX n) sees the target through the path
``x_tx[m] + x_rx[n]`` -- the virtual element at that position.  With the TX
pitch equal to ``n_rx`` RX pitches the virtual positions are a filled
uniform line of ``n_tx x n_rx`` elements at the RX pitch, the aperture a
single-TX array would need ``n_tx`` times the receivers for.

The angle is read by digital beamforming: at the target's range-Doppler
cell the virtual snapshot ``s_k`` is weighted, windowed and transformed
onto a grid of ``u = sin(theta)`` (a DFT on the element positions, so any
virtual layout works; the filled line is the plain zero-padded FFT), and
the peak's ``u`` is the estimate.  Three things sit on it:

* **TDM Doppler phase**: the TX blocks are ``PRI`` apart, so the snapshot
  of TX m carries ``exp(j 2 pi f_d m PRI)`` on top of its path phase: a
  moving target reads at the wrong angle unless the Doppler, estimated
  from each TX's own Doppler FFT, is taken out (``tdm_doppler_compensation``).
  Uncompensated, 2 m/s on the default config is 0.5 rad between the two
  TX blocks.
* **Mutual coupling of the receive array**: through array_tx's
  ``CouplingMatrix`` (three sources, same object), applied as the array
  radiates it in reverse -- received_k = a_k + sum_j S_kj a_j at the carrier.
  Uncalibrated it biases the estimate and raises the sidelobes; with the
  matrix known (``coupling.calibrated``) its inverse is applied to every TX
  block of the snapshot first.  The matrix is the RX array's own
  (``n_rx`` ports); the transmitters radiate one at a time under TDM, so
  their coupling only loses power into the idle TX's termination
  (not modelled, like array_tx's diagonal).
* **The sweep**: over a 4 GHz sweep the array manifold's phase slope moves
  by B / f_c = 6.7 %, an order of magnitude more than FR2's 400 MHz
  (array_tx's beam squint, ``squint_analytic_deg``).  For the receive DBF it
  shows as a per-element beat-frequency offset ``S x_k sin(theta) / c``
  (a fraction of a range bin at the aperture's edge) whose window response
  tapers the snapshot; the range FFT's phase at its peak is the
  sweep-centre phase, so the estimate is not biased by it.  The numbers a
  phase-shifter-steered transmit beam would squint by over this sweep are
  reported for reference.

Accuracy: the Cramer-Rao bound of a single-snapshot deterministic source on
these positions, ``var(u) = 6 lambda^2 / (4 pi^2 d^2 N (N^2 - 1) SNR)`` for
a filled line (the general sum of squared positions otherwise), with the
per-element cell SNR from the link budget.  The estimator here is not on
that bound and ``angle_error_budget`` says by how much and why: the taper
across the elements (Hann on 8: 1.52 in sigma), the cell's scalloping, the
element pattern, and the Doppler estimate of the TDM compensation (a
percent).  Resolution: the virtual
aperture's ``0.886 lambda / (L cos theta)``, measured on the array factor
through array_tx's ``beamwidth_3db_deg`` for the filled line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config.schema import C0, RadarConfig
from .processing.windows import window
from .vendor.arraytx.beam import beamwidth_3db_deg, squint_analytic_deg
from .vendor.arraytx.coupling import CouplingMatrix, analytic_matrix, survey_matrix, touchstone_matrix
from .vendor.arraytx.geometry import ArrayGeometry

TWOPI = 2.0 * np.pi


def rx_coupling_matrix(cfg: RadarConfig, geom: ArrayGeometry) -> CouplingMatrix | None:
    """The receive array's coupling matrix from the config's source (None for
    ``none``), on a grid covering the sweep."""
    c = cfg.mimo.coupling
    if c.source == "none" or geom.n == 1:
        return None
    f0 = cfg.band.center_hz
    f_lo, f_hi = cfg.band.start_hz, cfg.band.stop_hz
    c1_db, _ = cfg.coupling_c1()
    if c.source == "analytic":
        return analytic_matrix(geom, c1_db, c.c1_deg, c.c2_rel_db, f_lo, f_hi)
    if c.source == "survey":
        grid = np.linspace(f_lo, f_hi, 257)
        return survey_matrix(geom, c1_db, c.c1_deg, c.c2_rel_db, f0, geom.spacing_m, grid, path_delay=c.path_delay)
    from .lo import resolve_data_file

    m = touchstone_matrix(str(resolve_data_file(c.touchstone)))
    if m.n != geom.n:
        raise ValueError(f"mimo.coupling.touchstone has {m.n} ports, the receive array {geom.n} elements")
    return m


@dataclass
class VirtualArray:
    """The config's MIMO geometry and everything the angle estimate needs."""

    cfg: RadarConfig

    def __post_init__(self):
        m = self.cfg.mimo
        f0 = self.cfg.band.center_hz
        self.f0_hz = f0
        self.wavelength_m = C0 / f0
        self.rx = ArrayGeometry(m.n_rx, 1, m.rx_spacing_lambda, m.rx_spacing_lambda, f0, m.element_pattern)
        self.tx = ArrayGeometry(m.n_tx, 1, m.tx_pitch_lambda, m.tx_pitch_lambda, f0, "isotropic")
        self.x_v = (self.tx.x_m[:, None] + self.rx.x_m[None, :]).ravel()       # virtual positions, TX-major
        self.filled = m.tx_spacing_lambda is None or abs(m.tx_pitch_lambda - m.n_rx * m.rx_spacing_lambda) < 1e-12
        self.virtual = (ArrayGeometry(m.n_virtual, 1, m.rx_spacing_lambda, m.rx_spacing_lambda, f0, m.element_pattern)
                        if self.filled else None)
        self.coupling = rx_coupling_matrix(self.cfg, self.rx)
        eye = np.eye(m.n_rx, dtype=complex)
        if self.coupling is None:
            self.c_rx = eye
        else:
            s = self.coupling.at(np.array([f0]))[0]
            self.c_rx = eye + (s - np.diag(np.diag(s)))                          # received = a + S_offdiag a
        self.c_rx_inv = np.linalg.inv(self.c_rx)

    # ------------------------------------------------------------ geometry
    @property
    def n(self) -> int:
        return self.x_v.size

    @property
    def aperture_m(self) -> float:
        """Virtual extent plus one RX pitch (the length the 0.886 lambda / L rule uses)."""
        return float(self.x_v.max() - self.x_v.min()) + self.rx.spacing_m

    def element_gain(self, theta_deg: float) -> float:
        return self.rx.element_gain(theta_deg)

    def manifold(self, theta_deg: float, f_hz: float | None = None) -> np.ndarray:
        """``exp(j 2 pi f x_v sin(theta) / c)`` on the virtual positions."""
        f = self.f0_hz if f_hz is None else f_hz
        return np.exp(1j * TWOPI * f * self.x_v * math.sin(math.radians(theta_deg)) / C0)

    def rx_manifold(self, theta_deg: float, coupled: bool = True) -> np.ndarray:
        a = np.exp(1j * TWOPI * self.f0_hz * self.rx.x_m * math.sin(math.radians(theta_deg)) / C0)
        return self.c_rx @ a if coupled else a

    def tx_manifold(self, theta_deg: float) -> np.ndarray:
        return np.exp(1j * TWOPI * self.f0_hz * self.tx.x_m * math.sin(math.radians(theta_deg)) / C0)

    def snapshot(self, theta_deg: float, doppler_hz: float = 0.0, coupled: bool = True) -> np.ndarray:
        """The noiseless virtual snapshot (TX-major, ``n_tx x n_rx``) the time
        engine would deliver at the target's cell: TX path phase, coupled RX
        path phase, and the TDM Doppler phase ``exp(j 2 pi f_d m PRI)`` of
        TX block m."""
        m = self.cfg.mimo
        tdm = np.exp(1j * TWOPI * doppler_hz * np.arange(m.n_tx) * self.cfg.chirp.pri_s)
        s = (self.tx_manifold(theta_deg) * tdm)[:, None] * self.rx_manifold(theta_deg, coupled)[None, :]
        return s.ravel() * self.element_gain(theta_deg)

    # ----------------------------------------------------------- estimate
    def prepare(self, snapshot: np.ndarray, doppler_hz: float | None) -> np.ndarray:
        """What the estimator does before the beamformer: the TDM Doppler
        compensation with the (estimated) Doppler and, when the config says
        the matrix is calibrated, its inverse on every TX block."""
        m = self.cfg.mimo
        s = np.asarray(snapshot, dtype=complex).reshape(m.n_tx, m.n_rx).copy()
        if m.tdm_doppler_compensation and doppler_hz is not None:
            s *= np.exp(-1j * TWOPI * doppler_hz * np.arange(m.n_tx) * self.cfg.chirp.pri_s)[:, None]
        if m.coupling.calibrated and self.coupling is not None:
            s = s @ self.c_rx_inv.T
        return s.ravel()

    def u_grid(self) -> np.ndarray:
        n_u = self.n * self.cfg.mimo.angle_pad
        return np.linspace(-1.0, 1.0, n_u, endpoint=False) + 1.0 / n_u

    def spectrum(self, snapshot: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(u, |B(u)|^2 in dB rel. its peak)``: the windowed beamformer
        output over ``u = sin(theta)``, a DFT on the positions (the FFT for a
        filled line)."""
        w = window(self.cfg.mimo.angle_window, self.n)
        w = w / w.sum()
        u = self.u_grid()
        steer = np.exp(-1j * TWOPI * self.x_v[None, :] * u[:, None] / self.wavelength_m)
        b = steer @ (w * snapshot)
        p = np.abs(b) ** 2
        return u, 10.0 * np.log10(np.maximum(p / max(p.max(), 1e-300), 1e-300))

    def estimate(self, snapshot: np.ndarray, doppler_hz: float | None = None) -> dict:
        """The angle estimate of a virtual snapshot: ``theta_deg``, ``u``, the
        spectrum, its highest sidelobe [dB] and -3 dB width in u."""
        s = self.prepare(snapshot, doppler_hz)
        u, p = self.spectrum(s)
        i = int(np.argmax(p))
        u_hat = float(u[i])
        if 0 < i < u.size - 1:
            a, b, c = p[i - 1], p[i], p[i + 1]
            den = a - 2.0 * b + c
            if den < 0.0:
                u_hat = float(u[i] + 0.5 * (a - c) / den * (u[1] - u[0]))
        u_hat = float(np.clip(u_hat, -1.0, 1.0))
        from .processing.windows import peak_sidelobe_of, width_at_level

        # half-wavelength positions make the spectrum periodic in u with the
        # grid's span, so a beam steered near u = +-1 wraps: read its sidelobe
        # with the peak rolled to the middle, where the main lobe is whole
        p_sl = p
        lattice = 2.0 * (self.x_v - self.x_v[0]) / self.wavelength_m      # a common offset is a common phase
        if np.allclose(lattice, np.round(lattice), atol=1e-9):
            p_sl = np.roll(p, u.size // 2 - i)
        return {"theta_deg": math.degrees(math.asin(u_hat)), "u": u_hat, "u_grid": u, "spectrum_db": p,
                "peak_sidelobe_db": float(peak_sidelobe_of(u, p_sl)), "width_3db_u": float(width_at_level(u, p, -3.0))}

    # ------------------------------------------------------------ metrics
    def beamwidth_deg(self, theta_deg: float) -> float:
        """Half-power width of the virtual array's beam at theta: array_tx's
        measured array factor for a filled line, the 0.886 lambda / (L cos)
        rule otherwise."""
        if self.virtual is not None and self.n > 1:
            return beamwidth_3db_deg(self.virtual, theta_deg, "phase")
        c = max(math.cos(math.radians(theta_deg)), 1e-3)
        return math.degrees(0.886 * self.wavelength_m / (self.aperture_m * c)) if self.n > 1 else 180.0

    def crlb_sigma_deg(self, snr_element_db: float, theta_deg: float) -> float:
        """Cramer-Rao bound on the angle [deg RMS] for a single snapshot of a
        deterministic source with per-element SNR ``snr_element_db``:
        var(u) = lambda^2 / (8 pi^2 SNR sum (x_k - x_mean)^2), sigma_theta =
        sigma_u / cos(theta)."""
        if self.n < 2:
            return float("inf")
        snr = 10.0 ** (snr_element_db / 10.0)
        ss = float(np.sum((self.x_v - self.x_v.mean()) ** 2))
        var_u = self.wavelength_m ** 2 / (8.0 * math.pi ** 2 * snr * ss)
        return math.degrees(math.sqrt(var_u) / max(math.cos(math.radians(theta_deg)), 1e-3))

    def angle_error_budget(self, snr_chirp_db: float, theta_deg: float, doppler_hz: float = 0.0,
                           range_scalloping_db: float = 0.0) -> dict:
        """What the estimator this module implements should scatter by, and
        why it is not the Cramer-Rao bound: the first-order (high-SNR) error
        of the windowed DBF peak on a TDM snapshot whose Doppler is estimated
        from the same chirps.  ``snr_chirp_db`` is the budget's SNR of one
        chirp's range bin on one receiver (isotropic element, on the grid).

        Every range-bin sample ``z[i, m, r]`` (TX block i, its chirp m, RX r)
        carries independent noise; the estimate is linear in it to first
        order, so the variance is the sum of squared coefficients:

        * the snapshot element (i, r) is the Doppler FFT's bin, weights
          ``c_m = d_m exp(j 2 pi delta m T) / D(delta)`` for a tone ``delta``
          off the bin (``sum c_m = 1``; ``sum |c_m|^2`` carries the Doppler
          window's coherent gain and its scalloping);
        * the beamformer's peak moves by ``sum_k a_k psi_k`` with ``a_k =
          w_k (x_k - x_w) / (kappa sum w_k (x_k - x_w)^2)``: uniform weights
          are the bound, a tapered window pays ``sum w^2 (x - x_w)^2
          sum (x - x_mean)^2 / (sum w (x - x_w)^2)^2`` in variance;
        * the TDM compensation takes ``i / n_tx`` of the estimated phase
          advance per TX period out of block i; the pulse-pair estimate
          (``doppler_fine_hz``) telescopes to the last chirp's phase minus
          the first's, averaged over the virtual channels, and is correlated
          with the snapshot through those two chirps.

        Returned: the bound at the budget's cell SNR (``sigma_crlb_deg``),
        the sigma factors of the element pattern, the cell's scalloping, the
        angle window and the Doppler estimate, their product applied to the
        bound (``sigma_expected_deg``), and the per-element cell SNR the
        snapshot really has.  Coupling (a bias, and coloured noise once its
        inverse is applied) is not in it."""
        m = self.cfg.mimo
        p = self.cfg.processing
        n_tx, n_rx = m.n_tx, m.n_rx
        m_tx = self.cfg.chirp.n_chirps // n_tx
        if self.n < 2:
            return {}
        cos_t = max(math.cos(math.radians(theta_deg)), 1e-3)
        kappa = TWOPI / self.wavelength_m
        d = window(p.window_doppler, m_tx)
        d = d / d.sum()
        t_tx = self.cfg.chirp.pri_s * n_tx
        bins = doppler_hz * t_tx * m_tx * p.doppler_pad
        delta_t = (bins - round(bins)) / (m_tx * p.doppler_pad)             # (f_d - f_bin) T, cycles per TX period
        rot = d * np.exp(1j * TWOPI * delta_t * np.arange(m_tx))
        big_d = rot.sum()

        def sigma_u(weights: np.ndarray, c: np.ndarray, rho_chirp: float, doppler_term: bool) -> float:
            xw = float(np.sum(weights * self.x_v) / np.sum(weights))
            a = weights * (self.x_v - xw) / (kappa * float(np.sum(weights * (self.x_v - xw) ** 2)))    # per element, TX-major
            i_tx = np.repeat(np.arange(n_tx), n_rx)
            cq = a[:, None] * c.real[None, :]                               # on the quadrature noise of z[k, m]
            cp = a[:, None] * c.imag[None, :]                               # on the in-phase noise
            if doppler_term and m.tdm_doppler_compensation and n_tx > 1 and m_tx > 1:
                b = float(np.sum(a * i_tx)) / n_tx
                cq = cq.copy()
                cq[:, -1] -= b / (self.n * (m_tx - 1))
                cq[:, 0] += b / (self.n * (m_tx - 1))
            return math.sqrt(float(np.sum(cq ** 2) + np.sum(cp ** 2)) / (2.0 * rho_chirp))

        rho0 = 10.0 ** (snr_chirp_db / 10.0)
        g2 = self.element_gain(theta_deg) ** 2
        rho = rho0 * g2 * 10.0 ** (-range_scalloping_db / 10.0)
        ones = np.ones(self.n)
        w = window(m.angle_window, self.n)
        c_grid = d.astype(complex)                                          # on the Doppler bin
        c_off = rot / big_d
        s_crlb = sigma_u(ones, c_grid, rho0, False)
        s_elem = sigma_u(ones, c_grid, rho0 * g2, False)
        s_scal = sigma_u(ones, c_off, rho, False)
        s_win = sigma_u(w, c_off, rho, False)
        s_all = sigma_u(w, c_off, rho, True)
        to_deg = lambda su: math.degrees(su / cos_t)                        # noqa: E731
        snr_el = 10.0 * math.log10(rho / float(np.sum(np.abs(c_off) ** 2)))
        return {"sigma_crlb_deg": to_deg(s_crlb), "factor_element_pattern": s_elem / s_crlb,
                "factor_scalloping": s_scal / s_elem, "factor_angle_window": s_win / s_scal,
                "factor_doppler_estimate": s_all / s_win, "sigma_expected_deg": to_deg(s_all),
                "snr_element_cell_db": snr_el, "doppler_bin_offset": float(delta_t * m_tx * p.doppler_pad)}

    def coupling_bias_deg(self, theta_deg: float) -> float:
        """What the uncalibrated coupling moves the estimate by (noiseless)."""
        if self.coupling is None:
            return 0.0
        est = self.estimate(self.snapshot(theta_deg, 0.0, coupled=True), 0.0)
        return est["theta_deg"] - theta_deg

    def tdm_bias_deg(self, theta_deg: float, doppler_hz: float) -> float:
        """What the TDM Doppler phase moves the estimate by when NOT compensated (noiseless)."""
        import dataclasses

        cfg = dataclasses.replace(self.cfg, mimo=dataclasses.replace(self.cfg.mimo, tdm_doppler_compensation=False))
        va = VirtualArray(cfg)
        est = va.estimate(va.snapshot(theta_deg, doppler_hz, coupled=False), None)
        return est["theta_deg"] - theta_deg

    def sweep_squint(self, theta_deg: float) -> dict:
        """The sweep's effect on the receive DBF and, for reference, on a
        phase-shifter-steered transmit beam: the per-element beat offset at
        the aperture's edge [range bins], the window taper it costs there
        [dB], and array_tx's squint of a beam aligned at f_c at the sweep's
        edges, next to the same beam over FR2's 400 MHz."""
        cfg = self.cfg
        s = math.sin(math.radians(theta_deg))
        edge = float(np.max(np.abs(self.x_v))) * s / C0                      # delay of the edge element
        shift_bins = cfg.slope_hz_per_s * edge * cfg.chirp.duration_s
        w = window(cfg.processing.window_range, cfg.n_samples)
        k = np.arange(w.size)
        taper = abs(np.sum(w * np.exp(-2j * np.pi * shift_bins * k / w.size))) / w.sum()
        b2 = 0.5 * cfg.band.sweep_hz
        return {"edge_shift_bins": float(shift_bins), "edge_taper_db": float(20.0 * math.log10(max(taper, 1e-300))),
                "tx_beam_squint_deg": (squint_analytic_deg(theta_deg, self.f0_hz, -b2), squint_analytic_deg(theta_deg, self.f0_hz, b2)),
                "fr2_400mhz_squint_deg": (squint_analytic_deg(theta_deg, 28e9, -200e6), squint_analytic_deg(theta_deg, 28e9, 200e6))}


__all__ = ["VirtualArray", "rx_coupling_matrix"]

"""Cyclic steady state for many operating points at once.

An optimizer needs the CSS of many nearby operating points: the current point plus one
perturbed point per decision variable for every gradient.  The columns, packing,
components and grid are the same for all of them; only the flows and the switch time
differ.  ``BatchSimulator`` therefore stacks the operating points along an extra array
axis and integrates them together with the same equations as ``smbsim.Simulator``.
With small grids the cost of a NumPy step is mostly fixed overhead, so a batch of
6-10 operating points costs little more than a single one.

Array layout: (component, member, column, grid point).
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

from smbsim import SMBConfig, Simulator
from smbsim.solver import ORIG_CFL, _vanleer


class BatchSimulator:
    """Integrates several operating points of one unit together (see the module docstring).

    All members must share the unit layout, grid, numerical mode and flow model; they may
    differ in the zone I flow, port flows and switch time.
    """

    def __init__(self, cfgs: list[SMBConfig]):
        self.cfgs = cfgs
        self.sims = [Simulator(c) for c in cfgs]  # validates every member, builds its flow plan
        s0 = self.sims[0]
        for s in self.sims[1:]:
            if (s.n, s.ncell, s.nc, s.cfg.scheme, s.vc, s.jb, s.open) != (
                s0.n,
                s0.ncell,
                s0.nc,
                s0.cfg.scheme,
                s0.vc,
                s0.jb,
                s0.open,
            ):
                raise ValueError("Batch members must share the unit layout, grid and model.")
        self.B, self.n, self.nc, self.ncell = len(cfgs), s0.n, s0.nc, s0.ncell
        self.scheme, self.vc, self.open, self.jb = s0.cfg.scheme, s0.vc, s0.open, s0.jb
        c4 = lambda a: np.asarray(a)[:, None, None, None]
        comps = s0.cfg.components
        self.par = {"qsat": c4([c.qsat for c in comps]), "keq": c4([c.keq for c in comps])}
        self.qeq_fn = s0.qeq_fn
        self.kap = c4([c.kap for c in comps])
        self.rho = c4([c.rho for c in comps])
        self.area, self.eps, self.pe, self.L = s0.area, s0.eps, s0.pe, s0.cfg.length
        self.phi = s0.phi
        self.prev, self.out_src, self.out_isbal = s0.prev, s0.out_src, s0.out_isbal

        st = lambda name: np.stack([getattr(s, name) for s in self.sims])
        self.Q1 = np.array([s.Q1 for s in self.sims])
        self.A_in, self.W_fix, self.D_next = st("A_in"), st("W_fix"), st("D_next")  # (B, n)
        self.c_add = np.stack([s.c_add for s in self.sims], axis=1)  # (nc, B, n)
        self.out_fixed = st("out_fixed")  # (B, nout)
        self.Fin_const = st("Fin_const")  # (B, n)
        self.QB_const = np.array([s.QB_const for s in self.sims])  # (B,)
        self.T = np.array([c.step_time for c in cfgs])
        self.nsub = max(s.nsub for s in self.sims)
        self.dt = self.T / self.nsub
        if self.scheme == "original":
            self.h, self.Mflow = s0.h, s0.Mflow
            self.rhs = self._rhs_original
        else:
            for k in ("dx", "dxc", "vol", "phic", "solid", "ebc"):
                setattr(self, k, getattr(s0, k))
            self.rhs = self._rhs_conservative

    # ------------------------------------------------------------------ network
    def network(self, dF: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Column inlet flows (B, n) and balance-outlet flows (B,) for flow changes ``dF`` across each column."""
        Fin = self.Q1[:, None] + np.concatenate(
            [np.zeros((self.B, 1)), np.cumsum(dF[:, :-1] + self.D_next[:, :-1], axis=1)], axis=1
        )
        if self.open:
            QB = Fin[:, -1] + dF[:, -1] - self.W_fix[:, 0]
        else:
            QB = Fin[:, -1] + dF[:, -1] + self.D_next[:, -1] - self.Q1
            if self.jb:
                Fin = Fin.copy()
                Fin[:, self.jb :] -= QB[:, None]
        return Fin, QB

    def mix_inlet(self, Cout: np.ndarray, Fin: np.ndarray) -> np.ndarray:  # Cout (nc, B, n)
        """Column inlet concentrations from the previous column outlets plus the inlet ports."""
        return (Cout[:, :, self.prev] * (Fin - self.A_in) + self.c_add) / Fin

    def outlet_rates(self, Cout: np.ndarray, QB: np.ndarray) -> np.ndarray:  # -> (B, nout, nc)
        """Mass flow of every component in every outlet port, for every member."""
        flows = np.where(self.out_isbal, QB[:, None], self.out_fixed)
        return np.transpose(Cout[:, :, self.out_src], (1, 2, 0)) * flows[:, :, None]

    def qeq(self, C: np.ndarray) -> np.ndarray:
        """Equilibrium adsorbed concentrations from the isotherm."""
        return self.qeq_fn(C, self.par)

    # ------------------------------------------------------------------ schemes
    def _rhs_original(self, C, Q):
        A, eb, L, h = self.area, self.eps, self.L, self.h
        dQt = self.kap * (self.qeq(C[..., 1:]) - Q[..., 1:])
        if self.vc:
            s = np.zeros((self.B, self.n, self.ncell))
            s[..., 1:] = -A * (1 - eb) * np.sum(dQt / self.rho, axis=0)
            G = s @ self.Mflow.T
            Fin, QB = self.network(G[..., -1])
            Fn = Fin[..., None] + G
        else:
            Fin, QB = self.Fin_const, self.QB_const
            Fn = Fin[..., None]
        Cin = self.mix_inlet(C[..., -1], Fin)
        C = C.copy()
        C[..., 0] = Cin
        dQ = np.empty_like(Q)
        dQ[..., 1:] = dQt
        dQ[..., 0] = self.kap[..., 0] * (self.qeq(Cin[..., None])[..., 0] - Q[..., 0])
        d1 = np.empty_like(C)
        d2 = np.empty_like(C)
        hi = h[1:-1]
        d1[..., 1:-1] = (C[..., 2:] - C[..., :-2]) / (2 * hi)
        d2[..., 1:-1] = (C[..., 2:] - 2 * C[..., 1:-1] + C[..., :-2]) / hi**2
        hN = h[-1]
        d1[..., -1] = (3 * C[..., -1] - 4 * C[..., -2] + C[..., -3]) / (2 * hN)
        d2[..., -1] = (2 * C[..., -1] - 5 * C[..., -2] + 4 * C[..., -3] - C[..., -4]) / hN**2
        u = Fn / (A * eb)
        dC = -u * d1 + u * (L / self.pe) * d2 - self.phi * dQ
        if self.vc:
            dC -= C * (s / (A * eb))
        dC[..., 0] = 0.0
        return dC, dQ, self.outlet_rates(C[..., -1], QB), QB

    def _rhs_conservative(self, C, Q):
        L = self.L
        dQ = self.kap * (self.qeq(C) - Q) * self.solid
        if self.vc:
            dFc = -self.area * (1 - self.ebc) * self.dx * np.sum(dQ / self.rho, axis=0)  # (B, n, ncell)
            Fin, QB = self.network(dFc.sum(axis=2))
            Ff = np.concatenate([Fin[..., None], Fin[..., None] + np.cumsum(dFc, axis=2)], axis=2)
        else:
            Fin, QB = self.Fin_const, self.QB_const
            Ff = np.broadcast_to(Fin[..., None], (self.B, self.n, self.ncell + 1))
        Cin = self.mix_inlet(C[..., -1], Fin)
        dp = np.diff(C, axis=3)
        dm = C[..., :-1] - np.concatenate([Cin[..., None], C[..., :-2]], axis=3)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(np.abs(dp) > 1e-14, dm / dp, 0.0)
        Cf = C[..., :-1] + 0.5 * _vanleer(r) * dp
        flux = np.empty(C.shape[:3] + (self.ncell + 1,))
        flux[..., 0] = Fin * Cin
        flux[..., 1:-1] = Ff[..., 1:-1] * (Cf - (L / self.pe) * dp / self.dxc)
        flux[..., -1] = Ff[..., -1] * C[..., -1]
        dC = -(flux[..., 1:] - flux[..., :-1]) / self.vol - self.phic * dQ
        return dC, dQ, self.outlet_rates(C[..., -1], QB), QB

    # ------------------------------------------------------------------ driving
    def initial_state(self) -> tuple[np.ndarray, np.ndarray]:
        """Unit full of desorbent, in equilibrium, for every member: (C, Q), each (nc, B, n, ncell)."""
        C0, Q0 = self.sims[0].initial_state()
        return np.repeat(C0[:, None], self.B, axis=1), np.repeat(Q0[:, None], self.B, axis=1)

    def advance(self, C: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """One switching period for every member (SSP-RK3, a common number of sub-steps)."""
        dt4 = self.dt[None, :, None, None]
        dto = self.dt[:, None, None]
        out = np.zeros((self.B, len(self.out_src), self.nc))
        qb = np.zeros(self.B)
        w = (1 / 6, 1 / 6, 2 / 3)
        for _ in range(self.nsub):
            k1 = self.rhs(C, Q)
            C1 = C + dt4 * k1[0]
            Q1 = Q + dt4 * k1[1]
            k2 = self.rhs(C1, Q1)
            C2 = 0.75 * C + 0.25 * (C1 + dt4 * k2[0])
            Q2 = 0.75 * Q + 0.25 * (Q1 + dt4 * k2[1])
            k3 = self.rhs(C2, Q2)
            C = C / 3 + 2 / 3 * (C2 + dt4 * k3[0])
            Q = Q / 3 + 2 / 3 * (Q2 + dt4 * k3[1])
            for wk, kk in zip(w, (k1, k2, k3)):
                out += dto * wk * kk[2]
                qb += self.dt * wk * kk[3]
        return C, Q, out, qb / self.T

    # state <-> flat vectors, one row per member
    def _pack(self, C, Q):
        return np.concatenate(
            [np.moveaxis(C, 1, 0).reshape(self.B, -1), np.moveaxis(Q, 1, 0).reshape(self.B, -1)], axis=1
        )

    def _unpack(self, x):
        half = x.shape[1] // 2
        shp = (self.B, self.nc, self.n, self.ncell)
        return (np.moveaxis(x[:, :half].reshape(shp), 0, 1), np.moveaxis(x[:, half:].reshape(shp), 0, 1))

    def switch_map(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """One switching period followed by the port switch (re-indexing by one column)."""
        C, Q = self._unpack(x)
        C, Q, out, qb = self.advance(C, Q)
        return self._pack(np.roll(C, -1, axis=2), np.roll(Q, -1, axis=2)), out, qb

    def css(
        self,
        warm: Optional[tuple[np.ndarray, np.ndarray]] = None,
        tol: float = 1e-7,
        max_switches: Optional[int] = None,
        memory: int = 12,
        cancel: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """Switch every member to cyclic steady state.

        The CSS is the fixed point x = G(x) of the switch map G (one period, then re-index the
        columns by one).  Plain repetition converges slowly, so the iteration is accelerated with
        Anderson mixing, separately for every member.  ``warm`` is an optional (C, Q) of shape
        (nc, n, ncell), used as the starting state of every member (for example the CSS of a
        nearby operating point).  Without it the unit starts full of desorbent and is switched
        for two cycles before acceleration starts.
        """
        n = self.n
        if warm is None:
            x = self._pack(*self.initial_state())
            for _ in range(2 * n):
                x, out, qb = self.switch_map(x)
            used = 2 * n
        else:
            C, Q = (np.asarray(a, float) for a in warm)
            if C.ndim == 3:
                C = np.repeat(C[:, None], self.B, axis=1)
                Q = np.repeat(Q[:, None], self.B, axis=1)
            x = self._pack(C, Q)
            used = 0
        max_switches = max_switches or 300 * n
        X, Fh = [], []  # Anderson history: iterates and residuals, each (B, N)
        best = np.full(self.B, np.inf)
        res = np.full(self.B, np.inf)
        while used < max_switches:
            if cancel is not None and cancel():
                raise InterruptedError("cancelled")
            gx, out, qb = self.switch_map(x)
            used += 1
            f = gx - x
            res = np.abs(f).max(axis=1)
            if not np.all(np.isfinite(res)):
                raise FloatingPointError("The simulation became unstable at one of the operating points.")
            if np.all(res < tol):
                x = gx
                break
            X.append(x)
            Fh.append(f)
            X, Fh = X[-memory - 1 :], Fh[-memory - 1 :]
            xn = gx.copy()
            if len(Fh) > 1:
                dX = np.stack([X[i + 1] - X[i] for i in range(len(X) - 1)], axis=2)  # (B, N, m)
                dF = np.stack([Fh[i + 1] - Fh[i] for i in range(len(Fh) - 1)], axis=2)
                for b in range(self.B):
                    if res[b] < tol:
                        continue
                    if res[b] > 50 * best[b]:  # safeguard: restart the history if mixing went astray
                        continue
                    gam, *_ = np.linalg.lstsq(dF[b], f[b], rcond=None)
                    xn[b] = x[b] + f[b] - (dX[b] + dF[b]) @ gam
            if np.any(res > 50 * best):
                X, Fh = [], []
            best = np.minimum(best, res)
            x = xn
        metrics = [s.metrics(out[b], qb[b]) for b, s in enumerate(self.sims)]
        C, Q = self._unpack(x)
        return {
            "metrics": metrics,
            "C": C,
            "Q": Q,
            "residual": res,
            "switches": used,
            "converged": bool(np.all(res < tol)),
        }

    def member_state(self, result: dict, b: int) -> tuple[np.ndarray, np.ndarray]:
        """The CSS state (C, Q) of member ``b`` from a ``css()`` result."""
        return result["C"][:, b].copy(), result["Q"][:, b].copy()

"""Operating-condition optimization by trust-region sequential quadratic programming.

Every evaluation of the objective or constraints is a cyclic-steady-state simulation.  The
decision variables are scaled to [0, 1] between their bounds.  Gradients come from forward
finite differences; the current point and its perturbed copies are simulated together
(``BatchSimulator``), started from the CSS of the previous point, and optionally split over
several processes.  Flow limits and feed or desorbent objectives are computed analytically.

At the optimum the Lagrange multipliers of the binding limits are estimated from the
gradients (non-negative least squares).  They are reported as "what one unit of relaxation
is worth": for example the extra feed that one percentage point less extract purity would
allow.
"""

from __future__ import annotations

import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
from typing import Any, Callable, Optional, Sequence

import numpy as np
from scipy.optimize import minimize, nnls

from smbsim import SMBConfig, Simulator
from .batch import BatchSimulator
from .problem import Problem, METRICS, METRIC_LABEL, OBJECTIVES


class Cancelled(Exception):
    """Raised when a run is stopped through its ``cancel`` callback."""


# ------------------------------------------------------------------ batch runs (also used by workers)
def _run_chunk(cfg_dicts, warm, tol, cancel=None):
    cfgs = [SMBConfig.from_dict(d) for d in cfg_dicts]
    r = BatchSimulator(cfgs).css(warm=warm, tol=tol, cancel=cancel)
    return {
        "metrics": [_slim(m) for m in r["metrics"]],
        "C": r["C"],
        "Q": r["Q"],
        "switches": r["switches"],
        "residual": r["residual"],
    }


def _slim(m):
    keep = METRICS + ("balance_flow", "desorbent_to_feed", "productivity", "m_values")
    out = {k: m[k] for k in keep}
    out["components"] = m["components"]
    out["streams"] = [
        {k: s[k] for k in ("label", "kind", "flow", "balance", "composition", "product_fraction")} for s in m["streams"]
    ]
    return out


def default_workers() -> int:
    """Default number of worker processes: one fewer than the CPU count, between 1 and 8."""
    return max(1, min((os.cpu_count() or 2) - 1, 8))


class BatchRunner:
    """Runs a list of operating points to CSS, split over worker processes when useful."""

    def __init__(self, workers: int = 0) -> None:
        self.workers = workers or default_workers()
        self.pool = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(cancel_futures=True)
            self.pool = None

    def run(
        self, cfgs: Sequence[SMBConfig], warm: Any, tol: float, cancel: Optional[Callable[[], bool]] = None
    ) -> tuple[list[dict], float]:
        """Run every setup to CSS (from the warm state ``warm``, or from a fresh start if None).

        Returns one ``{"metrics", "C", "Q"}`` dictionary per setup and the mean number of switches.
        """
        dicts = [c.to_dict() for c in cfgs]
        k = min(self.workers, len(dicts))
        if k <= 1:
            parts = [_run_chunk(dicts, warm, tol, cancel)]
        else:
            if self.pool is None:
                self.pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=mp.get_context("spawn"))
            chunks = [list(range(len(dicts)))[i::k] for i in range(k)]
            futs = [self.pool.submit(_run_chunk, [dicts[j] for j in ch], warm, tol) for ch in chunks]
            res = [f.result() for f in futs]
            parts, order = [], []
            for ch, r in zip(chunks, res):
                parts.append(r)
                order.append(ch)
            merged = [None] * len(dicts)
            for ch, r in zip(chunks, res):
                for pos, j in enumerate(ch):
                    merged[j] = {"metrics": r["metrics"][pos], "C": r["C"][:, pos], "Q": r["Q"][:, pos]}
            return merged, sum(r["switches"] for r in res) / len(res)
        r = parts[0]
        return [{"metrics": r["metrics"][j], "C": r["C"][:, j], "Q": r["Q"][:, j]} for j in range(len(dicts))], r[
            "switches"
        ]


# ------------------------------------------------------------------ the optimizer
class Optimizer:
    """Trust-region SQP search for the best operating point of a ``Problem``.

    ``progress`` is called with a dictionary after every evaluation batch and iteration, and
    ``cancel`` is polled between simulations; returning True stops the run with ``Cancelled``.
    Use ``run()`` to optimize.
    """

    def __init__(
        self,
        problem: Problem,
        progress: Optional[Callable[[dict], None]] = None,
        cancel: Optional[Callable[[], bool]] = None,
        runner: BatchRunner | None = None,
    ) -> None:
        errs = problem.validate()
        if errs:
            raise ValueError("\n".join(errs))
        self.p = problem
        self.vars = problem.opt_vars()
        self.lb = np.array([v.lower for v in self.vars])
        self.ub = np.array([v.upper for v in self.vars])
        self.span = self.ub - self.lb
        self.progress, self.cancel = progress, cancel
        self.runner = runner or BatchRunner(problem.workers)
        self._own_runner = runner is None
        self.cache = {}  # key -> {"x", "metrics", "C", "Q", "grad"}
        self.warm = None
        self.evaluations = 0
        self.sim_switches = 0
        self.history = []
        self.t0 = time.time()
        start = problem.start_values()
        x0 = np.array([min(max(start[v.key], v.lower), v.upper) for v in self.vars])
        self.z0 = (x0 - self.lb) / self.span
        f0 = problem.flows(problem.config_at(start))
        self.feed0 = max(f0["feed"], 1e-6)
        self.ratio0 = f0["desorbent_ratio"] if math.isfinite(f0["desorbent_ratio"]) else 10.0
        self.cons = self._constraint_list()
        # aim slightly inside every product specification (0.002 percentage point): the purity
        # surfaces are curved, so steps planned exactly onto a limit tend to land just outside it
        self.band = np.array([-self.AIM if c["kind"] == "spec" else 0.0 for c in self.cons])

    # ---------------------------------------------------------- variable mapping
    def values(self, z: np.ndarray) -> dict:
        """Physical values of all variables at the scaled point ``z`` (each in [0, 1])."""
        x = self.lb + np.clip(z, 0, 1) * self.span
        vals = self.p.start_values()
        vals.update({v.key: float(xi) for v, xi in zip(self.vars, x)})
        return vals

    def config(self, z: np.ndarray) -> SMBConfig:
        """The process setup at the scaled point ``z``."""
        return self.p.config_at(self.values(z))

    @staticmethod
    def _key(z):
        return tuple(np.round(np.asarray(z, float), 12))

    # ---------------------------------------------------------- analytic parts
    def _analytic(self, z):
        cfg = self.config(z)
        f = self.p.flows(cfg)
        a = {
            "feed": f["feed"],
            "desorbent_ratio": min(f["desorbent_ratio"], 1e6),
            "zones": np.array(f["zone_flows"]),
            "balance": f["balance_flow"],
        }
        return a

    def _analytic_grad(self, z, fn):
        """Gradient of an analytic (linear or rational) function of the flows, by central differences."""
        g = np.zeros(len(z))
        h = 1e-6
        for i in range(len(z)):
            zp, zm = z.copy(), z.copy()
            zp[i] += h
            zm[i] -= h
            g[i] = (fn(zp) - fn(zm)) / (2 * h)
        return g

    # ---------------------------------------------------------- simulations
    def _steps(self, z):
        x = self.lb + z * self.span
        return self.p.fd_step * np.maximum(np.abs(x), 0.1 * self.span) / self.span

    def _evaluate(self, z, need_grad=True):
        if self.cancel and self.cancel():
            raise Cancelled()
        z = np.clip(np.asarray(z, float), 0, 1)
        key = self._key(z)
        hit = self.cache.get(key)
        if hit is not None and (hit["grad"] is not None or not need_grad):
            return hit
        pts, dirs = [], []
        if hit is None:
            pts.append(z.copy())
            dirs.append(None)
        if need_grad:
            h = self._steps(z)
            for i in range(len(z)):
                step = h[i] if z[i] + h[i] <= 1 else -h[i]
                zp = z.copy()
                zp[i] += step
                if self.config(zp).validate():
                    zp[i] = z[i] - step
                    step = -step
                pts.append(zp)
                dirs.append((i, step))
        cfgs = [self.config(q) for q in pts]
        for c in cfgs:
            errs = c.validate()
            if errs:
                raise ValueError("Operating point outside the valid range: " + "; ".join(errs))
        warm = self.warm
        if hit is not None:
            warm = (hit["C"], hit["Q"])
        if self.progress:
            self.progress(
                {
                    "stage": "evaluating",
                    "points": len(pts),
                    "iteration": len(self.history),
                    "evaluations": self.evaluations,
                    "elapsed": time.time() - self.t0,
                }
            )
        _t = time.time()
        try:
            res, sw = self.runner.run(cfgs, warm, self.p.css_tol, cancel=self.cancel)
        except InterruptedError:
            raise Cancelled()
        self.evaluations += len(pts)
        self.sim_switches += sw
        if os.environ.get("SMBOPT_DEBUG"):
            print(f"    batch of {len(pts)}: {sw:.0f} switches, {time.time() - _t:.1f} s", flush=True)
        if hit is None:
            hit = {"z": z, "metrics": res[0]["metrics"], "C": res[0]["C"], "Q": res[0]["Q"], "grad": None}
            res = res[1:]
            self.cache[key] = hit
        self.warm = (hit["C"], hit["Q"])
        if need_grad:
            grad = {}
            for m in METRICS:
                g = np.zeros(len(z))
                for (i, step), r in zip(dirs[1:] if dirs[0] is None else dirs, res):
                    g[i] = (r["metrics"][m] - hit["metrics"][m]) / step
                grad[m] = g
            hit["grad"] = grad
        return hit

    # ---------------------------------------------------------- objective
    def _obj_value(self, z, metrics=None):
        o = self.p.objective
        if o == "max_feed":
            return -self._analytic(z)["feed"] / self.feed0
        if o == "min_desorbent":
            return self._analytic(z)["desorbent_ratio"] / self.ratio0
        m = metrics if metrics is not None else self._evaluate(z, need_grad=False)["metrics"]
        return -m[o[4:]] / 100.0

    def fun(self, z: np.ndarray) -> float:
        """Scaled objective at ``z`` (minimized)."""
        if self.p.objective_is_analytic():
            self._evaluate(z)  # speculative: the point and its gradient are needed next
            return self._obj_value(z)
        return self._obj_value(z, self._evaluate(z)["metrics"])

    def jac(self, z: np.ndarray) -> np.ndarray:
        """Gradient of the scaled objective at ``z``."""
        o = self.p.objective
        if o == "max_feed":
            return self._analytic_grad(np.asarray(z, float), lambda q: -self._analytic(q)["feed"] / self.feed0)
        if o == "min_desorbent":
            return self._analytic_grad(
                np.asarray(z, float), lambda q: self._analytic(q)["desorbent_ratio"] / self.ratio0
            )
        return -self._evaluate(z)["grad"][o[4:]] / 100.0

    # ---------------------------------------------------------- constraints (g >= 0)
    def _constraint_list(self):
        p, cons = self.p, []
        for s in p.specs:
            if s.enabled:
                cons.append(
                    {
                        "name": f"{METRIC_LABEL[s.metric]} ≥ {s.minimum:g} %",
                        "kind": "spec",
                        "metric": s.metric,
                        "scale": 10.0,
                        "minimum": s.minimum,
                    }
                )
        nz = len(p.base_config().zones)
        from smbsim.config import ROMAN

        if p.max_zone_flow is not None:
            for zi in range(nz):
                cons.append(
                    {"name": f"Zone {ROMAN[zi]} flow ≤ {p.max_zone_flow:g} mL/min", "kind": "zone_max", "zone": zi}
                )
        for zi in range(nz):
            cons.append({"name": f"Zone {ROMAN[zi]} flow ≥ {p.min_zone_flow:g} mL/min", "kind": "zone_min", "zone": zi})
        cons.append({"name": f"Balance outlet flow ≥ {p.min_zone_flow:g} mL/min", "kind": "balance_min"})
        if p.max_desorbent_ratio is not None:
            cons.append({"name": f"Desorbent / feed ≤ {p.max_desorbent_ratio:g}", "kind": "ratio_max"})
        return cons

    def _flow_scale(self):
        return self.p.max_zone_flow or max(self._analytic(self.z0)["zones"].max(), 1.0)

    def _analytic_con(self, c, z):
        a = self._analytic(z)
        p = self.p
        s = self._flow_scale()
        if c["kind"] == "zone_max":
            return (p.max_zone_flow - a["zones"][c["zone"]]) / s
        if c["kind"] == "zone_min":
            return (a["zones"][c["zone"]] - p.min_zone_flow) / s
        if c["kind"] == "balance_min":
            return (a["balance"] - p.min_zone_flow) / s
        if c["kind"] == "ratio_max":
            return (p.max_desorbent_ratio - a["desorbent_ratio"]) / p.max_desorbent_ratio
        raise KeyError(c["kind"])

    def con_value(self, c: dict, z: np.ndarray) -> float:
        """Scaled value of limit ``c`` at ``z`` (met when >= 0)."""
        if c["kind"] == "spec":
            return (self._evaluate(z, need_grad=False)["metrics"][c["metric"]] - c["minimum"]) / c["scale"]
        return self._analytic_con(c, np.asarray(z, float))

    def con_grad(self, c: dict, z: np.ndarray) -> np.ndarray:
        """Gradient of the scaled limit ``c`` at ``z``."""
        if c["kind"] == "spec":
            return self._evaluate(z)["grad"][c["metric"]] / c["scale"]
        return self._analytic_grad(np.asarray(z, float), lambda q: self._analytic_con(c, q))

    # ---------------------------------------------------------- reporting helpers
    def objective_physical(self, z: np.ndarray, metrics: dict) -> float:
        """Objective in physical units (mL/min feed, desorbent/feed or %)."""
        o = self.p.objective
        a = self._analytic(z)
        if o == "max_feed":
            return a["feed"]
        if o == "min_desorbent":
            return a["desorbent_ratio"]
        return metrics[o[4:]]

    def snapshot(self, z: np.ndarray) -> dict:
        """Values, objective, purities, recoveries, flows and limit status at ``z``."""
        hit = self._evaluate(z, need_grad=False)
        a = self._analytic(z)
        cfg = self.config(z)
        d = cfg.derived()
        return {
            "values": self.values(z),
            "objective": self.objective_physical(z, hit["metrics"]),
            "metrics": {k: hit["metrics"][k] for k in METRICS},
            "feed": a["feed"],
            "desorbent_ratio": a["desorbent_ratio"],
            "zone_flows": list(a["zones"]),
            "balance_flow": a["balance"],
            "m_values": d["m_values"],
            "constraints": [
                {
                    "name": c["name"],
                    "value": self._con_physical(c, z, hit["metrics"]),
                    "ok": self.con_value(c, z) >= -1e-4,
                }
                for c in self.cons
            ],
        }

    def _con_physical(self, c, z, metrics):
        a = self._analytic(z)
        if c["kind"] == "spec":
            return metrics[c["metric"]]
        if c["kind"] in ("zone_max", "zone_min"):
            return float(a["zones"][c["zone"]])
        if c["kind"] == "balance_min":
            return a["balance"]
        return a["desorbent_ratio"]

    # ---------------------------------------------------------- run
    def run(self) -> dict:
        """Optimize from the start values and return the result dictionary (see ``optimize``)."""
        try:
            return self._run()
        finally:
            if self._own_runner:
                self.runner.close()

    def _run(self):
        self.t0 = time.time()
        z0 = self.z0.copy()
        start = self.snapshot(z0)
        self.history.append(self._hist_entry(z0))
        if self.progress:
            self.progress(
                {
                    "stage": "start",
                    "history": self.history,
                    "start": start,
                    "evaluations": self.evaluations,
                    "elapsed": time.time() - self.t0,
                }
            )

        z_opt, message, success = self._trsqp(z0)
        # keep the best feasible point seen
        z_opt = self._best_feasible(z_opt)
        if self._key(z_opt) != self._key(self.history[-1]["z"]):
            self.history.append(self._hist_entry(z_opt))
        final = self.snapshot(z_opt)
        feasible = all(c["ok"] for c in final["constraints"])
        binding = self.multipliers(z_opt)
        return {
            "success": success and feasible,
            "solver_success": success,
            "message": str(message),
            "feasible": feasible,
            "start": start,
            "optimum": final,
            "history": [{k: v for k, v in h.items() if k != "z"} for h in self.history],
            "binding": binding,
            "evaluations": self.evaluations,
            "elapsed": time.time() - self.t0,
            "rejected_steps": getattr(self, "rejected", 0),
            "z_opt": list(map(float, z_opt)),
            "variables": [v.__dict__ for v in self.p.variables],
            "objective": self.p.objective,
            "objective_label": OBJECTIVES[self.p.objective],
            "optimum_config": self.config(z_opt).to_dict(),
            "_points": {"start": self.cache[self._key(z0)], "optimum": self.cache[self._key(z_opt)]},
        }

    # ---------------------------------------------------------- trust-region SQP
    def _model(self, z, need_grad=True):
        """Objective, constraints and (optionally) their gradients at z, all in scaled units."""
        hit = self._evaluate(z, need_grad=need_grad)
        f = self._obj_value(z, hit["metrics"])
        g = np.array([self.con_value(c, z) for c in self.cons])
        out = {"z": np.asarray(z, float).copy(), "f": f, "g": g}
        if need_grad:
            out["gf"] = np.asarray(self.jac(z), float)
            out["J"] = np.array([self.con_grad(c, z) for c in self.cons])
        return out

    FEAS_TOL = 1e-4  # scaled; a limit counts as met within 0.001 percentage point
    AIM = 2e-4  # scaled; the search aims 0.002 percentage point inside each product limit

    def _merit(self, m, mu):
        # L1 penalty on the (shifted) limits
        return m["f"] + mu * np.maximum(0.0, -m["g"] - self.band).sum()

    def _qp(self, m, B, delta, mu):
        """Sl1QP step: min gf.d + 1/2 d'Bd + mu*sum(t)  s.t.  g + J d + t >= 0, t >= 0, |d| <= delta, 0 <= z+d <= 1."""
        z, gf, g, J = m["z"], m["gf"], m["g"] + self.band, m["J"]
        n, k = len(z), len(g)
        lo = np.maximum(-delta, -z)
        hi = np.minimum(delta, 1 - z)

        def obj(v):
            d, t = v[:n], v[n:]
            return gf @ d + 0.5 * d @ B @ d + mu * t.sum()

        def obj_jac(v):
            d = v[:n]
            return np.concatenate([gf + B @ d, np.full(k, mu)])

        A = np.hstack([J, np.eye(k)])
        cons = [{"type": "ineq", "fun": lambda v: g + A @ v, "jac": lambda v: A}]
        t0 = np.maximum(0.0, -g)
        best = None
        for d0 in (np.zeros(n), np.clip(-gf, lo, hi) * 0.5):
            r = minimize(
                obj,
                np.concatenate([d0, t0 + np.maximum(0, -(J @ d0))]),
                jac=obj_jac,
                method="SLSQP",
                bounds=list(zip(lo, hi)) + [(0, None)] * k,
                constraints=cons,
                options={"maxiter": 200, "ftol": 1e-12},
            )
            if best is None or r.fun < best.fun:
                best = r
        d = np.clip(best.x[:n], lo, hi)
        lin = g + J @ d
        model = gf @ d + 0.5 * d @ B @ d + mu * np.maximum(0, -lin).sum()
        pred = mu * np.maximum(0, -g).sum() - model
        # multipliers of the linearized constraints that are active at the step
        act = np.where(lin <= 1e-7)[0]
        lam = np.zeros(k)
        if len(act):
            cols = [J[i] for i in act]
            rhs = gf + B @ d
            for i in range(n):
                if d[i] >= hi[i] - 1e-9 and hi[i] < delta - 1e-9:
                    cols.append(-np.eye(n)[i])
                elif d[i] <= lo[i] + 1e-9 and lo[i] > -delta + 1e-9:
                    cols.append(np.eye(n)[i])
            sol, _ = nnls(np.array(cols).T, rhs)
            lam[act] = np.minimum(sol[: len(act)], mu)
        return d, pred, lam

    def _trsqp(self, z0):
        """Trust-region SQP on an exact L1 penalty (Sl1QP).

        Every iteration solves a small quadratic model of the problem inside a box of size
        delta around the current point, simulates the proposed point, and accepts it only if
        the penalty merit (objective + mu * constraint violation) really improves.  The box
        grows after good steps and shrinks after poor ones, so the strongly nonlinear purity
        response cannot throw the search far away, and no step is taken on faith.
        """
        n = len(z0)
        mu, delta, delta_min = 10.0, 0.2, 1e-4
        B = np.eye(n)
        m = self._model(z0)
        rejected = 0
        message, success = "Iteration limit reached.", False
        for it in range(self.p.max_iterations):
            d, pred, lam = self._qp(m, B, delta, mu)
            step = np.abs(d).max()
            viol = np.maximum(0, -m["g"] - self.band).sum()
            interior = step < 0.5 * delta  # the model's best step lies inside the box: a real optimum
            if step < 1e-5 or (interior and pred < 1e-4 * max(1.0, abs(m["f"])) and viol < 1e-5):
                message, success = "Converged: no further improvement within the limits.", True
                break
            z_new = np.clip(m["z"] + d, 0, 1)
            trial = self._model(z_new, need_grad=False)
            ared = self._merit(m, mu) - self._merit(trial, mu)
            rho = ared / pred if pred > 1e-12 else -1.0
            if rho <= 0.1 and np.maximum(0, -trial["g"] - self.band).sum() > viol:
                # second-order correction: the step left the curved limits; re-solve the model with the
                # constraint values actually found at the trial point and try the corrected step once
                msoc = dict(m, g=trial["g"] - m["J"] @ d)  # _qp adds the tolerance band itself
                d2, _, _ = self._qp(msoc, B, delta, mu)
                z_soc = np.clip(m["z"] + d2, 0, 1)
                if np.abs(z_soc - z_new).max() > 1e-9:
                    t2 = self._model(z_soc, need_grad=False)
                    ared2 = self._merit(m, mu) - self._merit(t2, mu)
                    if ared2 / pred > 0.1 if pred > 1e-12 else False:
                        z_new, trial, ared, rho, d = z_soc, t2, ared2, ared2 / pred, d2
                        step = np.abs(d).max()
            if os.environ.get("SMBOPT_DEBUG"):
                print(
                    f"    step {step:.4f} delta {delta:.4f} pred {pred:.2e} ared {ared:.2e} rho {rho:.2f}", flush=True
                )
            if rho > 0.1:
                new = self._model(z_new, need_grad=True)
                s = new["z"] - m["z"]
                yl = (new["gf"] - new["J"].T @ lam) - (m["gf"] - m["J"].T @ lam)
                sBs = s @ B @ s
                if sBs > 1e-14:  # damped BFGS (Powell) keeps B positive definite
                    sy = s @ yl
                    theta = 1.0 if sy >= 0.2 * sBs else 0.8 * sBs / (sBs - sy)
                    r = theta * yl + (1 - theta) * (B @ s)
                    Bs = B @ s
                    B = B - np.outer(Bs, Bs) / sBs + np.outer(r, r) / max(s @ r, 1e-14)
                m = new
                if rho > 0.75 and step > 0.8 * delta:
                    delta = min(2 * delta, 0.5)
                elif rho < 0.25:
                    delta = max(0.5 * delta, delta_min)
                self.history.append(self._hist_entry(m["z"]))
                if self.progress:
                    self.progress(
                        {
                            "stage": "iteration",
                            "history": self.history,
                            "rejected": rejected,
                            "evaluations": self.evaluations,
                            "elapsed": time.time() - self.t0,
                        }
                    )
            else:
                rejected += 1
                delta = max(0.4 * step, delta_min)
                if self.progress:
                    self.progress(
                        {
                            "stage": "rejected",
                            "history": self.history,
                            "rejected": rejected,
                            "evaluations": self.evaluations,
                            "elapsed": time.time() - self.t0,
                        }
                    )
            if delta <= delta_min and rho <= 0.1:
                message, success = (
                    "Stopped: the trust region shrank to its minimum (the limits are as tight as the simulation accuracy).",
                    True,
                )
                break
        self.rejected = rejected
        return m["z"], message, success

    def _hist_entry(self, z):
        s = self.snapshot(z)
        return {
            "z": np.asarray(z, float).copy(),
            "iteration": len(self.history),
            "values": s["values"],
            "objective": s["objective"],
            "metrics": s["metrics"],
            "m_values": s["m_values"],
            "feed": s["feed"],
            "desorbent_ratio": s["desorbent_ratio"],
            "feasible": all(c["ok"] for c in s["constraints"]),
            "max_violation": max(
                [0.0]
                + [
                    -self.con_value(c, z) * (c.get("scale", 1.0) if c["kind"] == "spec" else self._flow_scale())
                    for c in self.cons
                ]
            ),
            "evaluations": self.evaluations,
            "elapsed": time.time() - self.t0,
        }

    def _best_feasible(self, z_last):
        def ok(z):
            return all(self.con_value(c, z) >= -1e-4 for c in self.cons)

        cands = [h["z"] for h in self.history] + [z_last]
        feas = [z for z in cands if self._key(z) in self.cache and ok(z)]
        if not feas:
            return z_last
        return min(feas, key=lambda z: self._obj_value(z, self.cache[self._key(z)]["metrics"]))

    # ---------------------------------------------------------- shadow prices
    def multipliers(self, z: np.ndarray) -> list[dict]:
        """Estimate which limits bind at z and what relaxing each one by one unit is worth."""
        z = np.asarray(z, float)
        hit = self._evaluate(z, need_grad=True)
        gf = self.jac(z)
        cols, items = [], []
        for c in self.cons:
            g = self.con_value(c, z)
            if g < 2e-3:
                cols.append(self.con_grad(c, z))
                items.append(("con", c))
        for i, v in enumerate(self.vars):
            if z[i] > 1 - 1e-6:
                e = np.zeros(len(z))
                e[i] = -1.0
                cols.append(e)
                items.append(("upper", i))
            elif z[i] < 1e-6:
                e = np.zeros(len(z))
                e[i] = 1.0
                cols.append(e)
                items.append(("lower", i))
        if not cols:
            return []
        A = np.array(cols).T
        mu, resid = nnls(A, gf)
        o = self.p.objective
        # d(objective, physical) per unit of scaled objective
        if o == "max_feed":
            obj_scale, obj_unit = self.feed0, "mL/min feed"
        elif o == "min_desorbent":
            obj_scale, obj_unit = self.ratio0, "desorbent/feed"
        else:
            obj_scale, obj_unit = 100.0, "points " + METRIC_LABEL[o[4:]].lower()
        out = []
        for (kind, item), m in zip(items, mu):
            if kind == "con":
                c = item
                if c["kind"] == "spec":
                    per, unit = 1.0 / c["scale"], "per percentage point"
                elif c["kind"] == "ratio_max":
                    per, unit = 1.0 / self.p.max_desorbent_ratio, "per unit of desorbent/feed"
                else:
                    per, unit = 1.0 / self._flow_scale(), "per mL/min"
                name = c["name"]
            else:
                v = self.vars[item]
                per, unit = 1.0 / self.span[item], f"per {v.unit}"
                name = f"{v.label} at its {'upper' if kind == 'upper' else 'lower'} bound ({v.upper if kind == 'upper' else v.lower:g} {v.unit})"
            value = m * per * obj_scale
            out.append(
                {
                    "name": name,
                    "kind": kind if kind != "con" else item["kind"],
                    "multiplier": float(m),
                    "value": float(value),
                    "unit": f"{obj_unit} {unit}",
                    "binding": bool(m > 1e-6),
                }
            )
        out.sort(key=lambda r: -abs(r["value"]))
        return out


def optimize(
    problem: Problem,
    progress: Optional[Callable[[dict], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    runner: BatchRunner | None = None,
) -> dict:
    """Find the best operating point of ``problem``.

    Returns a dictionary with, among others: ``start`` and ``optimum`` (values, objective,
    metrics, flows, m-values and limit status), ``feasible``, ``message``, ``history`` (one
    entry per accepted iteration), ``binding`` (limits that bind and what relaxing each is
    worth), ``evaluations`` (CSS simulations), ``elapsed`` (s) and ``optimum_config`` (the
    best setup as an SMB simulator setup dictionary).

    On macOS and Windows, call it under ``if __name__ == "__main__":`` when it may use
    several processes (``problem.workers`` other than 1).
    """
    return Optimizer(problem, progress=progress, cancel=cancel, runner=runner).run()


def point_view(problem: Problem, values: dict, point: dict) -> dict:
    """Display data for an evaluated operating point: flows, m-values, products and the CSS profile."""
    cfg = problem.config_at(values)
    sim = Simulator(cfg)
    C, Q = point["C"], point["Q"]
    Cd = sim._display_C(C, sim.rhs(C, Q))
    d = cfg.derived()
    return {
        "values": values,
        "derived": d,
        "metrics": point["metrics"],
        "x": sim.positions(),
        "C": Cd.reshape(sim.nc, -1),
        "column_pitch": sim.pitch,
        "cells_per_column": sim.ncell,
        "zones": list(cfg.zones),
        "ports": sim.port_info(),
        "config": cfg.to_dict(),
    }


def simulate_point(problem: Problem, values: dict, tol: float = 1e-7) -> dict:
    """CSS of one operating point (no optimization)."""
    cfg = problem.config_at(values)
    r = BatchSimulator([cfg]).css(tol=tol)
    return point_view(problem, values, {"metrics": _slim(r["metrics"][0]), "C": r["C"][:, 0], "Q": r["Q"][:, 0]})

"""Operating window in the (m2, m3) plane.

For a classic four-zone unit the dimensionless flow-rate ratios

    m_j = (Q_j t* - eps V) / ((1 - eps) V)

of zones II and III decide where every component goes.  Equilibrium (triangle) theory
predicts complete separation when the weakest-held extract component is held in zone III
(m3 below its Henry constant) and the strongest-held raffinate component is carried
through zone II (m2 above its Henry constant), with m1 and m4 large and small enough to
regenerate the solid and the liquid.

``henry_constants`` gives the slope of each isotherm in pure desorbent, which is where the
dilute solutes see the adsorbent.  ``scan`` maps the window with the full model instead: it
simulates a grid of (m2, m3) points at fixed m1, m4 and switch time and records whether each
point meets the product specifications.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence

import numpy as np

from smbsim import SMBConfig
from .problem import Problem, METRICS

if TYPE_CHECKING:
    from .optimizer import BatchRunner


def henry_constants(cfg: SMBConfig) -> list[dict]:
    """dq*/dC of every non-desorbent component, at infinite dilution in the desorbent."""
    cD = np.array([c.des_frac * c.rho for c in cfg.components])
    denom = 1.0 + sum(c.keq * x for c, x in zip(cfg.components, cD))
    return [
        {"name": c.name, "role": c.role, "H": c.qsat * c.keq / denom} for c in cfg.components if c.role != "desorbent"
    ]


def is_classic(cfg: SMBConfig) -> bool:
    """True for a closed-loop four-zone unit with ports D, E, F, R (raffinate as balance outlet)."""
    kinds = [(p.zone, p.kind, bool(p.balance)) for p in cfg.ports]
    return (
        not cfg.open_loop
        and len(cfg.zones) == 4
        and len(cfg.ports) == 4
        and sorted(kinds)
        == [(0, "desorbent", False), (1, "extract", False), (2, "feed", False), (3, "raffinate", True)]
    )


def flows_from_m(cfg: SMBConfig, m: Sequence[float], t_star: float) -> dict[str, float]:
    """Zone I flow and port flows (D, E, F, R) of a classic unit with m-values ``m`` and switch time ``t_star``."""
    V, eps = cfg.length * cfg.area, cfg.porosity
    Q = [(mj * (1 - eps) * V + eps * V) / t_star for mj in m]
    return {"Q1": Q[0], "QD": Q[0] - Q[3], "QE": Q[0] - Q[1], "QF": Q[2] - Q[1], "QR": Q[2] - Q[3]}


def apply_m(cfg: SMBConfig, m: Sequence[float], t_star: float) -> SMBConfig:
    """A copy of ``cfg`` operated at m-values ``m`` and switch time ``t_star``."""
    f = flows_from_m(cfg, m, t_star)
    c = SMBConfig.from_dict(cfg.to_dict())
    c.Q1, c.step_time = f["Q1"], t_star
    for p in c.ports:
        if p.kind == "desorbent":
            p.flow = f["QD"]
        elif p.kind == "extract":
            p.flow = f["QE"]
        elif p.kind == "feed":
            p.flow = f["QF"]
    return c


def scan(
    problem: Problem,
    values: dict,
    n: int = 10,
    m2_range: Optional[tuple[float, float]] = None,
    m3_range: Optional[tuple[float, float]] = None,
    runner: "BatchRunner | None" = None,
    warm: Any = None,
    progress: Optional[Callable[[dict], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """Simulate an n x n grid in the (m2, m3) plane (points with m3 > m2 only).

    m1, m4 and the switch time stay at the operating point ``values``.  Each grid cell is
    simulated to cyclic steady state with the full model and marked feasible when it meets
    every enabled purity and recovery limit of ``problem``.
    """
    from .optimizer import BatchRunner

    cfg = problem.config_at(values)
    if not is_classic(cfg):
        raise ValueError("The operating window map needs a classic closed-loop four-zone layout (D, E, F, R).")
    d = cfg.derived()
    m = d["m_values"]
    H = henry_constants(cfg)
    hv = [h["H"] for h in H]
    w = max(m[2] - m[1], 0.02)  # zoom on the current operating point
    lo, hi = m[1] - 0.7 * w, m[2] + 0.7 * w

    def axis(centre, rng):
        a, b = rng
        h = (b - a) / (n - 1)
        k = int(round((centre - a) / h))  # put the current point on a grid node
        return centre + h * (np.arange(n) - k)

    m2s = axis(m[1], m2_range or (lo, hi))
    m3s = axis(m[2], m3_range or (lo, hi))
    pts, cells = [], []
    for i, a in enumerate(m2s):
        for j, b in enumerate(m3s):
            if b > a + 1e-9:
                c = apply_m(cfg, [m[0], a, b, m[3]], cfg.step_time)
                if c.validate():
                    continue
                pts.append(c)
                cells.append((i, j))
    if not pts:
        raise ValueError("No valid operating points in the chosen range.")
    t0 = time.time()
    own = runner is None
    runner = runner or BatchRunner(problem.workers)
    res = []
    size = max(8, 4 * runner.workers)
    try:
        for k in range(0, len(pts), size):
            if cancel is not None and cancel():
                raise InterruptedError("cancelled")
            if progress:
                progress({"stage": "scanning", "points": len(pts), "done": k, "elapsed": time.time() - t0})
            part, _ = runner.run(pts[k : k + size], warm, max(problem.css_tol * 100, 1e-6), cancel=cancel)
            res += part
    finally:
        if own:
            runner.close()
    specs = [s for s in problem.specs if s.enabled]
    grid = []
    for (i, j), r, c in zip(cells, res, pts):
        met = {k: r["metrics"][k] for k in METRICS}
        margin = min([met[s.metric] - s.minimum for s in specs] or [0.0])
        grid.append(
            {
                "i": i,
                "j": j,
                "m2": float(m2s[i]),
                "m3": float(m3s[j]),
                "metrics": met,
                "feed": c.total_flow("feed"),
                "feasible": margin >= 0,
                "margin": margin,
            }
        )
    return {
        "m2": m2s.tolist(),
        "m3": m3s.tolist(),
        "m1": m[0],
        "m4": m[3],
        "t_star": cfg.step_time,
        "grid": grid,
        "henry": H,
        "point": {"m2": m[1], "m3": m[2]},
        "specs": [{"metric": s.metric, "minimum": s.minimum} for s in specs],
        "elapsed": time.time() - t0,
    }

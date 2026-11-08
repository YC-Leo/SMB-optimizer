"""Definition of an operating-condition optimization problem.

A problem has four parts:

* the **process**: an SMB Simulator setup (components, columns, zones, ports, model);
* the **decision variables**: the zone I flow, the flow of every port except the balance
  outlet, and the switch time, each with lower and upper bounds and a start value;
* the **objective**: maximize feed throughput, minimize desorbent use, or maximize one
  product-quality figure;
* the **constraints**: minimum purity and recovery for the extract and raffinate, the
  largest and smallest flow allowed in any zone (pressure drop and pump range), and an
  optional limit on desorbent use.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from smbsim import SMBConfig, case_1, case_2
from smbsim.config import ROMAN
from smbsim.config import INLET_KINDS

METRICS = ("extract_purity", "extract_recovery", "raffinate_purity", "raffinate_recovery")
METRIC_LABEL = {
    "extract_purity": "Extract purity",
    "extract_recovery": "Extract recovery",
    "raffinate_purity": "Raffinate purity",
    "raffinate_recovery": "Raffinate recovery",
}
OBJECTIVES = {
    "max_feed": "Maximize feed throughput",
    "min_desorbent": "Minimize desorbent use (desorbent / feed)",
    "max_extract_purity": "Maximize extract purity",
    "max_extract_recovery": "Maximize extract recovery",
    "max_raffinate_purity": "Maximize raffinate purity",
    "max_raffinate_recovery": "Maximize raffinate recovery",
}
KIND_LABEL = {"desorbent": "Desorbent in", "feed": "Feed in", "extract": "Extract out", "raffinate": "Raffinate out"}


@dataclass
class Variable:
    """One decision variable: a flow or the switch time, with its bounds and start value."""

    key: str  # 'Q1' | 'port:<index>' | 'step_time'
    label: str
    unit: str
    start: float
    lower: float
    upper: float
    optimize: bool = True


@dataclass
class Spec:
    """A minimum product purity or recovery (in %), applied when ``enabled``."""

    metric: str  # one of METRICS
    minimum: float = 90.0  # %
    enabled: bool = True


@dataclass
class Problem:
    """An operating-condition optimization problem (see the module docstring for its parts)."""

    process: dict  # SMBConfig.to_dict()
    variables: List[Variable]
    objective: str = "max_feed"
    specs: List[Spec] = field(default_factory=lambda: [Spec(m, 90.0, m.endswith("purity")) for m in METRICS])
    max_zone_flow: Optional[float] = 7.0  # mL/min, pressure-drop limit (None = no limit)
    min_zone_flow: float = 0.01  # mL/min, smallest flow in any zone or balance outlet
    max_desorbent_ratio: Optional[float] = None  # desorbent / feed upper limit (None = no limit)
    # solver settings
    max_iterations: int = 40
    css_tol: float = 1e-8  # CSS tolerance for every evaluation
    fd_step: float = 0.001  # relative finite-difference step
    ftol: float = 1e-6  # SLSQP stopping tolerance (scaled objective)
    workers: int = 0  # parallel processes (0 = automatic)

    # ------------------------------------------------------------- mapping
    def base_config(self) -> SMBConfig:
        """The process setup as an ``SMBConfig`` (a fresh copy, at the stored operating point)."""
        return SMBConfig.from_dict(copy.deepcopy(self.process))

    def opt_vars(self) -> List[Variable]:
        """The decision variables the optimizer may change."""
        return [v for v in self.variables if v.optimize]

    def config_at(self, values: dict) -> SMBConfig:
        """Process setup with the given variable values (others at their start values)."""
        cfg = self.base_config()
        for v in self.variables:
            val = values.get(v.key, v.start)
            if v.key == "Q1":
                cfg.Q1 = val
            elif v.key == "step_time":
                cfg.step_time = val
            else:
                cfg.ports[int(v.key.split(":")[1])].flow = val
        return cfg

    def start_values(self) -> dict:
        """Start value of every variable, keyed by ``Variable.key``."""
        return {v.key: v.start for v in self.variables}

    # ------------------------------------------------------- analytic figures
    @staticmethod
    def flows(cfg: SMBConfig) -> dict:
        """Zone flows, balance-outlet flow, feed, desorbent and desorbent/feed ratio of a setup."""
        plan = cfg.flow_plan()
        feed, des = cfg.total_flow("feed"), cfg.total_flow("desorbent")
        return {
            "zone_flows": list(plan["zone_flows"]),
            "balance_flow": plan["QB"],
            "feed": feed,
            "desorbent": des,
            "desorbent_ratio": des / feed if feed > 0 else math.inf,
        }

    def objective_is_analytic(self) -> bool:
        """True when the objective follows from the flows alone (no simulation needed)."""
        return self.objective in ("max_feed", "min_desorbent")

    # ------------------------------------------------------------- checks
    def validate(self) -> List[str]:
        """Check the problem; returns a list of readable error messages (empty when valid)."""
        errs = []
        try:
            cfg = self.base_config()
            errs += cfg.validate()
        except Exception as e:  # noqa: BLE001
            return [f"Process setup: {e}"]
        if self.objective not in OBJECTIVES:
            errs.append("Unknown objective.")
        ov = self.opt_vars()
        if not ov:
            errs.append("Select at least one decision variable to optimize.")
        for v in self.variables:
            if not v.lower < v.upper and v.optimize:
                errs.append(f"{v.label}: the lower bound must be below the upper bound.")
            if v.lower < 0:
                errs.append(f"{v.label}: bounds cannot be negative.")
            if v.key == "step_time" and v.lower <= 0:
                errs.append("Switch time: the lower bound must be positive.")
        keys = {v.key for v in ov}
        feed_keys = {f"port:{i}" for i, p in enumerate(cfg.ports) if p.kind == "feed"}
        des_keys = {f"port:{i}" for i, p in enumerate(cfg.ports) if p.kind == "desorbent"}
        if self.objective == "max_feed" and not keys & feed_keys:
            errs.append("To maximize feed throughput, the feed flow must be a decision variable.")
        if self.objective == "min_desorbent" and not keys & (des_keys | feed_keys):
            errs.append("To minimize desorbent use, the desorbent or feed flow must be a decision variable.")
        if self.objective.startswith("max_") and self.objective[4:] in METRICS:
            pass
        if self.max_zone_flow is not None and self.max_zone_flow <= self.min_zone_flow:
            errs.append("The largest zone flow must be above the smallest.")
        for s in self.specs:
            if s.enabled and not 0 < s.minimum <= 100:
                errs.append(f"{METRIC_LABEL[s.metric]}: the minimum must be between 0 and 100 %.")
        if not 1e-10 <= self.css_tol <= 1e-4:
            errs.append("CSS tolerance must be between 1e-10 and 1e-4.")
        if not 1e-4 <= self.fd_step <= 0.05:
            errs.append("Gradient step must be between 0.01 % and 5 %.")
        if not 1 <= self.max_iterations <= 200:
            errs.append("Iterations must be between 1 and 200.")
        return errs

    # --------------------------------------------------------- serialization
    def to_dict(self) -> dict:
        """Plain-dictionary form, as stored in a problem file."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Problem":
        """Build a problem from ``to_dict()`` output; unknown keys are ignored."""
        d = copy.deepcopy(d)
        d["variables"] = [Variable(**v) for v in d.get("variables", [])]
        d["specs"] = [Spec(**s) for s in d.get("specs", [])] or [Spec(m, 90.0, m.endswith("purity")) for m in METRICS]
        known = set(cls.__dataclass_fields__)
        p = cls(**{k: v for k, v in d.items() if k in known})
        if not p.variables:
            p.variables = default_variables(p.base_config())
        return p


def default_variables(cfg: SMBConfig, spread: float = 0.3) -> List[Variable]:
    """Zone I flow (closed loop), every port flow except the balance outlet, and the switch time."""
    labels = cfg.port_labels()
    out = []
    if not cfg.open_loop:
        out.append(
            Variable(
                "Q1", "Zone I flow", "mL/min", cfg.Q1, round(cfg.Q1 * (1 - spread), 4), round(cfg.Q1 * (1 + spread), 4)
            )
        )
    for i, p in enumerate(cfg.ports):
        if p.balance and p.kind not in INLET_KINDS:
            continue
        out.append(
            Variable(
                f"port:{i}",
                f"{labels[i]} · {KIND_LABEL[p.kind]} (zone {ROMAN[p.zone]})",
                "mL/min",
                p.flow,
                round(p.flow * (1 - spread), 4),
                round(p.flow * (1 + spread), 4),
            )
        )
    out.append(
        Variable(
            "step_time",
            "Switch time t*",
            "min",
            cfg.step_time,
            round(cfg.step_time * (1 - spread), 4),
            round(cfg.step_time * (1 + spread), 4),
        )
    )
    return out


# =================================================================== presets
def _set(vars_: List[Variable], key: str, lower: float, upper: float, optimize: bool = True) -> List[Variable]:
    for v in vars_:
        if v.key == key:
            v.lower, v.upper, v.optimize = lower, upper, optimize
    return vars_


def benchmark_feed_problem() -> Problem:
    """Case 2 started from its operating point: maximize feed with both group purities >= 90 %.

    Flow bounds are the start values +/- 0.5 mL/min (zone I, desorbent) and +/- 0.387 mL/min
    (feed, extract); every zone flow stays between 0.01 and 7 mL/min.  The benchmark optimum
    of this problem is Case 3.
    """
    cfg = case_2(flow_model="volume_change")
    v = default_variables(cfg)
    r = 0.15**0.5
    _set(v, "Q1", 6.96 - 0.5, 6.96 + 0.5)
    _set(v, "port:0", 2.14 - 0.5, 2.14 + 0.5)  # desorbent
    _set(v, "port:1", round(0.721 - r, 6), round(0.721 + r, 6))  # extract
    _set(v, "port:2", 0.0, round(0.24 + r, 6))  # feed
    _set(v, "step_time", 0.5, 4.0)
    specs = [
        Spec("extract_purity", 90.0, True),
        Spec("extract_recovery", 90.0, False),
        Spec("raffinate_purity", 90.0, True),
        Spec("raffinate_recovery", 90.0, False),
    ]
    return Problem(
        process=cfg.to_dict(), variables=v, objective="max_feed", specs=specs, max_zone_flow=7.0, min_zone_flow=0.01
    )


def desorbent_problem() -> Problem:
    """Case 2 at its feed flow: use as little desorbent as possible with both purities >= 90 %."""
    p = benchmark_feed_problem()
    p.objective = "min_desorbent"
    _set(p.variables, "port:2", 0.0, 0.627, optimize=False)
    _set(p.variables, "port:0", 0.5, 4.0)
    return p


def case1_feed_problem() -> Problem:
    """Case 1: maximize feed with extract purity >= 98 % and both recoveries >= 99 % (the start misses the purity)."""
    cfg = case_1()
    v = default_variables(cfg)
    _set(v, "Q1", 4.0, 7.0)
    _set(v, "port:0", 3.0, 7.0)
    _set(v, "port:1", 1.5, 5.0)
    _set(v, "port:2", 0.5, 3.0)
    _set(v, "step_time", 1.0, 4.0)
    specs = [
        Spec("extract_purity", 98.0, True),
        Spec("extract_recovery", 99.0, True),
        Spec("raffinate_purity", 99.0, False),
        Spec("raffinate_recovery", 99.0, True),
    ]
    return Problem(
        process=cfg.to_dict(), variables=v, objective="max_feed", specs=specs, max_zone_flow=7.0, min_zone_flow=0.01
    )


PROBLEMS = {
    "case2_feed": (
        "Case 2 · maximize feed (benchmark problem)",
        "7 components · start at Case 2, purities ≥ 90 % · benchmark optimum is Case 3",
        benchmark_feed_problem,
    ),
    "case2_desorbent": ("Case 2 · minimize desorbent", "7 components · fixed feed, purities ≥ 90 %", desorbent_problem),
    "case1_feed": (
        "Case 1 · maximize feed",
        "3 components · extract purity ≥ 98 %, both recoveries ≥ 99 % · the start misses the purity",
        case1_feed_problem,
    ),
}


def problem_preset(name: str) -> Problem:
    """A fresh copy of a built-in example problem (a key of ``PROBLEMS``; unknown names give Case 2)."""
    return PROBLEMS.get(name, PROBLEMS["case2_feed"])[2]()

"""smbopt - operating-condition optimizer for simulated moving bed (SMB) chromatography.

Typical use::

    from smbopt import problem_preset, optimize

    result = optimize(problem_preset("case1_feed"))
    print(result["optimum"]["values"], result["optimum"]["metrics"])

The public names are loaded on first use, so ``smbopt.cli`` can start and report a missing
NumPy or SciPy installation with a clear message instead of a traceback.
"""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.0.0"

_EXPORTS = {
    "Problem": "problem",
    "Variable": "problem",
    "Spec": "problem",
    "METRICS": "problem",
    "METRIC_LABEL": "problem",
    "OBJECTIVES": "problem",
    "PROBLEMS": "problem",
    "problem_preset": "problem",
    "default_variables": "problem",
    "BatchSimulator": "batch",
    "Optimizer": "optimizer",
    "optimize": "optimizer",
    "simulate_point": "optimizer",
    "point_view": "optimizer",
    "BatchRunner": "optimizer",
    "Cancelled": "optimizer",
    "load_problem": "io",
    "problem_from_setup": "io",
}
__all__ = list(_EXPORTS) + ["__version__"]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'smbopt' has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

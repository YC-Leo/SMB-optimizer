"""Reading problem files and writing optimization results.

A problem file is the JSON written by ``Problem.to_dict()`` (the web app's *Export problem*
button writes the same file).  YAML files with the same structure are accepted when PyYAML
is installed (``pip install "smb-optimizer[yaml]"``).  See ``docs/configuration.md``.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from smbsim import SMBConfig

from .problem import METRICS, Problem, default_variables, problem_preset

YAML_SUFFIXES = (".yaml", ".yml")


def to_jsonable(o: Any, exact: bool = False) -> Any:
    """Convert results to plain, JSON-safe Python objects.

    NumPy arrays and scalars become lists and numbers, non-finite floats become ``None``, and
    dictionary keys starting with ``_`` (internal data such as simulator states) are dropped.
    Unless ``exact`` is true, floats are rounded to 9 decimals (arrays to 7) for compact output;
    problem files are written with ``exact=True`` so that they read back unchanged.
    """
    if isinstance(o, dict):
        return {k: to_jsonable(v, exact) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v, exact) for v in o]
    if isinstance(o, np.ndarray):
        if exact:
            return to_jsonable(o.tolist(), exact)
        a = np.where(np.abs(o) < 1e-12, 0.0, o)
        return to_jsonable(np.round(a.astype(float), 7).tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        if not math.isfinite(f):
            return None
        return f if exact else round(f, 9)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _yaml():
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        raise SystemExit(
            "Reading or writing YAML needs PyYAML. Install it with:  python -m pip install pyyaml\n"
            "or use a .json file instead."
        ) from None
    return yaml


def read_data(path: str | Path) -> dict:
    """Read a JSON or YAML file into a dictionary."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in YAML_SUFFIXES:
        data = _yaml().safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level.")
    return data


def write_data(path: str | Path, data: dict) -> None:
    """Write a dictionary as JSON, or as YAML when the file name ends in .yaml or .yml.

    Floats are written at full precision, so a problem file reads back exactly.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in YAML_SUFFIXES:
        text = _yaml().safe_dump(to_jsonable(data, exact=True), sort_keys=False, allow_unicode=True)
    else:
        text = json.dumps(to_jsonable(data, exact=True), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def load_problem(path: str | Path) -> Problem:
    """Load an optimization problem from a JSON or YAML problem file.

    Raises ``ValueError`` when the file is not a problem file (it must contain ``process``,
    an SMB simulator setup).  The problem is not validated here; call ``Problem.validate()``.
    """
    data = read_data(path)
    if "process" not in data:
        hint = (
            " It looks like an SMB simulator setup; convert it with 'smb-optimizer from-setup'."
            if ("components" in data)
            else ""
        )
        raise ValueError(f"{path}: not a problem file (no 'process' section).{hint}")
    try:
        return Problem.from_dict(data)
    except (TypeError, KeyError) as e:
        raise ValueError(f"{path}: could not read the problem: {e}") from None


def problem_from_setup(setup: dict, base: Problem | None = None) -> Problem:
    """Build a problem from an SMB simulator setup, with default decision variables.

    The objective, limits and solver settings are taken from ``base`` (default: the Case 2
    feed problem).  If the setup has no feed port, the objective becomes extract recovery.
    """
    cfg = SMBConfig.from_dict(setup)
    p = Problem.from_dict(base.to_dict()) if base is not None else problem_preset("case2_feed")
    p.process = cfg.to_dict()
    p.variables = default_variables(cfg)
    if p.objective in ("max_feed", "min_desorbent") and not any(port.kind == "feed" for port in cfg.ports):
        p.objective = "max_extract_recovery"
    return p


def summary(result: dict) -> dict:
    """The parts of an ``optimize()`` result worth saving: start, optimum, limits and effort."""
    keep = (
        "success",
        "feasible",
        "message",
        "objective",
        "objective_label",
        "start",
        "optimum",
        "binding",
        "evaluations",
        "elapsed",
        "rejected_steps",
    )
    out = {k: result[k] for k in keep if k in result}
    out["variables"] = result.get("variables", [])
    out["iterations"] = len(result.get("history", [])) - 1
    return to_jsonable(out)


def write_iterations_csv(path: str | Path, result: dict) -> None:
    """Write the search history, one row per accepted iteration (same columns as the web app)."""
    variables = result["variables"]
    head = (
        ["iteration", "objective"]
        + [f"{v['label']} ({v['unit']})" for v in variables]
        + list(METRICS)
        + ["m1", "m2", "m3", "m4", "meets_specs", "simulations", "elapsed_s"]
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for h in result["history"]:
            m = list(h["m_values"])[:4]
            m += [""] * (4 - len(m))
            w.writerow(
                [h["iteration"], h["objective"]]
                + [h["values"].get(v["key"]) for v in variables]
                + [h["metrics"][k] for k in METRICS]
                + m
                + [h["feasible"], h["evaluations"], round(h["elapsed"], 1)]
            )

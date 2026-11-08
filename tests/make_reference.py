"""Regenerate the stored reference results used by tests/test_cases.py.

    python tests/make_reference.py            # both cases, one process (a few minutes)
    python tests/make_reference.py case1      # one case

Only regenerate after an intentional change to the optimizer or the model, and explain the
change of the reference values in the pull request.
"""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy  # noqa: E402
import scipy  # noqa: E402

from smbopt import optimize, problem_preset  # noqa: E402
from smbopt.io import to_jsonable, write_data  # noqa: E402

CASES = {"case1": "case1_feed", "case2": "case2_feed"}
REF_DIR = ROOT / "tests" / "reference"


def reference(preset: str, workers: int = 1) -> dict:
    """Run one example problem and return the values the reference test compares."""
    p = problem_preset(preset)
    p.workers = workers
    t = time.time()
    r = optimize(p)
    pick = lambda s: {k: s[k] for k in ("values", "objective", "metrics", "m_values", "feed", "desorbent_ratio")}
    return to_jsonable(
        {
            "preset": preset,
            "objective": r["objective"],
            "feasible": r["feasible"],
            "start": pick(r["start"]),
            "optimum": pick(r["optimum"]),
            "binding": sorted(b["name"] for b in r["binding"] if b["binding"]),
            "produced_with": {
                "python": platform.python_version(),
                "numpy": numpy.__version__,
                "scipy": scipy.__version__,
                "workers": workers,
                "iterations": len(r["history"]) - 1,
                "simulations": r["evaluations"],
                "seconds": round(time.time() - t),
            },
        },
        exact=True,
    )


def main(argv: list[str]) -> None:
    names = argv or list(CASES)
    for name in names:
        print(f"{name}: optimizing {CASES[name]} ...", flush=True)
        ref = reference(CASES[name])
        out = REF_DIR / f"{name}.json"
        write_data(out, ref)
        print(f"  objective {ref['optimum']['objective']:.6g}, feasible {ref['feasible']}; wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:])

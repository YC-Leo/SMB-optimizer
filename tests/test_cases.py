"""Full optimizations of Case 1 and Case 2, compared with stored reference results.

    python -m pytest -q -m slow          # only these tests (a few minutes)
    python -m pytest -q -m "not slow"    # everything else

The references in tests/reference/ were produced by tests/make_reference.py.  The search
path of a trust-region method can differ slightly between platforms and NumPy/SciPy builds
(floating-point summation order in linear algebra), so the optimum is compared with
tolerances rather than exactly:

* the start point is a plain simulation and must agree to 0.01 percentage point;
* the optimized objective must agree to 0.5 % (relative);
* every enabled purity/recovery limit must be met (to 0.01 point) and agree to 0.1 point;
* the other purities and recoveries must agree to 0.5 point;
* every decision variable must agree to 3 % of its bound range, and m2, m3 to 0.005.

Several variables are weakly determined at the optimum (for example, zone I flow and switch
time can be traded against each other at almost the same m-values), so the variable
tolerance is wider than the objective tolerance.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smbopt import METRICS, optimize, problem_preset  # noqa: E402
from smbopt.io import read_data  # noqa: E402

REF = Path(__file__).resolve().parent / "reference"


def _run(preset: str) -> dict:
    p = problem_preset(preset)
    p.workers = int(os.environ.get("SMBOPT_TEST_WORKERS", "0"))
    return p, optimize(p)


@pytest.mark.slow
@pytest.mark.parametrize("case", ["case1", "case2"])
def test_case_matches_reference(case):
    ref = read_data(REF / f"{case}.json")
    p, r = _run(ref["preset"])
    start, opt = r["start"], r["optimum"]

    for m in METRICS:
        assert start["metrics"][m] == pytest.approx(ref["start"]["metrics"][m], abs=0.01), f"start {m}"

    assert r["feasible"], r["message"]
    assert opt["objective"] == pytest.approx(ref["optimum"]["objective"], rel=5e-3)

    enabled = {s.metric: s.minimum for s in p.specs if s.enabled}
    for m in METRICS:
        if m in enabled:
            assert opt["metrics"][m] >= enabled[m] - 0.01, f"{m} below its limit"
            assert opt["metrics"][m] == pytest.approx(ref["optimum"]["metrics"][m], abs=0.1), m
        else:
            assert opt["metrics"][m] == pytest.approx(ref["optimum"]["metrics"][m], abs=0.5), m

    for v in p.opt_vars():
        tol = 0.03 * (v.upper - v.lower)
        assert opt["values"][v.key] == pytest.approx(ref["optimum"]["values"][v.key], abs=tol), v.label
    for j in (1, 2):
        assert opt["m_values"][j] == pytest.approx(ref["optimum"]["m_values"][j], abs=5e-3), f"m{j + 1}"

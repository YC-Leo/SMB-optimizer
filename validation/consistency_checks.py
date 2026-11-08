"""Consistency checks of the optimizer on the benchmark problem.

    python validation/consistency_checks.py

1. Specification sweep: re-optimize with both purity specifications at 88, 90 and 92 %.
   The best feed must fall as the specifications tighten, and the change between neighbours
   must agree with the value the multipliers put on one percentage point of purity.
2. Different starts: start from the benchmark optimum itself and from a deliberately poor point.
   A good optimizer ends near the same feed from every start.

Results are written to validation/consistency_results.md.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smbopt import problem_preset, Optimizer  # noqa: E402


def solve(spec=90.0, start=None):
    p = problem_preset("case2_feed")
    for s in p.specs:
        if s.enabled:
            s.minimum = spec
    if start:
        for v in p.variables:
            if v.key in start:
                v.start = start[v.key]
        cfg = p.config_at(p.start_values())
        p.process = cfg.to_dict()
    t = time.time()
    r = Optimizer(p).run()
    shadow = sum(b["value"] for b in r["binding"] if b["kind"] == "spec")
    print(
        f"  spec {spec:g} %, start feed {r['start']['feed']:.4f}: best feed {r['optimum']['feed']:.4f} "
        f"(purities {r['optimum']['metrics']['extract_purity']:.2f} / {r['optimum']['metrics']['raffinate_purity']:.2f}), "
        f"{len(r['history']) - 1} iterations, {r['evaluations']} simulations, {time.time() - t:.0f} s",
        flush=True,
    )
    return r, shadow


def main():
    lines = ["# Optimizer consistency checks (benchmark problem)", ""]
    print("1) specification sweep")
    sweep = {s: solve(s) for s in (88.0, 90.0, 92.0)}
    lines += [
        "## 1. Specification sweep",
        "",
        "| Both purities at least | Best feed (mL/min) | Extract / raffinate purity | Value of 1 point (sum of multipliers, mL/min) | Iterations | Simulations |",
        "|---|---|---|---|---|---|",
    ]
    for s, (r, sh) in sweep.items():
        m = r["optimum"]["metrics"]
        lines.append(
            f"| {s:g} % | {r['optimum']['feed']:.4f} | {m['extract_purity']:.2f} / {m['raffinate_purity']:.2f} | "
            f"{sh:.4f} | {len(r['history']) - 1} | {r['evaluations']} |"
        )
    f88, f90, f92 = (sweep[s][0]["optimum"]["feed"] for s in (88.0, 90.0, 92.0))
    lines += [
        "",
        f"Observed change per point: {(f88 - f90) / 2:.4f} mL/min between 88 and 90 %, "
        f"{(f90 - f92) / 2:.4f} between 90 and 92 %; the multipliers at 90 % predict {sweep[90.0][1]:.4f}.",
        f"Monotonic (tighter specification, less feed): {'yes' if f88 > f90 > f92 else 'no'}.",
        "",
    ]

    print("2) different starts")
    starts = {
        "Benchmark optimum (Case 3)": {
            "Q1": 6.971362,
            "port:0": 1.64,
            "port:1": 0.880286,
            "port:2": 0.387384,
            "step_time": 1.92165,
        },
        "Poor start (low feed, long switch)": {
            "Q1": 6.6,
            "port:0": 2.4,
            "port:1": 0.6,
            "port:2": 0.10,
            "step_time": 2.2,
        },
    }
    lines += [
        "## 2. Different starting points",
        "",
        "| Start | Start feed | Best feed | Extract / raffinate purity | Iterations | Simulations |",
        "|---|---|---|---|---|---|",
    ]
    r90 = sweep[90.0][0]
    lines.append(
        f"| Case 2 operating point | {r90['start']['feed']:.4f} | {r90['optimum']['feed']:.4f} | "
        f"{r90['optimum']['metrics']['extract_purity']:.2f} / {r90['optimum']['metrics']['raffinate_purity']:.2f} | "
        f"{len(r90['history']) - 1} | {r90['evaluations']} |"
    )
    for label, st in starts.items():
        r, _ = solve(90.0, st)
        m = r["optimum"]["metrics"]
        lines.append(
            f"| {label} | {r['start']['feed']:.4f} | {r['optimum']['feed']:.4f} | {m['extract_purity']:.2f} / "
            f"{m['raffinate_purity']:.2f} | {len(r['history']) - 1} | {r['evaluations']} |"
        )
    out = ROOT / "validation" / "consistency_results.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()

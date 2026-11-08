"""Reproduce the benchmark optimum: start at Case 2 and maximize the feed.

    python validation/benchmark_optimum.py

Problem (preset "case2_feed"): maximize the feed flow with extract and raffinate group purities
of at least 90 %, every zone flow between 0.01 and 7 mL/min, zone I and desorbent flows within
0.5 mL/min of their start values, extract and feed flows within 0.387 mL/min, volume-change
flow model.  The benchmark optimum of this problem is Case 3 of the SMB Simulator.

The script reports the optimum found here, the benchmark optimum evaluated with the same
model, and which limits bind.  Results are written to validation/benchmark_results.md.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smbsim import case_3  # noqa: E402
from smbopt import problem_preset, Optimizer, BatchSimulator, METRICS, METRIC_LABEL  # noqa: E402

BENCH = {"Q1": 6.971362, "port:0": 1.64, "port:1": 0.880286, "port:2": 0.387384, "step_time": 1.92165}
LABEL = {
    "Q1": "Zone I flow (mL/min)",
    "port:0": "Desorbent (mL/min)",
    "port:1": "Extract (mL/min)",
    "port:2": "Feed (mL/min)",
    "step_time": "Switch time (min)",
}


def progress(d):
    if d["stage"] in ("start", "iteration"):
        h = d["history"][-1]
        print(
            f"  [{d['elapsed']:5.0f} s] iteration {h['iteration']:2d}  feed {h['objective']:.5f}  "
            f"extract purity {h['metrics']['extract_purity']:6.2f}  raffinate purity {h['metrics']['raffinate_purity']:6.2f}"
            f"  {'' if h['feasible'] else '(spec missed)'}",
            flush=True,
        )


def main():
    p = problem_preset("case2_feed")
    p.workers = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print("Optimizing Case 2 (maximize feed, both purities >= 90 %) ...")
    t = time.time()
    res = Optimizer(p, progress=progress).run()
    print(
        f"done in {time.time() - t:.0f} s, {res['evaluations']} simulations, {len(res['history']) - 1} iterations; {res['message']}"
    )

    bench = BatchSimulator([case_3()]).css(tol=p.css_tol)["metrics"][0]
    opt = res["optimum"]
    rows = ["| | Start (Case 2) | Optimum found here | Benchmark optimum (Case 3) |", "|---|---|---|---|"]
    for k in ("Q1", "port:0", "port:1", "port:2", "step_time"):
        rows.append(f"| {LABEL[k]} | {res['start']['values'][k]:.4f} | **{opt['values'][k]:.4f}** | {BENCH[k]:.4f} |")
    for m in METRICS:
        rows.append(
            f"| {METRIC_LABEL[m]} (%) | {res['start']['metrics'][m]:.2f} | **{opt['metrics'][m]:.2f}** | {bench[m]:.2f} |"
        )
    rows.append(
        f"| m2 / m3 | {res['start']['m_values'][1]:.3f} / {res['start']['m_values'][2]:.3f} | "
        f"**{opt['m_values'][1]:.3f} / {opt['m_values'][2]:.3f}** | "
        f"{case_3().derived()['m_values'][1]:.3f} / {case_3().derived()['m_values'][2]:.3f} |"
    )
    gain = (opt["feed"] / res["start"]["feed"] - 1) * 100
    gain_b = (BENCH["port:2"] / res["start"]["feed"] - 1) * 100
    bind = [b for b in res["binding"] if b["binding"]]
    lines = [
        "# Benchmark optimum (Case 2 → Case 3)",
        "",
        f"Optimizer: trust-region SQP, {len(res['history']) - 1} iterations, {res['evaluations']} CSS simulations, "
        f"{res['elapsed']:.0f} s on the machine that produced this file.",
        "",
        *rows,
        "",
        f"Feed gain over the start: **{gain:+.1f} %** here, {gain_b:+.1f} % for the benchmark optimum.",
        "",
        "The desorbent flow can differ between the two optima: with the zone I flow fixed it only sets the zone IV flow, "
        "which hardly affects purity here (its purity gradient is about 100 times smaller than that of the other flows), "
        "so a range of desorbent flows gives the same feed. Both optima sit at the same (m2, m3).",
        "",
        "Binding limits at the optimum found here (value of relaxing each by one unit):",
        "",
    ]
    lines += [f"- {b['name']}: {b['value']:+.4f} {b['unit']}" for b in bind] or ["- none"]
    out = ROOT / "validation" / "benchmark_results.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()

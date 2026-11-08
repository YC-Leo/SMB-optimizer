"""Command-line interface: ``smb-optimizer`` (or ``python -m smbopt``).

    smb-optimizer example case1 -o case1.json   # write a ready-to-run problem file
    smb-optimizer validate case1.json           # check a problem file
    smb-optimizer run case1.json                # optimize; results go to results/case1/
    smb-optimizer from-setup setup.json -o problem.json   # problem from an SMB-simulator setup
    smb-optimizer gui                           # local web app at http://127.0.0.1:8051

Exit status: 0 on success, 1 on an input or runtime error, 2 when the run finished but the
best point found does not meet every limit.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Sequence

from . import __version__

#: example name -> (preset key, one-line description)
EXAMPLES = {
    "case1": ("case1_feed", "Case 1: 3 components, maximize feed, extract purity >= 98 %, recoveries >= 99 %"),
    "case2": ("case2_feed", "Case 2: 7 components, maximize feed, both group purities >= 90 %"),
    "case2-desorbent": ("case2_desorbent", "Case 2: fixed feed, minimize desorbent use, both purities >= 90 %"),
}


def _check_dependencies() -> None:
    """Exit with an install hint if NumPy or SciPy (the numerical solver) is missing."""
    missing = []
    for mod in ("numpy", "scipy"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        names = " and ".join("NumPy" if m == "numpy" else "SciPy" for m in missing)
        raise SystemExit(
            f"smb-optimizer needs {names}, which {'is' if len(missing) == 1 else 'are'} not installed.\n"
            f"Install with:  python -m pip install {' '.join(missing)}"
        )


# ------------------------------------------------------------------ commands
def cmd_example(a: argparse.Namespace) -> int:
    from .io import write_data
    from .problem import problem_preset

    key = EXAMPLES[a.name][0]
    out = Path(a.output or f"{a.name}.json")
    write_data(out, problem_preset(key).to_dict())
    print(f"Wrote {out}  ({EXAMPLES[a.name][1]})")
    print(f"Run it with:  smb-optimizer run {out}")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    from .io import load_problem
    from .problem import OBJECTIVES

    p = load_problem(a.file)
    errs = p.validate()
    if errs:
        print(f"{a.file}: {len(errs)} problem(s)")
        for e in errs:
            print(f"  - {e}")
        return 1
    cfg = p.base_config()
    print(f"{a.file}: OK")
    print(f"  objective   {OBJECTIVES[p.objective]}")
    print(
        f"  process     {len(cfg.components)} components, {cfg.n_columns} columns, zones {'-'.join(map(str, cfg.zones))}"
    )
    print(f"  variables   {', '.join(v.label for v in p.opt_vars())}")
    specs = [f"{s.metric.replace('_', ' ')} >= {s.minimum:g} %" for s in p.specs if s.enabled]
    print(f"  limits      {'; '.join(specs) or 'none'}")
    return 0


def _apply_overrides(p, a: argparse.Namespace) -> None:
    if a.workers is not None:
        p.workers = a.workers
    if a.max_iterations is not None:
        p.max_iterations = a.max_iterations


def _print_progress(d: dict) -> None:
    if d["stage"] in ("start", "iteration"):
        h = d["history"][-1]
        m = h["metrics"]
        print(
            f"  [{d['elapsed']:6.0f} s] iteration {h['iteration']:2d}  objective {h['objective']:.6g}  "
            f"purity E/R {m['extract_purity']:6.2f} / {m['raffinate_purity']:6.2f}  "
            f"recovery E/R {m['extract_recovery']:6.2f} / {m['raffinate_recovery']:6.2f}"
            f"{'' if h['feasible'] else '  (limit missed)'}",
            flush=True,
        )


def _print_result(res: dict) -> None:
    from .problem import METRIC_LABEL, METRICS

    s, o = res["start"], res["optimum"]
    print(f"\n{res['objective_label']}: {s['objective']:.6g} -> {o['objective']:.6g}")
    print(f"{'':42s}{'start':>12s}{'best':>12s}")
    for v in res["variables"]:
        if v["optimize"]:
            label = f"{v['label']} ({v['unit']})"
            print(f"  {label[:40]:40s}{s['values'][v['key']]:12.5g}{o['values'][v['key']]:12.5g}")
    for k in METRICS:
        print(f"  {METRIC_LABEL[k] + ' (%)':40s}{s['metrics'][k]:12.3f}{o['metrics'][k]:12.3f}")
    binding = [b for b in res["binding"] if b["binding"]]
    if binding:
        print("Binding limits (value of relaxing each by one unit):")
        for b in binding:
            print(f"  - {b['name']}: {b['value']:+.4g} {b['unit']}")
    print(
        f"{res['message']}  {len(res['history']) - 1} iterations, {res['evaluations']} simulations, "
        f"{res['elapsed']:.0f} s.  {'All limits met.' if res['feasible'] else 'Some limits are NOT met.'}"
    )


def cmd_run(a: argparse.Namespace) -> int:
    from .io import load_problem, summary, write_data, write_iterations_csv
    from .optimizer import optimize

    p = load_problem(a.file)
    _apply_overrides(p, a)
    errs = p.validate()
    if errs:
        print(f"{a.file}: cannot run, {len(errs)} problem(s):", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    outdir = Path(a.output) if a.output else Path("results") / Path(a.file).stem
    if not a.quiet:
        print(f"Optimizing {a.file} ...")
    t = time.time()
    res = optimize(p, progress=None if a.quiet else _print_progress)
    res["elapsed"] = time.time() - t
    write_data(outdir / "summary.json", summary(res))
    write_iterations_csv(outdir / "iterations.csv", res)
    write_data(outdir / "best_setup.json", res["optimum_config"])
    if not a.quiet:
        _print_result(res)
    print(f"Results written to {outdir}/ (summary.json, iterations.csv, best_setup.json)")
    return 0 if res["feasible"] else 2


def cmd_from_setup(a: argparse.Namespace) -> int:
    from .io import load_problem, problem_from_setup, read_data, write_data

    base = load_problem(a.base) if a.base else None
    p = problem_from_setup(read_data(a.setup), base)
    out = Path(a.output or f"{Path(a.setup).stem}_problem.json")
    write_data(out, p.to_dict())
    print(f"Wrote {out}. Check the bounds and limits, then run:  smb-optimizer run {out}")
    return 0


def cmd_gui(a: argparse.Namespace) -> int:
    from .webapp.server import serve

    try:
        httpd = serve(a.host, a.port)
    except OSError:
        print(f"Port {a.port} is busy. Try:  smb-optimizer gui --port {a.port + 1}", file=sys.stderr)
        return 1
    url = f"http://{a.host}:{a.port}"
    print(f"SMB Optimizer Suite running at {url}  (press Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``smb-optimizer``."""
    ap = argparse.ArgumentParser(
        prog="smb-optimizer",
        description="Find the best operating conditions (flows and switch time) of a simulated moving bed unit.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True, metavar="COMMAND")

    e = sub.add_parser("example", help="write a ready-to-run example problem file")
    e.add_argument(
        "name", choices=list(EXAMPLES), help="; ".join(f"{k}: {v[1]}" for k, v in EXAMPLES.items()).replace("%", "%%")
    )
    e.add_argument("-o", "--output", help="file to write (.json, or .yaml with PyYAML); default NAME.json")
    e.set_defaults(func=cmd_example)

    v = sub.add_parser("validate", help="check a problem file without running it")
    v.add_argument("file", help="problem file (.json, .yaml)")
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run", help="optimize a problem file")
    r.add_argument("file", help="problem file (.json, .yaml)")
    r.add_argument("-o", "--output", help="output folder (default results/<file name>)")
    r.add_argument("-w", "--workers", type=int, help="parallel processes (0 = automatic)")
    r.add_argument("--max-iterations", type=int, help="override the iteration limit")
    r.add_argument("-q", "--quiet", action="store_true", help="print only where the results are")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("from-setup", help="make a problem file from an SMB-simulator setup file")
    s.add_argument("setup", help="setup file exported by SMB-simulator")
    s.add_argument("-o", "--output", help="problem file to write (default <setup>_problem.json)")
    s.add_argument("--base", help="problem file whose objective, limits and solver settings to keep")
    s.set_defaults(func=cmd_from_setup)

    g = sub.add_parser("gui", help="start the local web app")
    g.add_argument("--port", type=int, default=8051)
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    g.set_defaults(func=cmd_gui)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``smb-optimizer`` command; returns the exit status."""
    a = build_parser().parse_args(argv)
    _check_dependencies()
    try:
        return a.func(a)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

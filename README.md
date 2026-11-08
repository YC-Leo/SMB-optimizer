# SMB Optimizer Suite

[![tests](https://github.com/YC-Leo/SMB-optimizer/actions/workflows/tests.yml/badge.svg)](https://github.com/YC-Leo/SMB-optimizer/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

An open-source optimizer that finds the flow rates and switch time of a **simulated moving bed (SMB)** chromatography unit that give the most feed throughput, or use the least desorbent, while the products meet their purity and recovery targets.

You describe the unit, the flows the optimizer may change, the objective and the limits. The optimizer then searches for the best operating point. Every candidate point is simulated to cyclic steady state with the full SMB model, so the optimum accounts for mass transfer, axial dispersion, competitive adsorption and density-driven volume change, not just equilibrium theory. At the optimum it reports which limits are binding and what relaxing each one would be worth.

It runs on Windows, macOS and Linux with Python, NumPy and SciPy. There is a command-line tool for scripted runs and a local web app for interactive work. It is the companion to [**SMB-simulator**](https://github.com/YC-Leo/SMB-simulator), which runs one operating point and shows the unit in motion.

![The web app after optimizing Case 2: feed throughput up 61.6 %, the search path and the full-model operating window in the (m2, m3) plane](assets/screenshot_optimizer.png)

## Install and quick start

You need Python 3.10 or newer.

```bash
git clone https://github.com/YC-Leo/SMB-optimizer.git
cd SMB-optimizer
python -m pip install -r requirements.txt -e .
smb-optimizer run examples/case1_max_feed.json
```

The run takes two to three minutes on a laptop. Its results go to `results/case1_max_feed/`. To use the web app instead, run `smb-optimizer gui`, which opens <http://127.0.0.1:8051>. On Windows you can also double-click `launch_windows.bat`, and on macOS or Linux run `./launch_mac_linux.sh`.

To install without cloning: `python -m pip install "smb-optimizer @ git+https://github.com/YC-Leo/SMB-optimizer"`.

If NumPy or SciPy is missing, `smb-optimizer` says so and prints the one-line install command.

## Examples

Three example problems are in [`examples/`](examples/), and their outputs are in [`examples/output/`](examples/output/). Components are named generically: **Wanted** components leave in the extract, **Unwanted** components in the raffinate, and the **Solvent** is the desorbent.

| Input | What it asks | Result |
|---|---|---|
| [`case1_max_feed.json`](examples/case1_max_feed.json) | **Case 1**, 3 components, 16 columns (5-4-4-3). Find the largest feed with extract purity ≥ 98 % and both recoveries ≥ 99 %. The start point misses the purity (96.9 %). | Feed **1.32 → 2.23 mL/min (+69 %)**, every limit met. |
| [`case2_max_feed.json`](examples/case2_max_feed.json) | **Case 2**, 7 components, 16 columns (3-7-4-2), volume-change flow. Find the largest feed with both group purities ≥ 90 %. | Feed **0.240 → 0.387 mL/min (+61 %)**, both purities exactly at 90 %. |
| [`case2_min_desorbent.json`](examples/case2_min_desorbent.json) | **Case 2** at its fixed feed: use as little desorbent as possible, both purities ≥ 90 %. | Desorbent / feed **8.92 → 3.04** with every limit met, but the run stops at its 40-iteration limit before converging (about 10 minutes with 8 processes), so this is an improved point rather than a proven optimum. |

`smb-optimizer run` prints the search as it goes and then a comparison of the start and best points:

```text
$ smb-optimizer run examples/case1_max_feed.json
Optimizing examples/case1_max_feed.json ...
  [     5 s] iteration  0  objective 1.32  purity E/R  96.92 /  99.99  recovery E/R  99.92 /  99.45  (limit missed)
  [    19 s] iteration  1  objective 1.82  purity E/R  98.51 /  99.91  recovery E/R  99.50 /  99.74
  [    37 s] iteration  2  objective 2.22  purity E/R  98.00 /  99.83  recovery E/R  99.02 /  99.65  (limit missed)
  [    77 s] iteration  3  objective 2.22799  purity E/R  98.03 /  99.83  recovery E/R  99.00 /  99.65  (limit missed)
  [    95 s] iteration  4  objective 2.22927  purity E/R  98.01 /  99.83  recovery E/R  99.00 /  99.65

Maximize feed throughput: 1.32 -> 2.22927
                                                 start        best
  Zone I flow (mL/min)                            6.85      6.8578
  D · Desorbent in (zone I) (mL/min)              5.71        5.71
  E · Extract out (zone II) (mL/min)              3.58      3.5721
  F · Feed in (zone III) (mL/min)                 1.32      2.2293
  Switch time t* (min)                          2.3333      2.3456
  Extract purity (%)                            96.919      98.005
  Extract recovery (%)                          99.917      99.000
  Raffinate purity (%)                          99.985      99.826
  Raffinate recovery (%)                        99.447      99.649
Binding limits (value of relaxing each by one unit):
  - Extract recovery ≥ 99 %: +0.004597 mL/min feed per percentage point
  - Extract purity ≥ 98 %: +0.0009025 mL/min feed per percentage point
Stopped: the trust region shrank to its minimum (the limits are as tight as the simulation accuracy).  4 iterations, 50 simulations, 104 s.  All limits met.
Results written to results/case1_max_feed/ (summary.json, iterations.csv, best_setup.json)
```

| Output file | Content |
|---|---|
| `summary.json` | start and best point: variables, objective, purities, recoveries, zone flows, m-values, the status of every limit, binding limits and their value, effort |
| `iterations.csv` | one row per accepted iteration |
| `best_setup.json` | the best operating point as an SMB-simulator setup |

Other commands:

```bash
smb-optimizer example case2 -o my_problem.json    # start a new problem from an example
smb-optimizer validate my_problem.json            # check it without running it
smb-optimizer run my_problem.json -w 4            # optimize with 4 processes
```

The problem file format is documented in [docs/configuration.md](docs/configuration.md). The same file can be imported into and exported from the web app.

### From Python

```python
from smbopt import load_problem, optimize

if __name__ == "__main__":          # needed on macOS and Windows when several processes are used
    result = optimize(load_problem("examples/case1_max_feed.json"))
    print(result["optimum"]["values"], result["optimum"]["metrics"])
```

## How it connects to SMB-simulator

The two projects share one simulation engine and one setup file format:

- **Same model.** `smbsim/` in this repository is the engine of [SMB-simulator](https://github.com/YC-Leo/SMB-simulator), kept identical file for file. The optimizer adds `smbopt/`: batched simulation of many operating points, the search and the reporting.
- **Simulator → optimizer.** Build and check a unit in SMB-simulator and export its setup. Then `smb-optimizer from-setup my_setup.json -o my_problem.json` (or **Use a setup from the SMB Simulator** in the web app) turns it into a problem. The flows and switch time become decision variables with ±30 % bounds.
- **Optimizer → simulator.** Every run writes `best_setup.json`. Open it in SMB-simulator to watch the unit run at the optimum: the column profiles, the outlet histories and the convergence to steady state.

The web app uses port 8051 and the simulator uses 8050, so both can run side by side.

## How it works

Each evaluation runs the unit to cyclic steady state. Anderson acceleration makes that affordable, and so does simulating the current point together with its gradient perturbations in one batch, warm-started from the previous point.

The search is a trust-region SQP on an exact L1 penalty. It solves a small quadratic model inside a box around the current point, simulates the proposed point, and accepts it only if the penalty merit really improves. Infeasible starts are therefore handled, and the strongly nonlinear purity response cannot throw the search far away.

At the optimum, non-negative least squares on the KKT conditions gives the value of each binding limit in physical units. The details are in [docs/method.md](docs/method.md).

## Validation

`python validation/benchmark_optimum.py` solves the Case 2 feed problem and compares the result with its benchmark optimum, which is the operating point stored as Case 3 in SMB-simulator.

| | Start (Case 2) | Optimum found here | Benchmark optimum (Case 3) |
|---|---|---|---|
| Zone I flow (mL/min) | 6.960 | **7.000** | 6.971 |
| Desorbent (mL/min) | 2.140 | **1.640** | 1.640 |
| Extract (mL/min) | 0.721 | **0.823** | 0.880 |
| Feed (mL/min) | 0.240 | **0.3874** | 0.3874 |
| Switch time (min) | 1.893 | **1.896** | 1.922 |
| Extract / raffinate purity (%) | 91.30 / 96.04 | **90.00 / 90.00** | 90.00 / 90.00 |
| m₂ / m₃ | 0.549 / 0.648 | **0.527 / 0.687** | 0.526 / 0.688 |

The optimizer raises the feed by 61.4 %, the same as the benchmark optimum, and both optima sit at the same (m₂, m₃). The extract flow and switch time differ slightly because one zone I flow / switch time combination can be traded against another at nearly the same m-values.

`python validation/consistency_checks.py` checks the optimizer itself:
- The best feed falls monotonically as the purity limits tighten from 88 % to 92 %.
- The multipliers predict the value of one point of purity to within 1 %.
- Starting at the benchmark optimum, the search stays there.
- From a deliberately poor start it ends 0.75 % below the best.

Full tables are in [validation/](validation/).

The test suite reruns the full Case 1 and Case 2 optimizations on Windows, macOS and Linux and compares them with stored references in [tests/reference/](tests/reference/). The search can take a slightly different path on different platforms and library versions (see [docs/method.md](docs/method.md#reproducibility-across-platforms)), so results are compared within tolerances:
- the objective to within 0.5 %
- purities at their limits to within 0.1 percentage point
- each decision variable to within 3 % of its bound range

## Project status and limitations

**Status:** version 1.0.0, stable. The method, the examples and the file format are tested, and CI covers Python 3.10–3.15 on Windows, macOS and Linux.

**Limitations:**

- **Local optimum.** The search is gradient-based and finds a local optimum near the start point within the given bounds. Different starts usually end at practically the same point, but this is not guaranteed. Try more than one start for a new system.
- **Convergence on flat objectives.** The minimize-desorbent example improves desorbent use about threefold, but it reaches its iteration limit before the search converges. Raise `max_iterations` or tighten the bounds when the objective is flat near the optimum.
- **Run time.** Every evaluation is a full cyclic-steady-state simulation, so a run takes minutes, not seconds. Parallel processes help on multi-core machines.
- **Decision variables.** Only flows and the switch time are optimized. The number of columns per zone is a discrete choice and stays fixed, so compare layouts by running each one.
- **Model scope.** The model is SMB-simulator's: competitive Langmuir isotherm, linear-driving-force mass transfer, axial dispersion, isothermal. There is no pressure-drop model; the largest-zone-flow limit stands in for it.
- **Operating-window map.** It needs a classic closed-loop four-zone unit (desorbent, extract, feed, raffinate).
- **One objective at a time.** There is no Pareto front. To trade throughput against purity, sweep the limits, as `validation/consistency_checks.py` does.
- **Input data.** Results are only as good as the isotherm and mass-transfer parameters. The example parameters are illustrative.

## Project layout

```
smbsim/              simulation engine (identical to SMB-simulator)
smbopt/
  problem.py         decision variables, objectives, limits, example problems
  batch.py           batched CSS solver with Anderson acceleration
  optimizer.py       trust-region SQP, gradients, multipliers, process pool
  window.py          (m2, m3) operating-window map, Henry constants
  io.py              problem files (JSON/YAML) and result files
  cli.py             the smb-optimizer command
  webapp/            local web server (Python standard library) and UI, no external libraries
examples/            example problems (Case 1, Case 2) and their outputs
tests/               unit tests and Case 1/Case 2 reference tests
validation/          benchmark optimum and consistency checks
docs/                problem file format and method
assets/              screenshots
tools/check_repo.py  content check run before every commit and in CI
```

## How to cite

If you use SMB-optimizer in your work, please cite it. GitHub shows a **Cite this repository** button built from [CITATION.cff](CITATION.cff), or you can use:

```bibtex
@software{chiang_smb_optimizer_2026,
  author  = {Chiang, Yadong (Leo)},
  title   = {{SMB-optimizer}: operating-condition optimizer for simulated moving bed chromatography},
  version = {1.0.0},
  year    = {2026},
  url     = {https://github.com/YC-Leo/SMB-optimizer}
}
```

If you also use the simulation model on its own, please cite [SMB-simulator](https://github.com/YC-Leo/SMB-simulator) as well.

## Contributing

Contributions are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains the setup, the checks to run and the pull request workflow. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT. See [LICENSE](LICENSE).

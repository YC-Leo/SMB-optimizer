# Contributing

Thank you for your interest in contributing to SMB-optimizer. Bug reports, questions, examples and
pull requests are all welcome.

## Development setup

You need Python 3.10 or newer and git.

```bash
git clone https://github.com/YC-Leo/SMB-optimizer.git
cd SMB-optimizer
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
git config core.hooksPath .githooks     # run the content check before every commit
```

## Checks to run before a pull request

| What | Command | Time |
|---|---|---|
| Unit tests | `python -m pytest -q -m "not slow"` | under a minute |
| Case 1 and Case 2 against the stored references | `python -m pytest -q -m slow` | a few minutes |
| Formatting | `black --check .` (or `black .` to fix) | seconds |
| Content check | `python tools/check_repo.py` | seconds |
| Benchmark optimum (optional) | `python validation/benchmark_optimum.py` | a few minutes |

Continuous integration runs the first four on Windows, macOS and Linux for every push and pull
request.

If a change is meant to move the optimum (for example a change to the search method), regenerate the
references with `python tests/make_reference.py`, and explain the old and new values in the pull
request.

## Project style and boundaries

- `smbsim/` is the simulation engine shared with
  [SMB-simulator](https://github.com/YC-Leo/SMB-simulator). Keep it identical to the simulator's
  version: changes to the physics belong in that project first. It is excluded from formatting for
  this reason.
- Keep the optimizer (`smbopt/`) to NumPy and SciPy. Optional extras (such as PyYAML) must stay
  optional.
- Keep the web app dependency-free: Python standard library backend, vanilla JavaScript front end,
  no external libraries or CDNs.
- Format Python code with black (line length 120, configured in `pyproject.toml`). Public functions
  get type hints and a docstring.
- Keep component names generic (for example: Wanted, Unwanted, Solvent, Wanted 1-3, Unwanted 1-3),
  and name example scenarios Case 1, Case 2, and so on.
- Do not commit data you are not free to share, personal paths, e-mail addresses, tokens or large
  binary files. `tools/check_repo.py` catches the common cases.

## Branch and pull request workflow

1. Create a branch from `main` for each feature or fix.
2. Keep commits small and focused, with a clear message.
3. Make sure the checks above pass.
4. Explain any effect on the reference results or the benchmark optimum in the pull request.

## Adding an objective or a constraint

1. Add the objective to `OBJECTIVES` in `smbopt/problem.py`, or the limit to `Problem`.
2. Compute it in `Optimizer._obj_value` / `Optimizer.jac` or in `Optimizer._constraint_list` /
   `con_value` / `con_grad` (`smbopt/optimizer.py`). Analytic quantities (flows, ratios) should get
   analytic gradients; anything that needs the CSS should use the metrics and gradients returned by
   `Optimizer._evaluate`.
3. Document it in `docs/configuration.md` and expose it in the web app
   (`smbopt/webapp/static/index.html`, `app.js`).

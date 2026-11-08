# Contributing

Thank you for your interest in contributing to the SMB Optimizer Suite.

## Development setup

1. Create and activate a virtual environment.
2. Install the dependencies and the test tools:

   ```bash
   pip install -r requirements.txt pytest
   ```

3. Run the tests:

   ```bash
   python -m pytest -q
   ```

4. Reproduce the benchmark optimum (takes a few minutes):

   ```bash
   python validation/benchmark_optimum.py
   ```

5. Run the local web app:

   ```bash
   python run_suite.py
   ```

## Project style and boundaries

- `smbsim/` is the simulation engine shared with the SMB Simulator Suite. Keep it identical to the
  simulator's version; changes to the physics belong in that project first.
- Keep the optimizer (`smbopt/`) to NumPy and SciPy.
- Keep the web app dependency-free (Python standard library backend, vanilla JS front end, no external
  libraries or CDNs).
- Keep component naming generic (for example: Wanted, Unwanted, Solvent, Wanted 1-3, Unwanted 1-3).
- Do not change validation targets unless the change is intentional and clearly explained.

## Branch and pull request workflow

1. Create a branch from `main` for each feature or fix.
2. Keep commits small and focused.
3. Make sure the tests pass before opening a pull request.
4. Explain any effect on the benchmark optimum in the pull request description.

## Adding an objective or a constraint

1. Add the objective to `OBJECTIVES` in `smbopt/problem.py`, or the limit to `Problem`.
2. Compute it in `Optimizer._obj_value` / `Optimizer.jac` or in `Optimizer._constraint_list` /
   `con_value` / `con_grad` (`smbopt/optimizer.py`). Analytic quantities (flows, ratios) should get
   analytic gradients; anything that needs the CSS should use the metrics and gradients returned by
   `Optimizer._evaluate`.
3. Expose it in the web app (`smbopt/webapp/static/index.html`, `app.js`).

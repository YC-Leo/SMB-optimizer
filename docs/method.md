# How the optimizer works

This page describes the search method. The simulation model is the one in [SMB-simulator](https://github.com/YC-Leo/SMB-simulator); see that project for the equations and their validation.

## Every evaluation is a cyclic steady state

The objective and the purity and recovery constraints are only defined at cyclic steady state (CSS), so every evaluation means switching the unit until it repeats itself. Three things make that affordable on a laptop:

1. **Accelerated CSS.** The CSS is the fixed point of the switch map *x = G(x)*: integrate one switching period, then re-index the columns by one. Plain repetition converges slowly because some modes decay by only a few per cent per switch. Anderson mixing of the last 12 iterates cuts the number of switches by a factor of 3–5. (It must not clip slightly negative concentrations at zero: the central-difference grid has small negative values at steady state, and clipping stalls the iteration.)
2. **Batched simulation.** The current point and one slightly changed copy per decision variable differ only in flows and switch time. `BatchSimulator` stacks them along an extra array axis and integrates them with exactly the same equations as the simulator (the results are bit-for-bit identical). With small grids the cost of a NumPy step is mostly fixed overhead, so six operating points cost about twice as much as one.
3. **Warm starts and parallel processes.** Every simulation starts from the CSS of the previous point, and gradient batches can be split over several processes.

## Trust-region SQP

The purities respond very nonlinearly to the flows: in the benchmark problem a 2 % change in switch time moves purity by about 35 points. A line-search SQP (SciPy's SLSQP) took a first step to the feed's upper bound, lost 30 points of purity, and then spent its time backtracking. The optimizer therefore uses a trust-region SQP on an exact L1 penalty (Sl1QP):

1. At the current point, compute the objective, the constraints and their gradients (forward differences from one batch).
2. Solve a small quadratic model of the problem, with a damped-BFGS Hessian of the Lagrangian, inside a box of size Δ around the current point. Constraint violations are allowed in the model at a penalty, so an infeasible start is not a problem.
3. Simulate the proposed point. Accept it only if the penalty merit (objective + μ · violation) improves by at least 10 % of what the model predicted.
4. Enlarge the box after good steps, shrink it after poor ones, and stop when the best step lies well inside the box and promises less than 0.01 % improvement.

Two details matter in practice. Each steady state is converged to 1e-8 g/mL per switch: at 1e-7 the purities still depend on the starting state by about 0.002 percentage point, which is enough to make a penalty method reject good steps near the optimum. And because purity is curved in the flows, a step aimed exactly at a limit tends to land just outside it; the search therefore aims 0.002 percentage point inside every product specification, and a second-order correction re-plans a step that left a curved limit.

Flow limits and feed or desorbent objectives are computed analytically, with exact gradients.

## What limits the optimum

At the optimum the gradient of the objective is a non-negative combination of the gradients of the binding limits (KKT conditions). The multipliers are estimated by non-negative least squares and converted to physical units: they say how much the objective would improve per unit of relaxation of each limit.

## What the operating-window map shows

For the benchmark problem the full-model window lies well to the left of the equilibrium-theory triangle: the best point has m₂ = 0.53, below the Henry constants of all three raffinate components (0.555–0.596), where dilute theory would send them into the extract. At these concentrations the solutes compete for the adsorbent and displace each other, so they travel faster than the dilute theory predicts. That is why this optimizer works on the full model, and why the triangle is shown only as a guide.

## Model

The simulation engine (`smbsim/`) is the one in [SMB-simulator](https://github.com/YC-Leo/SMB-simulator), kept identical file for file: competitive Langmuir isotherm, linear-driving-force mass transfer, axial dispersion, constant flow or density-driven volume change, and explicit port switching to cyclic steady state, in either the Original (finite-difference) or the Conservative (finite-volume) numerical mode. See that project for the equations and their validation.

The m-values are m<sub>j</sub> = (Q<sub>j</sub> t* − ε V) / ((1 − ε) V), with ε the total porosity and V the column volume. The Henry constants in the operating-window chart are the isotherm slopes at infinite dilution in the desorbent.

## Numerical libraries

Everything runs on NumPy and SciPy, which install from wheels on Windows, macOS (Apple Silicon and
Intel) and Linux with `pip`; no compiler, commercial solver or licence is needed. SciPy provides the
two solvers the search uses:

* `scipy.optimize.minimize(method="SLSQP")` for the small quadratic subproblem of each iteration
  (a few variables and limits; it takes milliseconds, against seconds to minutes for the simulations);
* `scipy.optimize.nnls` for the multipliers of the binding limits.

The cost of a run is dominated by the cyclic-steady-state simulations, not by these solvers, so a
dedicated QP or NLP package would not make a run noticeably faster.

## Reproducibility across platforms

The search is deterministic, but floating-point results of linear algebra (summation order in BLAS)
differ slightly between processors, operating systems and NumPy/SciPy builds, and so does the number
of worker processes (each worker integrates its share of a batch with that share's time step). Near
the optimum, where accepting or rejecting a step depends on small differences, the search can then
take a different path to practically the same optimum. For the Case 2 benchmark, two library
versions gave a feed of 0.3874 and 0.3877 mL/min (66 and 86 simulations), both with the purities
exactly on their 90 % limits. The reference tests therefore compare results with tolerances; see
`tests/test_cases.py`.

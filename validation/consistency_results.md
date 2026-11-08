# Optimizer consistency checks (benchmark problem)

## 1. Specification sweep

| Both purities at least | Best feed (mL/min) | Extract / raffinate purity | Value of 1 point (sum of multipliers, mL/min) | Iterations | Simulations |
|---|---|---|---|---|---|
| 88 % | 0.4423 | 88.00 / 88.00 | 0.0292 | 7 | 71 |
| 90 % | 0.3874 | 90.00 / 90.00 | 0.0277 | 9 | 66 |
| 92 % | 0.3325 | 92.00 / 92.00 | 0.0284 | 10 | 83 |

Observed change per point: 0.0274 mL/min between 88 and 90 %, 0.0275 between 90 and 92 %; the multipliers at 90 % predict 0.0277.
Monotonic (tighter specification, less feed): yes.

## 2. Different starting points

| Start | Start feed | Best feed | Extract / raffinate purity | Iterations | Simulations |
|---|---|---|---|---|---|
| Case 2 operating point | 0.2400 | 0.3874 | 90.00 / 90.00 | 9 | 66 |
| Benchmark optimum (Case 3) | 0.3874 | 0.3874 | 90.00 / 90.00 | 3 | 32 |
| Poor start (low feed, long switch) | 0.1000 | 0.3845 | 90.00 / 90.00 | 11 | 100 |

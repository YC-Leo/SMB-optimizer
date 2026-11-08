# Benchmark optimum (Case 2 → Case 3)

Optimizer: trust-region SQP, 9 iterations, 66 CSS simulations, 169 s on the machine that produced this file.

| | Start (Case 2) | Optimum found here | Benchmark optimum (Case 3) |
|---|---|---|---|
| Zone I flow (mL/min) | 6.9600 | **7.0000** | 6.9714 |
| Desorbent (mL/min) | 2.1400 | **1.6400** | 1.6400 |
| Extract (mL/min) | 0.7210 | **0.8227** | 0.8803 |
| Feed (mL/min) | 0.2400 | **0.3874** | 0.3874 |
| Switch time (min) | 1.8930 | **1.8955** | 1.9217 |
| Extract purity (%) | 91.30 | **90.00** | 90.00 |
| Extract recovery (%) | 91.80 | **77.94** | 77.93 |
| Raffinate purity (%) | 96.04 | **90.00** | 90.00 |
| Raffinate recovery (%) | 95.74 | **95.79** | 95.79 |
| m2 / m3 | 0.549 / 0.648 | **0.527 / 0.687** | 0.526 / 0.688 |

Feed gain over the start: **+61.4 %** here, +61.4 % for the benchmark optimum.

The desorbent flow can differ between the two optima: with the zone I flow fixed it only sets the zone IV flow, which hardly affects purity here (its purity gradient is about 100 times smaller than that of the other flows), so a range of desorbent flows gives the same feed. Both optima sit at the same (m2, m3).

Binding limits at the optimum found here (value of relaxing each by one unit):

- Zone I flow ≤ 7 mL/min: +0.0262 mL/min feed per mL/min
- Raffinate purity ≥ 90 %: +0.0173 mL/min feed per percentage point
- Extract purity ≥ 90 %: +0.0104 mL/min feed per percentage point
- D · Desorbent in (zone I) at its lower bound (1.64 mL/min): +0.0043 mL/min feed per mL/min

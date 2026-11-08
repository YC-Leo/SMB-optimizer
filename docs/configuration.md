# Problem file format

A problem file describes one optimization: the SMB unit, what the optimizer may change, what it should
achieve and which limits it must respect. It is a JSON file (or YAML with the same structure, when
PyYAML is installed). The web app's **Export problem** button and `smb-optimizer example` write this
format, and `smb-optimizer run` and the web app's **Import problem** read it.

The quickest way to start is to write an example and edit it:

```bash
smb-optimizer example case1 -o my_problem.json     # or case2, case2-desorbent
smb-optimizer validate my_problem.json
```

To build a problem around a setup made in [SMB-simulator](https://github.com/YC-Leo/SMB-simulator):

```bash
smb-optimizer from-setup my_setup.json -o my_problem.json
```

## Top level

```jsonc
{
  "process":   { ... },          // the SMB unit: an SMB-simulator setup (see below)
  "variables": [ ... ],          // decision variables with bounds and start values
  "objective": "max_feed",       // what to optimize
  "specs":     [ ... ],          // purity and recovery limits
  "max_zone_flow": 7.0,          // mL/min, largest flow in any zone (pressure-drop limit); null = none
  "min_zone_flow": 0.01,         // mL/min, smallest flow in any zone and in the balance outlet
  "max_desorbent_ratio": null,   // optional upper limit on desorbent / feed
  "max_iterations": 40,          // trust-region iterations
  "css_tol": 1e-8,               // g/mL per switch: cyclic-steady-state tolerance for every evaluation
  "fd_step": 0.001,              // relative finite-difference step for the gradients
  "ftol": 1e-6,                  // kept for compatibility; not used by the trust-region search
  "workers": 0                   // parallel processes; 0 = automatic (CPU count − 1, at most 8)
}
```

| Key | Values |
|---|---|
| `objective` | `max_feed` (feed throughput), `min_desorbent` (desorbent / feed), `max_extract_purity`, `max_extract_recovery`, `max_raffinate_purity`, `max_raffinate_recovery` |
| `css_tol` | 1e-10 to 1e-4. Keep 1e-8: looser tolerances make the purities depend on the starting state enough to disturb the search near the optimum. |
| `fd_step` | 1e-4 to 0.05 (0.01 % to 5 %) |
| `max_iterations` | 1 to 200 |

## `variables`

One entry per flow the optimizer may change, plus the switch time:

```json
{"key": "port:2", "label": "F · Feed in (zone III)", "unit": "mL/min",
 "start": 1.32, "lower": 0.5, "upper": 3.0, "optimize": true}
```

| Field | Meaning |
|---|---|
| `key` | `Q1` (zone I flow, closed loop), `port:<i>` (flow of port *i* in `process.ports`), or `step_time` (switch time, min) |
| `start`, `lower`, `upper` | start value and bounds; `lower` must be below `upper`, and none may be negative |
| `optimize` | `false` keeps the variable fixed at `start` |
| `label`, `unit` | used in reports only |

The `start` values override the matching flows and switch time in `process`. The balance outlet
(the port with `"balance": true`) has no variable: its flow follows from the liquid balance.

To maximize feed throughput, the feed flow must be a decision variable; to minimize desorbent use,
the desorbent or the feed flow must be one.

## `specs`

```json
{"metric": "extract_purity", "minimum": 98.0, "enabled": true}
```

`metric` is `extract_purity`, `extract_recovery`, `raffinate_purity` or `raffinate_recovery`. Purity
is the desorbent-free group purity: the share of the wanted components in the extract (or of the
unwanted components in the raffinate), ignoring the solvent. Recovery is the share of the fed
wanted (or unwanted) components that leaves in that product. Both are in %.

## `process`

The `process` section is an SMB-simulator setup, the same file SMB-simulator exports. The
optimizer uses it unchanged; see the SMB-simulator documentation for the model behind it. The main
fields are:

| Field | Meaning |
|---|---|
| `components` | 2 to 10 components, each with `name`, `role` (`extract`, `raffinate` or `desorbent`), Langmuir `qsat` (g/mL solid) and `keq` (mL/g), mass-transfer coefficient `kap` (1/min), liquid density `rho` (g/mL), and volume fractions `feed_frac` and `des_frac` |
| `zones` | columns per zone in flow order, for example `[5, 4, 4, 3]`; at most 16 columns and 6 zones |
| `ports` | `kind` (`desorbent`, `feed`, `extract`, `raffinate`), `zone` (0 = zone I), `flow` (mL/min), `balance` (exactly one outlet) |
| `open_loop` | `true` for no recycle from the last zone to zone I |
| `Q1`, `step_time` | zone I flow (mL/min) and switch time (min) |
| `length`, `radius`, `dead_length` | packed length, internal radius and extra-column length per column (cm) |
| `porosity_spec`, `porosity_total`, `bed_porosity`, `particle_porosity` | total porosity, or bed and particle porosity |
| `dispersion_spec`, `peclet`, `particle_diameter`, `particle_peclet` | axial dispersion from a column Péclet number, or from particle size |
| `scheme` | `original` (finite differences) or `conservative` (finite volumes) |
| `flow_model` | `constant` or `volume_change` (liquid flow changes along the bed with adsorption) |
| `nodes`, `cells` | grid points per column (original) or finite volumes (conservative) |

`css_tol`, `max_cycles` and `accelerate` in `process` are settings of the simulator's own run; the
optimizer uses the top-level `css_tol` instead.

## Output of `smb-optimizer run`

`smb-optimizer run my_problem.json` writes to `results/my_problem/` (change with `-o`):

| File | Content |
|---|---|
| `summary.json` | start and best point: variable values, objective, purities and recoveries, zone flows, m-values and the status of every limit; the binding limits and what relaxing each by one unit is worth; iterations, simulations and run time |
| `iterations.csv` | one row per accepted iteration (same columns as the web app's CSV download) |
| `best_setup.json` | the best operating point as an SMB-simulator setup; open it in SMB-simulator to watch the unit run |

The exit status is 0 when the best point meets every limit, 2 when the search finished without
meeting them all, and 1 for an input error.

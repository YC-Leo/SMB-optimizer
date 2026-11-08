# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-08

First public release.

### Added
- Operating-condition optimizer for SMB units: zone I flow, port flows and switch time as decision
  variables with bounds.
- Objectives: maximize feed throughput, minimize desorbent use, or maximize a purity or recovery figure.
- Limits: minimum extract and raffinate purity and recovery, largest and smallest zone flow, optional
  desorbent-to-feed limit.
- Trust-region SQP on an exact L1 penalty, with finite-difference gradients from batched,
  warm-started cyclic-steady-state simulations.
- Batched CSS solver (many operating points integrated together) with Anderson acceleration of the
  switch map.
- Lagrange-multiplier report of which limits bind and what relaxing each one is worth.
- Operating-window map in the (m2, m3) plane from the full model, with the equilibrium-theory
  triangle as a guide.
- Local web app with grouped setup, live progress, start-vs-best comparison and export of the best
  setup for SMB-simulator.
- `smb-optimizer` command-line tool (`example`, `validate`, `run`, `from-setup`, `gui`) and a
  documented JSON/YAML problem file format; example problems for Case 1 and Case 2 with their outputs.
- Tests that run the Case 1 and Case 2 optimizations and compare them with stored reference results,
  on Windows, macOS and Linux in continuous integration.
- Benchmark validation (Case 2 to its benchmark optimum) and consistency checks.
- Pre-publication content check (`tools/check_repo.py`) run as a git hook and in CI.

[Unreleased]: https://github.com/YC-Leo/SMB-optimizer/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/YC-Leo/SMB-optimizer/releases/tag/v1.0.0

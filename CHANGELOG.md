# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog,
and this project adheres to Semantic Versioning.

## [1.0.0] - 2026-11-01

### Added
- Operating-condition optimizer for SMB units: zone I flow, port flows and switch time as decision variables with bounds.
- Objectives: maximize feed throughput, minimize desorbent use, or maximize a purity or recovery figure.
- Limits: minimum extract and raffinate purity and recovery, largest and smallest zone flow, optional desorbent-to-feed limit.
- Trust-region SQP on an exact L1 penalty, with finite-difference gradients from batched, warm-started CSS simulations.
- Batched CSS solver (many operating points integrated together) with Anderson acceleration of the switch map.
- Lagrange-multiplier report of which limits bind and what relaxing each one is worth.
- Operating-window map in the (m2, m3) plane from the full model, with the equilibrium-theory triangle as a guide.
- Local web app with grouped setup, live progress, start-vs-best comparison and export of the best setup for the SMB Simulator Suite.
- Benchmark validation (Case 2 → Case 3), tests and cross-platform CI.

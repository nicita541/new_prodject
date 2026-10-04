---
name: risky-change
description: Use for migrations, destructive operations, large data/state changes, signing/release changes, production configuration changes, or any edit with a wide blast radius or difficult rollback. Analyze impact first and define rollback and validation before execution.
---

# Risky change

Before implementation, assess:
- blast radius;
- reversibility;
- data compatibility/loss risk;
- affected users/services;
- external dependencies;
- detection/monitoring signals.

Define:
1. backup or preservation needs;
2. staged rollout/feature flag options;
3. rollback steps;
4. validation before and after rollout;
5. stop conditions.

Prefer reversible, incremental changes over one-way transitions.


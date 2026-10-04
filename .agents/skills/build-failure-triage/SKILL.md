---
name: build-failure-triage
description: Use when a build, compilation, packaging, CI, signing, or release pipeline fails. Separate the first causal error from follow-on noise, reproduce locally when possible, fix the responsible configuration or code, and rerun the failing stage.
---

# Build failure triage

1. Identify the exact failing command/stage and the first causal error.
2. Distinguish primary failures from downstream noise.
3. Compare environment, toolchain, configuration, secrets/signing inputs, and recent changes.
4. Reproduce the smallest failing step when possible.
5. Fix the responsible source/configuration rather than suppressing the error.
6. Rerun the failed stage, then the broader pipeline if warranted.
7. Record durable environment/build facts in `docs/ai/project-context.md` only if future work benefits.


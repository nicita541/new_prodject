---
name: release-readiness
description: Use when preparing a build or repository state for a real release, deployment, store submission, package publication, or handoff. Validate versioning, build/tests, configuration, secrets/signing, migrations, artifacts, release notes, and rollback readiness.
---

# Release readiness

Check only items relevant to this project:
- clean intended diff and repository state;
- version/build identifiers;
- reproducible release build/package;
- required tests and critical smoke flows;
- production configuration;
- secret/signing handling without exposing secret values;
- migrations and backward compatibility;
- expected artifacts and checksums/signatures when applicable;
- release notes/change log;
- rollback/recovery path.

Separate release blockers from non-blocking follow-ups.


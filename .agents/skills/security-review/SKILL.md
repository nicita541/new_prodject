---
name: security-review
description: Use when code touches authentication, authorization, secrets, user-controlled input, file/network access, sensitive data, payments, external integrations, or another trust boundary. Review concrete attack paths and least-privilege assumptions.
---

# Security review

Identify trust boundaries first, then inspect relevant risks:
- authentication and authorization;
- input validation and injection;
- path traversal / unsafe file access;
- unsafe deserialization or command execution;
- secret handling and sensitive logs;
- storage/encryption requirements;
- SSRF/network boundaries;
- dependency and supply-chain risk;
- privilege escalation and insecure defaults.

Do not claim a security guarantee. Report scope, evidence, assumptions, and unverified areas.


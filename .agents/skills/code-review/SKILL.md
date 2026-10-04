---
name: code-review
description: Use when reviewing a patch, branch, pull request, or completed implementation. Look for correctness and regressions first, then security, architecture, error handling, tests, performance, and maintainability. Report concrete findings with evidence.
---

# Code review

Review the actual diff in context.

Priority:
1. correctness and data loss;
2. regressions and broken contracts;
3. security and permission boundaries;
4. error/failure handling;
5. concurrency/state issues;
6. test gaps for meaningful risk;
7. maintainability/performance where material.

Make findings specific: file/location, failure scenario, impact, and suggested direction.
Avoid style-only noise unless it violates an established repo rule or creates real risk.


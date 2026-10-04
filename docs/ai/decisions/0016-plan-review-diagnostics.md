# ADR-0016: Derived plan diagnostics for review

## Status
Accepted — 2026-10-05

## Context
Export plans contain diagnostics for analyzed events, including events later
removed from the final timeline. Showing that raw list can flag footage that
does not appear in the export. Reviewers also need to understand why retained
source intervals remain without exposing private analysis payloads.

## Decision
Keep the existing `GET /api/jobs/{id}/plan` endpoint and derive two bounded,
transient response fields: `quality_summary` and `debug_timeline`. Attribute
event diagnostics only where the event's selected ranges intersect final part
cuts. Debug reasons require explicit saved interval evidence and are clipped to
those same cuts. Missing or malformed provenance is reported as unavailable.
Profile-preservation notes remain separate from actionable warnings. The
debug timeline stays off until the reviewer enables it.

## Alternatives considered
Persist a second diagnostic artifact or add a new endpoint. Both duplicate plan
state and create another compatibility surface without adding information.

## Consequences
Old plan files remain readable and return unavailable diagnostics when they do
not contain adequate provenance. The summary is recomputed from the saved plan,
so it follows manual corrections without rewriting analysis history. Response
fields are allowlisted text and source intervals; provider payloads, prompts,
keys and filesystem paths are not included.

## Revisit when
Diagnostics need independent persistence or callers need a stable API outside
the local review UI.

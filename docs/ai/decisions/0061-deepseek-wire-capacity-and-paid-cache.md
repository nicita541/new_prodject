# ADR-0061: Validate DeepSeek capacity on the actual wire and preserve paid cache

Status: implemented and tested.

## Context

A real candidate needed nine contact-sheet images. The adapter's old eight-image
and 4 MiB individual-image restrictions were app limits, not current API limits.
After correcting those, a valid cut-only question still failed before transport:
the domain preflight counted expanded local JSON/schema while the adapter sends
losslessly compacted JSON and factored schema. A cached unsent rejection persisted
after the preflight fix. Independent review also reproduced a duplicate paid
request when malformed optional diagnostic metadata invalidated a valid cache hit.

## Decision

Use the documented inline protocol limits: 600 images, 32 MiB per image, 64 MiB
total raw images and 48 MiB serialized request body. These are capacity bounds,
not sampling targets or a spending policy. Reject oversized inputs before file
read/base64 allocation using exact serialized JSON plus base64 lengths. Guard the
final HTTP body before credentials/network; check correction bodies again.
Contact sheets remain 960×1224, below the documented dimension limits. No Files
API, external image host or new dependency is introduced.

Source: [official DeepSeek vision documentation](https://api-docs.deepseek.com/guides/vision/),
verified 2026-10-18. The [model documentation](https://api-docs.deepseek.com/quick_start/pricing/)
lists 1M context. The retained 64,000-byte adapter text policy is not that API limit.

DeepSeek candidate requests defer capacity validation to the adapter's actual
compact wire inside the existing question reservation. Local and other external
preflights remain unchanged. Only a known pre-dispatch `RequestCapacityError`
permits proposal image reduction. Correction overflow after a response is a
technical failure and cannot restart proposal sampling or paid dispatch.

Keep original question keys for successful answers and unknown reservations.
Only the legacy exact `{status: context_limit}` result, which was recorded before
transport, uses a versioned compact-wire capacity key. Preserve the old negative;
reuse the new result on subsequent runs. Never migrate unknown dispatch outcomes.

Separate optional cache-hit diagnostics from cache validation. Malformed JSON,
nonobject metadata or I/O failures in the audit cannot invalidate an already
validated paid answer. Its media/schema/content ownership still must validate.

## Validation and rollback

Tests cover nine-image transport/reuse, individual/total/body byte bounds, exact
base64 size, correction overflow, compact-schema preflight, legacy unsent negative
migration, unknown outcome protection and corrupt optional audit metadata. A real
nine-page source review and eight-page cut-only review completed. The viewer
rejected the unfinished story; capacity success does not establish edit quality.

No persisted answer or original source is rewritten. Reverting adapter/prompt
changes preserves old response caches/readers; changed native stage identities
remain explicit. Full editorial/audio/corpus acceptance remains in the ExecPlan.

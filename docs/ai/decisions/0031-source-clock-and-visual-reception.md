# Source clock, speech margins and verified visual reception

## Problem
Structured source selections ended exactly on ASR timestamps. The planners
skipped their existing speech margins, cutting audible consonants. Treating
padding as selected story then created false unresolved transitions. Separately,
the restricted Antigravity persona allowed only finish: print-mode @ mentions
did not deliver image pixels, so accepted JSON could contain invented scenes.

## Decision
Both planners use one source-bounded speech-margin function. Plans additionally
save semantic_ranges, the original selected story clock before padding. The
final gate independently reconstructs all permitted margins and checks exact
coverage before using that story clock. Next omitted ASR words, actual title
exclusions and omitted consequential actions block expansion. Source endings
can include their bounded continuous audio tail, without rewriting source proof.

An explicit preferred_part_count influences retention cost and partition
comfort; it is an upper-count preference, not a requirement to cut necessary
context. Processing duration, word safety and independently supported endings
remain mandatory. Ordinary planning keeps its existing 120-second ceiling.

Visual CLI calls use the official restricted view_file tool and stream-json
tool events. The standalone runner publishes success only after DONE reads of
every exact packet image, with a receipt bound to the packet image hashes and
the exact returned envelope bytes. Official visual envelopes need that receipt
on import. Text packet identities remain unchanged; visual identities change
to prevent reuse of previous replies without image delivery. Explicit manual
JSON imports retain their existing contract and schema checks.

Previously accepted ASR dialogue quotes can supply exact source facts for
continuity without new speech recognition. This cache reuse does not carry
unsupported visual descriptions or approve a bridge; the original endpoint
images must independently establish which candidate facts are needed.

## Compatibility and rollback
Old plans remain readable through a recomputed bounded-margin fallback.
Source media, transcript and previous exports stay intact. Code/policy cache
identities cover the new shared helper. Reverting the planners restores earlier
partition behavior; reverting visual transport must not re-enable unverified
visual replies. Keep prior exports as separate job versions for comparison.

## Validation
Authored regressions cover structured margins, omitted neighbors, exclusion
barriers, forged range metadata, no-new-speech ending tails, soft count overflow,
bounded candidate refs and receipt/hash mismatches. Actual pixel reception was
verified with official view_file DONE events and source-matching descriptions.
These checks do not claim that JSON validation proves semantic truth.

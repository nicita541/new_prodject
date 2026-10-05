# Per-job rendering presets

Named `layout` and `caption_style` fields are validated at the job API and persisted in `render-settings.json`. Absent settings mean legacy `portrait`/`classic`; the UI explicitly submits `cinema`/`accent` for its new default presentation. Arbitrary filter expressions are never accepted.

Story decisions do not depend on rendering. The whole-frame `cinema` layout skips local speaker-coordinate inference and uses a separate final-event cache signature while retaining the original story signature. Subtitle style and layout participate in export fingerprints. This avoids paid story repeats and stale rendered results after a preset change. Existing per-job source and output ownership remains unchanged.

Whole-frame composition trades large faces for preserving interactions and avoiding incorrect face crops. The portrait option retains temporal AI focus. Rollback: submit portrait/classic; existing absent-settings jobs keep those defaults. There is no destructive data migration.

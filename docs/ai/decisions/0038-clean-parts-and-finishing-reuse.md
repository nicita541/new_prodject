# Clean montage parts and incremental finishing

Finishing previously opened the full episode once per source cut, forced CPU
encoding and encoded every selected part again after a local caption edit.

`app.clean_parts` now owns disposable clean masters under
`data/jobs/<job_id>/clean/part_<index>/<identity>/clean.mkv`. Initial render
workers retain these masters; existing completed jobs create them on the first
full finishing export. A five-second preview uses an available master but does
not force creation of a whole part.

Masters retain full source resolution, the selected original audio and exact
montage cuts on the output clock. H.264 lossless CRF 0 and PCM avoid adding a
lossy generation before presentation. Added subtitles, cards, music, blur and
crop are excluded; burned-in source text remains source content. This trades
disk space for repeat editing speed. Focus anchors are translated to output time
and reset abruptly at montage cut boundaries. Source identity, exact intervals,
audio ordinal and a version determine validity; captions and focus do not.
Media is probed before atomic publication, with size/time manifests checked on
reuse. Interrupted or mismatched masters are regenerated, with no change to the
source, plan or base output.

Finishing uses the existing NVENC probe and CPU fallback. FFmpeg's output clock
provides within-part progress; queue, master preparation and presentation are
separate status phases. A per-part render digest includes effective job captions,
focus, appearance, selected music content and source identity. Only the latest
completed owned presentation for the same plan can be copied into a new export
when this digest matches and MP4/SRT content hashes still verify. Other parts' caption edits and save revisions do not
invalidate it. Historical outputs without a render digest remain playable but
receive a new render once before incremental reuse is possible. Completed-task
publication remains atomic at the task level; partial failures do not replace
ready files.

The UI replaces any previous completion notice immediately at submission,
maintains visible progress and shows success only after a completed task and
refreshed playback files. A progress value of 100% alone is not completion.

Rollback: restore direct-source render calls and remove the new cache module.
Masters are derived data and can be removed to recover disk space; original
outputs, episode profiles, caption overrides and plans are unaffected.

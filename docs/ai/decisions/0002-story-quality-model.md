# Sequential models for story selection

The first complete-episode quality review found that the 4B visual model could mistake a mixed opening/title/office window for entirely non-narrative footage. The user explicitly authorized additional models and training if useful.

Keep Qwen3.5-4B for initial image grounding, and use Qwen3.5-9B UD-Q4_K_XL for condensation, individual credit-boundary units and global story continuity. Final temporal framing also uses 9B, in a separate session with thinking disabled. A real comparison on the mixed window preserved the silent office scene with the 9B unit prompt. Its 8192-token context and all-layer GPU offload ran on the installed 8GB GPU without OOM in the short compatibility check. Later comparison of 16 actual framing requests across eight samples improved confidently clipped faces from the 4B model. This establishes a reason to change the model, not a general accuracy measurement. Full-series quality remains an independent acceptance check.

Load model sessions sequentially and release each before loading the next. If GPU inference fails, the same model can use CPU; do not replace the story with a heuristic summary. JSON grammars constrain selections to existing source IDs. Protect actual speech within credits and prevent opening classifications from cascading into later silent narrative scenes.

Pin both 9B artifacts and their revision in setup and the model manifest. Their projector checksum differs from the 4B projector. Model identity participates in derived-cache signatures. Original audio, source files and prior diagnostics remain available for comparison and rollback; changing models requires regenerated derived decisions, not reusing old events.

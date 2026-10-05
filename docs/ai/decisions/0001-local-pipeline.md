# Local, process-isolated video pipeline

Status: accepted, 2026-10-01.

The project must run offline on Windows with 8GB VRAM and keep all installations inside its root. Use a portable Python/FastAPI app and a static Russian UI. A single worker owns FFmpeg, an isolated faster-whisper CUDA process, and a temporary llama.cpp Vulkan server. The model stages execute sequentially and terminate to release memory.

Analysis persists a factual source event map. The model selects supplied source-unit IDs; deterministic code validates dependencies, chronology, word boundaries and clip limits before rendering. This protects source provenance and allows failed work to resume. Original media is never overwritten; published clips appear only after FFprobe validation.

Vulkan llama.cpp avoids requiring a global CUDA toolkit or an incompatible compiled CUDA architecture. ASR's redistributable cuBLAS/cuDNN DLLs stay under tools/cuda. Alternatives involving hosted APIs, Docker services and system package managers conflict with the requested offline/portable operation.

Rollback: keep source files and exported results; replace a pinned tool/model or application stage independently, start a new job when analysis version changes. No OS installation changes are required.

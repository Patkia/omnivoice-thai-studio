"""Small long-text adapter; deliberately not a Novel Mode project system."""
from __future__ import annotations
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

from novel_chunker import CONTINUATION_PAUSE_MS, semantic_chunks

SINGLE_INPUT_CEILING = 500
# Compatibility name retained for existing callers.
THRESHOLD = SINGLE_INPUT_CEILING
TARGET = 100
HARD_MAX = 120
SILENCE_MS = CONTINUATION_PAUSE_MS  # legacy default for callers of merge()

def resolve_continuity_seed(alias: str) -> int | None:
    """Long text now uses the profile seed resolved by StudioEngineAdapter.

    Kept as a compatibility helper for callers/tests; there is no separate
    long-text-only seed policy anymore.
    """
    return None

def is_long(text): return len(text) > THRESHOLD

def merge(paths: list[Path], output: Path, silence_ms: int = SILENCE_MS,
          pause_after_ms: list[int] | None = None):
    """Merge ordered WAVs, using per-chunk pauses and never adding a final gap."""
    if not paths: raise ValueError("no chunk WAVs to merge")
    if pause_after_ms is None: pause_after_ms = [silence_ms] * len(paths)
    if len(pause_after_ms) != len(paths): raise ValueError("pause_after_ms must match paths")
    arrays, rate, channels, width = [], None, None, None
    for p in paths:
        with wave.open(str(p), "rb") as wav:
            meta = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
        if rate is None: rate, channels, width = meta
        elif meta != (rate, channels, width): raise RuntimeError("chunk WAV has mismatched sample rate/channel/sample width")
        audio, _ = sf.read(p, dtype="float32", always_2d=True)
        arrays.append(audio)
    parts = []
    for index, audio in enumerate(arrays):
        parts.append(audio)
        if index < len(arrays) - 1:
            parts.append(np.zeros((int(rate * pause_after_ms[index] / 1000), channels), dtype="float32"))
    combined = np.concatenate(parts)
    sf.write(output, combined, rate, subtype="PCM_16")
    return len(combined) / rate

def remerge_cached(paths: list[Path], output: Path, chunks) -> float:
    """Re-merge cached WAVs after pause-policy changes; no adapter/model call."""
    return merge(paths, output, pause_after_ms=[chunk.pause_after_ms for chunk in chunks])

def generate(adapter, text, alias, speed, steps, output, force=False,
             cancelled=lambda: False, progress=lambda *_: None, seed: int | None = None,
             instruction_override: str | None = None,
             reference_conditioning: bool = False, reference_audio: str | None = None,
             reference_sha256: str | None = None, reference_text: str | None = None,
             reference_text_sha256: str | None = None,
             generation_mode: str = "voice_design", language: str | None = None,
             denoise: bool | None = None, postprocess_output: bool | None = None,
             voice_project: str = ""):
    chunks = semantic_chunks(text, TARGET, HARD_MAX)
    continuity_seed = seed  # None means: StudioEngineAdapter resolves the profile's fixed seed.
    root = output.parent / "batch_chunks" / output.stem
    root.mkdir(parents=True, exist_ok=True)
    paths, total_inf, hits, total = [], 0.0, 0, len(chunks)
    for i, chunk in enumerate(chunks, 1):
        if cancelled(): return {"cancelled": True, "chunks": i - 1, "paths": paths}
        progress(i, total, "GENERATING")
        path = root / f"{i:03}.wav"
        options = {"seed": continuity_seed}
        if generation_mode != "voice_design":
            options["generation_mode"] = generation_mode
        if language is not None:
            options["language"] = language
        if denoise is not None:
            options["denoise"] = denoise
        if postprocess_output is not None:
            options["postprocess_output"] = postprocess_output
        if voice_project:
            options["voice_project"] = voice_project
        if instruction_override is not None:
            options["instruct_override"] = instruction_override
        if reference_conditioning:
            options.update(
                reference_conditioning=True,
                reference_audio=reference_audio,
                reference_sha256=reference_sha256,
                reference_text=reference_text,
                reference_text_sha256=reference_text_sha256,
            )
        try: result = adapter.generate(chunk.text, alias, speed, steps, path, force, **options)
        except Exception as exc: raise RuntimeError(f"chunk {i} failed: {exc}") from exc
        paths.append(path); hits += int(result["cache_hit"]); total_inf += result.get("inference_seconds", 0)
        progress(i, total, "CACHED" if result["cache_hit"] else "GENERATED")
    duration = remerge_cached(paths, output, chunks)
    return {"cancelled": False, "chunk_count": total, "paths": paths, "cache_hits": hits,
        "inference_seconds": total_inf, "duration": duration, "rtf": total_inf / duration if duration else None,
        "model_load_count": adapter.session.model_load_count, "continuity_seed": continuity_seed,
        "chunks": [chunk.to_dict() for chunk in chunks]}

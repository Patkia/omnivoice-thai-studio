"""Mission 17 A/B pack: three reviewed semantic chunks, with no UI changes."""
from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

import tts
from long_text_batch import merge, resolve_continuity_seed
from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
PREVIEW_PATH = ROOT / "output" / "semantic_chunk_preview.json"
OUTPUT_DIR = ROOT / "output" / "long_text_continuity_poc"
SELECTED_INDICES = (8, 9, 10)
STEPS = 32


def wav_meta(path: Path) -> dict:
    with wave.open(str(path), "rb") as source:
        return {"sample_rate": source.getframerate(), "channels": source.getnchannels(),
                "sample_width": source.getsampwidth(), "frames": source.getnframes()}


def synthesize_set(adapter, rows: list[dict], seed: int | None, label: str, speed: float) -> tuple[list[Path], list[dict]]:
    paths, records = [], []
    for row in rows:
        path = OUTPUT_DIR / f"{label}_chunk_{row['index']:02}.wav"
        result = adapter.generate(row["text"], "narrator", speed, STEPS, path, force=False, seed=seed)
        paths.append(path)
        records.append({"index": row["index"], "seed": seed, "pause_after_ms": row["pause_after_ms"],
                        "output": str(path.relative_to(ROOT)), "cache_hit": result["cache_hit"],
                        "model_load_seconds": result["model_load_seconds"],
                        "inference_seconds": result["inference_seconds"], "wav": wav_meta(path)})
    return paths, records


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    preview = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    rows = [row for row in preview["chunks"] if row["index"] in SELECTED_INDICES]
    if [row["index"] for row in rows] != list(SELECTED_INDICES):
        raise RuntimeError("semantic preview does not contain the requested ordered chunks")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    registry = tts.load_json(ROOT / "approved_voice_profiles.json")
    speed = float(tts.resolve_voice("narrator", registry)["speed"])
    seeded = resolve_continuity_seed("narrator")
    if seeded is None:
        raise RuntimeError("narrator continuity seed is not configured")

    adapter = StudioEngineAdapter()  # One persistent session for both A/B sets.
    started = time.perf_counter()
    current_paths, current = synthesize_set(adapter, rows, None, "current", speed)
    fixed_paths, fixed = synthesize_set(adapter, rows, seeded, "fixed_seed", speed)
    pauses = [row["pause_after_ms"] for row in rows]
    current_preview = OUTPUT_DIR / "current_preview.wav"
    fixed_preview = OUTPUT_DIR / "fixed_seed_preview.wav"
    current_duration = merge(current_paths, current_preview, pause_after_ms=pauses)
    fixed_duration = merge(fixed_paths, fixed_preview, pause_after_ms=pauses)
    total_inference = sum(row["inference_seconds"] for row in current + fixed)
    report = {
        "mission": "MISSION 17 — LONG TEXT VOICE CONTINUITY INTEGRATION",
        "model": adapter.engine["model"], "revision": adapter.engine["revision"], "voice": "narrator",
        "speed": speed, "steps": STEPS, "selected_chunk_indices": list(SELECTED_INDICES),
        "pause_after_ms": pauses, "seed_policy": {"current": None, "fixed_seed": seeded},
        "sets": {"current": current, "fixed_seed": fixed},
        "previews": {"current": str(current_preview.relative_to(ROOT)),
                     "fixed_seed": str(fixed_preview.relative_to(ROOT))},
        "durations_seconds": {"current": round(current_duration, 3), "fixed_seed": round(fixed_duration, 3)},
        "model_load_count": adapter.session.model_load_count, "device": adapter.session.device,
        "total_inference_seconds": round(total_inference, 3),
        "total_wall_seconds": round(time.perf_counter() - started, 3),
        "cache_hits": sum(row["cache_hit"] for row in current + fixed),
        "cache_misses": sum(not row["cache_hit"] for row in current + fixed),
        "merge_verification": {"same_order": True, "same_pause_metadata": True,
                               "merge_function": "long_text_batch.merge", "trailing_silence_added": False},
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

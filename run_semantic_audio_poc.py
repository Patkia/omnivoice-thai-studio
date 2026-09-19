"""Generate the approved representative semantic-audio POC; not a Novel Mode runner."""
from __future__ import annotations

import json
import time
from pathlib import Path

from long_text_batch import merge
from studio_engine_adapter import StudioEngineAdapter
import tts


ROOT = Path(__file__).resolve().parent
PREVIEW_PATH = ROOT / "output" / "semantic_chunk_preview.json"
OUTPUT_DIR = ROOT / "output" / "semantic_audio_poc"
REPORT_PATH = OUTPUT_DIR / "report.json"
SELECTED_INDICES = (6, 8, 9, 12, 19, 20)
VOICE_ALIAS = "narrator"


def load_selected_chunks() -> list[dict]:
    payload = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    indexed = {row["index"]: row for row in payload["chunks"]}
    missing = [index for index in SELECTED_INDICES if index not in indexed]
    if missing:
        raise RuntimeError(f"semantic preview is missing requested chunks: {missing}")
    rows = [indexed[index] for index in SELECTED_INDICES]
    if not all(row["char_count"] == len(row["text"]) <= 120 for row in rows):
        raise RuntimeError("semantic preview violates hard_max metadata")
    return rows


def main() -> int:
    chunks = load_selected_chunks()
    engine = tts.load_json(tts.ENGINE_PATH)
    registry = tts.load_json(ROOT / "approved_voice_profiles.json")
    voice = tts.resolve_voice(VOICE_ALIAS, registry)
    speed, steps = float(voice["speed"]), int(engine["default_steps"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    adapter = StudioEngineAdapter()
    chunk_results: list[dict] = []
    paths: list[Path] = []
    started = time.perf_counter()
    for row in chunks:
        output = OUTPUT_DIR / f"chunk_{row['index']:02}.wav"
        result = adapter.generate(row["text"], VOICE_ALIAS, speed, steps, output, force=False)
        paths.append(output)
        chunk_results.append({
            "index": row["index"],
            "output": str(output.relative_to(ROOT)),
            "char_count": row["char_count"],
            "boundary_type": row["boundary_type"],
            "pause_after_ms": row["pause_after_ms"],
            "dialogue": row["dialogue"],
            "cache_hit": result["cache_hit"],
            "model_load_seconds": result["model_load_seconds"],
            "inference_seconds": result["inference_seconds"],
        })

    preview_output = OUTPUT_DIR / "semantic_audio_preview.wav"
    duration = merge(paths, preview_output, pause_after_ms=[row["pause_after_ms"] for row in chunks])
    total_inference = sum(row["inference_seconds"] for row in chunk_results)
    report = {
        "mission": "MISSION 13 — SEMANTIC AUDIO POC",
        "source_preview": str(PREVIEW_PATH.relative_to(ROOT)),
        "selected_indices": list(SELECTED_INDICES),
        "model": engine["model"],
        "revision": engine["revision"],
        "voice": VOICE_ALIAS,
        "voice_instruction": voice["voice_instruction"],
        "speed": speed,
        "steps": steps,
        "device": adapter.session.device,
        "model_load_count": adapter.session.model_load_count,
        "total_wall_seconds": round(time.perf_counter() - started, 3),
        "total_inference_seconds": round(total_inference, 3),
        "audio_duration_seconds": round(duration, 3),
        "rtf": round(total_inference / duration, 3) if duration else None,
        "cache_hits": sum(1 for row in chunk_results if row["cache_hit"]),
        "cache_misses": sum(1 for row in chunk_results if not row["cache_hit"]),
        "chunks": chunk_results,
        "preview_output": str(preview_output.relative_to(ROOT)),
        "trailing_silence_added": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

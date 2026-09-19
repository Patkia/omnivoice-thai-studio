"""Mission 19 listening pack: old cached boundary versus two rebalanced chunks."""
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
PREVIEW = ROOT / "output" / "semantic_chunk_preview.json"
MISSION17 = ROOT / "output" / "long_text_continuity_poc" / "report.json"
OUTPUT_DIR = ROOT / "output" / "continuity_boundary_poc"
STEPS = 32


def wav_meta(path: Path) -> dict:
    with wave.open(str(path), "rb") as source:
        return {"sample_rate": source.getframerate(), "channels": source.getnchannels(),
                "sample_width": source.getsampwidth(), "frames": source.getnframes()}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    preview = json.loads(PREVIEW.read_text(encoding="utf-8"))
    rows = [row for row in preview["chunks"] if row["text"].startswith("เขาหัวเราะ")
            or row["text"].lstrip().startswith("แต่เขาก็หยิบมันออกจากมือของฉัน แล้วก็ห่อ")]
    if len(rows) != 2 or not rows[1]["text"].lstrip().startswith("แต่เขาก็หยิบ"):
        raise RuntimeError("rebalanced semantic chunks 09–10 are not present")
    if any(row["char_count"] > 120 for row in rows):
        raise RuntimeError("rebalanced chunk exceeds hard max")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prior = json.loads(MISSION17.read_text(encoding="utf-8"))
    old_rows = prior["sets"]["fixed_seed"]
    old_paths = [ROOT / row["output"] for row in old_rows if row["index"] in (9, 10)]
    if len(old_paths) != 2 or not all(path.exists() for path in old_paths):
        raise FileNotFoundError("Mission 17 cached fixed-seed chunks 09–10 are unavailable")
    old_pauses = [row["pause_after_ms"] for row in old_rows if row["index"] in (9, 10)]
    old_output = OUTPUT_DIR / "old_boundary.wav"
    old_duration = merge(old_paths, old_output, pause_after_ms=old_pauses)

    registry = tts.load_json(ROOT / "approved_voice_profiles.json")
    speed = float(tts.resolve_voice("narrator", registry)["speed"])
    seed = resolve_continuity_seed("narrator")
    if seed != 15015:
        raise RuntimeError("expected fixed narrator seed 15015")
    adapter = StudioEngineAdapter()
    records, new_paths = [], []
    started = time.perf_counter()
    for row in rows:
        path = OUTPUT_DIR / f"rebalanced_chunk_{row['index']:02}.wav"
        result = adapter.generate(row["text"], "narrator", speed, STEPS, path, force=False, seed=seed)
        new_paths.append(path)
        records.append({"index": row["index"], "text": row["text"], "char_count": row["char_count"],
                        "boundary_type": row["boundary_type"], "pause_after_ms": row["pause_after_ms"],
                        "output": str(path.relative_to(ROOT)), "cache_hit": result["cache_hit"],
                        "model_load_seconds": result["model_load_seconds"],
                        "inference_seconds": result["inference_seconds"], "wav": wav_meta(path)})
    new_output = OUTPUT_DIR / "rebalanced_boundary.wav"
    new_duration = merge(new_paths, new_output, pause_after_ms=[row["pause_after_ms"] for row in rows])
    report = {
        "mission": "MISSION 19 — CONTINUITY-AWARE BOUNDARY REBALANCING",
        "model": adapter.engine["model"], "revision": adapter.engine["revision"], "voice": "narrator",
        "speed": speed, "steps": STEPS, "seed": seed,
        "old_boundary": {"source": "Mission 17 fixed-seed cached chunks 09–10", "paths": [str(p.relative_to(ROOT)) for p in old_paths],
                         "pause_after_ms": old_pauses, "output": str(old_output.relative_to(ROOT)), "duration_seconds": round(old_duration, 3)},
        "rebalanced_boundary": {"chunks": records, "output": str(new_output.relative_to(ROOT)),
                                 "duration_seconds": round(new_duration, 3)},
        "model_load_count": adapter.session.model_load_count, "device": adapter.session.device,
        "total_inference_seconds": round(sum(row["inference_seconds"] for row in records), 3),
        "total_wall_seconds": round(time.perf_counter() - started, 3),
        "cache_hits": sum(row["cache_hit"] for row in records),
        "cache_misses": sum(not row["cache_hit"] for row in records),
        "trailing_silence_added": False, "production_default": False,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

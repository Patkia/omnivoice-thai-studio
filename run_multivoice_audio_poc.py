"""Mission 14 A/B multi-voice POC; deliberately not a production speaker system."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from long_text_batch import merge
from studio_engine_adapter import StudioEngineAdapter
import tts


ROOT = Path(__file__).resolve().parent
SEMANTIC_PREVIEW = ROOT / "output" / "semantic_chunk_preview.json"
MISSION13_REPORT = ROOT / "output" / "semantic_audio_poc" / "report.json"
OUTPUT_DIR = ROOT / "output" / "multivoice_audio_poc"
REPORT_PATH = OUTPUT_DIR / "report.json"

# POC-only editorial assignments. They describe scene function, not a claim
# about character identity or the speaker's gender in the source text.
ASSIGNMENTS = (
    (6, "narration_transition", "narrator"),
    (8, "dialogue_contrast_poc", "bright_female"),
    (9, "dialogue_to_narration_transition", "narrator"),
    (12, "emotional_reflective_beat", "warm_female_2"),
    (19, "concluding_reflection", "warm_female_2"),
    (20, "final_concluding_narration", "narrator"),
)


def load_scene() -> list[dict]:
    payload = json.loads(SEMANTIC_PREVIEW.read_text(encoding="utf-8"))
    indexed = {row["index"]: row for row in payload["chunks"]}
    scene = []
    for index, role, voice in ASSIGNMENTS:
        if index not in indexed:
            raise RuntimeError(f"semantic preview is missing chunk {index}")
        row = dict(indexed[index])
        if row["char_count"] != len(row["text"]) or row["char_count"] > 120:
            raise RuntimeError(f"invalid hard_max metadata for chunk {index}")
        row.update(semantic_role=role, voice=voice)
        scene.append(row)
    return scene


def mission13_narrator_paths(scene: list[dict]) -> dict[int, Path]:
    report = json.loads(MISSION13_REPORT.read_text(encoding="utf-8"))
    if report.get("voice") != "narrator" or report.get("speed") != 0.94:
        raise RuntimeError("Mission 13 artifact does not match the approved narrator configuration")
    source = {row["index"]: ROOT / row["output"] for row in report["chunks"]}
    expected = {row["index"] for row in scene}
    if not expected.issubset(source):
        raise RuntimeError("Mission 13 cache is missing one or more selected chunks")
    for index in expected:
        if not source[index].is_file():
            raise RuntimeError(f"Mission 13 cached WAV is missing for chunk {index}")
    return source


def audit_voices() -> tuple[dict, dict]:
    registry = tts.load_json(ROOT / "approved_voice_profiles.json")
    aliases = {}
    for alias in registry.get("aliases", {}):
        voice = tts.resolve_voice(alias, registry)
        aliases[alias] = {
            "description": voice["description_th"],
            "speed": voice["speed"],
            "voice_instruction": voice["voice_instruction"],
        }
    required = ("narrator", "bright_female", "warm_female_2")
    missing = [alias for alias in required if alias not in aliases]
    if missing:
        raise RuntimeError(f"required voice aliases missing: {missing}")
    return registry, aliases


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    scene = load_scene()
    registry, voice_audit = audit_voices()
    narrator_paths = mission13_narrator_paths(scene)
    engine = tts.load_json(tts.ENGINE_PATH)
    steps = int(engine["default_steps"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    adapter = StudioEngineAdapter()
    multi_paths: list[Path] = []
    rows: list[dict] = []
    total_inference = 0.0
    started = time.perf_counter()
    for chunk in scene:
        alias = chunk["voice"]
        voice = tts.resolve_voice(alias, registry)
        if alias == "narrator":
            path = narrator_paths[chunk["index"]]
            generated = {"cache_hit": True, "model_load_seconds": 0.0, "inference_seconds": 0.0,
                         "cache_source": "Mission 13 exact narrator artifact"}
        else:
            path = OUTPUT_DIR / f"chunk_{chunk['index']:02}_{alias}.wav"
            generated = adapter.generate(chunk["text"], alias, float(voice["speed"]), steps, path, force=False)
            generated["cache_source"] = "Mission 14 adapter cache"
            total_inference += generated["inference_seconds"]
        multi_paths.append(path)
        rows.append({
            "chunk_id": chunk["index"], "text": chunk["text"], "semantic_role": chunk["semantic_role"],
            "voice": alias, "speed": voice["speed"], "pause_after_ms": chunk["pause_after_ms"],
            "boundary_type": chunk["boundary_type"], "dialogue": chunk["dialogue"],
            "output": str(path.relative_to(ROOT)), "cache_hit": generated["cache_hit"],
            "cache_source": generated["cache_source"], "model_load_seconds": generated["model_load_seconds"],
            "inference_seconds": generated["inference_seconds"],
        })

    pauses = [row["pause_after_ms"] for row in rows]
    single_paths = [narrator_paths[row["chunk_id"]] for row in rows]
    single_output = OUTPUT_DIR / "single_voice_preview.wav"
    multi_output = OUTPUT_DIR / "multi_voice_preview.wav"
    single_duration = merge(single_paths, single_output, pause_after_ms=pauses)
    multi_duration = merge(multi_paths, multi_output, pause_after_ms=pauses)
    report = {
        "mission": "MISSION 14 — MULTI-VOICE SEMANTIC AUDIO POC",
        "source_preview": str(SEMANTIC_PREVIEW.relative_to(ROOT)),
        "selected_chunks": [row["chunk_id"] for row in rows],
        "voice_audit": voice_audit,
        "voice_assignment": rows,
        "model": engine["model"], "revision": engine["revision"], "steps": steps,
        "device": adapter.session.device, "model_load_count": adapter.session.model_load_count,
        "model_load_seconds": sum(row["model_load_seconds"] for row in rows),
        "total_inference_seconds": round(total_inference, 3),
        "total_wall_seconds": round(time.perf_counter() - started, 3),
        "single_preview_duration_seconds": round(single_duration, 3),
        "multi_preview_duration_seconds": round(multi_duration, 3),
        "multi_preview_rtf": round(total_inference / multi_duration, 3) if multi_duration else None,
        "cache_hits": sum(1 for row in rows if row["cache_hit"]),
        "cache_misses": sum(1 for row in rows if not row["cache_hit"]),
        "single_preview": str(single_output.relative_to(ROOT)),
        "multi_preview": str(multi_output.relative_to(ROOT)),
        "trailing_silence_added": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

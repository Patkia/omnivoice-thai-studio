"""Dry-run-first fixtures for measuring application and model segmentation."""
from __future__ import annotations

from narrator_excitement_polish import BOUNDARY, build_excitement_plan
from narrator_single_inference_tuning import MODEL_CHUNK_THRESHOLD_TOKENS, _estimate_tokens


LENGTH_TARGETS = ((500, 2), (750, 3), (1000, 4))


def selected_conditions(winner: str) -> dict:
    plan = build_excitement_plan()
    if winner == "baseline":
        base = plan["baseline"]
        return {
            "winner": winner,
            "spoken_block": base["spoken_text"],
            "speed": base["speed"],
            "seed": base["seed"],
            "voice": base["voice"],
            "instruction": base["instruction"],
            "steps": base["steps"],
            "pause_strategy": base["punctuation_strategy"],
            "source_cache_key": base["cache_key"],
            "source_sha256": base["sha256"],
        }
    row = next((item for item in plan["candidates"] if item["name"] == winner), None)
    if row is None:
        raise ValueError("winner must be baseline, E1, or E2")
    return {
        "winner": winner,
        "spoken_block": row["spoken_text"],
        "speed": row["speed"],
        "seed": row["seed"],
        "voice": row["voice"],
        "instruction": row["instruction"],
        "steps": row["steps"],
        "pause_strategy": plan["baseline"]["punctuation_strategy"],
        "source_cache_key": row["cache_key"],
        "source_sha256": plan["baseline"]["sha256"],
    }


def build_length_sweep_plan(winner: str) -> dict:
    selected = selected_conditions(winner)
    fixtures = []
    for target, repeats in LENGTH_TARGETS:
        text = "\n".join([selected["spoken_block"]] * repeats)
        estimated_tokens = _estimate_tokens(text)
        fixtures.append({
            "target_characters": target,
            "actual_characters": len(text),
            "repeated_blocks": repeats,
            "text": text,
            "application_input_count": 1,
            "application_single_inference": True,
            "application_semantic_chunks": 0,
            "estimated_audio_tokens": estimated_tokens,
            "estimated_duration_seconds": round(estimated_tokens / 25, 3),
            "model_internal_segmentation_expected": estimated_tokens > MODEL_CHUNK_THRESHOLD_TOKENS,
            "target_boundary_count": text.count(BOUNDARY),
            "output": f"length_{len(text)}.wav",
        })
    return {
        "status": "READY_NOT_GENERATED",
        "winner": winner,
        "seed": selected["seed"],
        "voice": selected["voice"],
        "instruction": selected["instruction"],
        "speed": selected["speed"],
        "steps": selected["steps"],
        "pause_strategy": selected["pause_strategy"],
        "approved_baseline_cache_key": selected["source_cache_key"],
        "approved_baseline_sha256": selected["source_sha256"],
        "model_internal_threshold_tokens": MODEL_CHUNK_THRESHOLD_TOKENS,
        "model_internal_threshold_seconds": 30.0,
        "fixtures": fixtures,
        "measurements_on_execute": [
            "application single inference", "estimated audio tokens",
            "model internal segmentation triggered", "actual audio duration",
            "inference time", "process RSS before/after/peak", "model load count",
            "voice continuity (human)", "paragraph pause behavior (human)",
        ],
    }

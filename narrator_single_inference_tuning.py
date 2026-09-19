"""Deterministic plan for the narrator single-inference listening pack."""
from __future__ import annotations

import tts
from narrator_continuity_fixture import (
    CANONICAL_TEXT,
    EXPECTED_INSTRUCTION,
    EXPECTED_SPEED,
    STEPS,
    TARGET_PHRASE,
    TARGET_WORD,
    VOICE_ALIAS,
)
from omnivoice.utils.duration import RuleDurationEstimator
from studio_engine_adapter import generation_cache_keys, preview_text


BOUNDARY = "อย่างยุติธรรม\nในที่สุด"
SEED_CANDIDATES = (
    ("single_seed_A", 15014, "symmetric nearby seed: original seed - 2"),
    ("single_seed_B", 15015, "symmetric nearby seed: original seed - 1"),
    ("single_seed_C", 15017, "symmetric nearby seed: original seed + 1"),
    ("single_seed_D", 15018, "symmetric nearby seed: original seed + 2"),
)
PAUSE_CANDIDATES = (
    ("pause_candidate_A", 15016, ".", "period before the retained paragraph newline"),
    ("pause_candidate_B", 15016, "…", "ellipsis before the retained paragraph newline"),
)
MODEL_FRAME_RATE = 25
MODEL_CHUNK_THRESHOLD_SECONDS = 30.0
MODEL_CHUNK_THRESHOLD_TOKENS = 750


def pause_representation(mark: str) -> str:
    if CANONICAL_TEXT.count(BOUNDARY) != 1:
        raise RuntimeError("canonical pause boundary is not unique")
    return CANONICAL_TEXT.replace(BOUNDARY, f"อย่างยุติธรรม{mark}\nในที่สุด", 1)


def _cache_key(spoken: str, seed: int) -> str:
    engine = tts.load_json(tts.ENGINE_PATH)
    payload = {
        "text": spoken,
        "model": engine["model"],
        "revision": engine["revision"],
        "voice_instruction": EXPECTED_INSTRUCTION,
        "speed": EXPECTED_SPEED,
        "steps": STEPS,
        "sample_rate": engine["sample_rate"],
        "audio_normalization": tts.AUDIO_NORMALIZATION,
    }
    return generation_cache_keys(payload, seed)[0]


def _estimate_tokens(text: str) -> int:
    estimator = RuleDurationEstimator()
    return int(estimator.estimate_duration(text, "Nice to meet you.", 25))


def build_tuning_plan() -> dict:
    canonical_preview = preview_text(CANONICAL_TEXT, VOICE_ALIAS)
    canonical_spoken = canonical_preview["prepared"]["spoken"]
    candidates = []
    for name, seed, reason in SEED_CANDIDATES:
        candidates.append({
            "name": name,
            "kind": "seed_search",
            "seed": seed,
            "reason": reason,
            "canonical_text": CANONICAL_TEXT,
            "spoken_text": canonical_spoken,
            "voice": VOICE_ALIAS,
            "instruction": EXPECTED_INSTRUCTION,
            "speed": EXPECTED_SPEED,
            "steps": STEPS,
            "estimated_audio_tokens": _estimate_tokens(canonical_spoken),
            "single_inference_expected": _estimate_tokens(canonical_spoken) < MODEL_CHUNK_THRESHOLD_TOKENS,
            "cache_key": _cache_key(canonical_spoken, seed),
            "output": f"{name}.wav",
        })
    for name, seed, mark, reason in PAUSE_CANDIDATES:
        represented = pause_representation(mark)
        preview = preview_text(represented, VOICE_ALIAS)
        spoken = preview["prepared"]["spoken"]
        candidates.append({
            "name": name,
            "kind": "pause_poc",
            "seed": seed,
            "reason": reason,
            "boundary_mark": mark,
            "canonical_text": CANONICAL_TEXT,
            "spoken_text": spoken,
            "normalization_transformations": preview["prepared"]["normalization"],
            "pronunciation_substitutions": preview["prepared"]["substitutions"],
            "thai_only_gate": preview["prepared"]["gate"].thai_only_gate_passed,
            "voice": VOICE_ALIAS,
            "instruction": EXPECTED_INSTRUCTION,
            "speed": EXPECTED_SPEED,
            "steps": STEPS,
            "estimated_audio_tokens": _estimate_tokens(spoken),
            "single_inference_expected": _estimate_tokens(spoken) < MODEL_CHUNK_THRESHOLD_TOKENS,
            "cache_key": _cache_key(spoken, seed),
            "output": f"{name}.wav",
        })
    return {
        "canonical_text": CANONICAL_TEXT,
        "target_word": TARGET_WORD,
        "target_phrase": TARGET_PHRASE,
        "human_target_reference": "A_current_chunked chunk 2",
        "voice": VOICE_ALIAS,
        "instruction": EXPECTED_INSTRUCTION,
        "speed": EXPECTED_SPEED,
        "steps": STEPS,
        "model_chunk_threshold_seconds": MODEL_CHUNK_THRESHOLD_SECONDS,
        "model_chunk_threshold_tokens": MODEL_CHUNK_THRESHOLD_TOKENS,
        "candidates": candidates,
    }

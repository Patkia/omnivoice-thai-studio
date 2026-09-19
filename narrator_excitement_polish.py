"""Deterministic plan for narrator excitement candidates based on Pause B."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import tts
from narrator_continuity_fixture import TARGET_PHRASE, TARGET_WORD
from narrator_single_inference_tuning import MODEL_CHUNK_THRESHOLD_TOKENS, _estimate_tokens
from studio_engine_adapter import generation_cache_keys, preview_text


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "output" / "narrator_single_inference_tuning"
BASELINE_WAV = SOURCE / "pause_candidate_B.wav"
EXPECTED_BASELINE_SHA256 = "c0ae71bf1ea9b953eac4d98f0e434efab3e7302873647d6a9ff5c6f9b670f8e6"
EXPECTED_SEED = 15016
EXPECTED_VOICE = "bright_female"
EXPECTED_INSTRUCTION = "female, young adult, high pitch"
EXPECTED_SPEED = 1.0
EXPECTED_STEPS = 32
BOUNDARY = "อย่างยุติธรรม…\nในที่สุด"
OPENING = "เมื่อสงครามดำเนินมาถึงช่วงสุดท้าย "
FIRST_PARAGRAPH_END = "สงบศึกกันในที่สุด\nและ"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _baseline_evidence() -> dict:
    plan = json.loads((SOURCE / "tuning_plan.json").read_text(encoding="utf-8"))
    candidate = next(row for row in plan["candidates"] if row["name"] == "pause_candidate_B")
    report = json.loads((SOURCE / "generation_report.json").read_text(encoding="utf-8"))
    generation = next(
        row for row in reversed(report["runs"])
        if Path(row["output"]).name == "pause_candidate_B.part.wav"
        and row["cache_key"] == candidate["cache_key"]
    )
    actual_hash = sha256(BASELINE_WAV)
    checks = {
        "artifact_hash": actual_hash == EXPECTED_BASELINE_SHA256,
        "spoken_text": generation["final_spoken_text"] == candidate["spoken_text"],
        "seed": generation["seed"] == candidate["seed"] == EXPECTED_SEED,
        "voice": generation["voice_alias"] == candidate["voice"] == EXPECTED_VOICE,
        "instruction": generation["resolved_voice_instruction"] == candidate["instruction"] == EXPECTED_INSTRUCTION,
        "speed": generation["speed"] == candidate["speed"] == EXPECTED_SPEED,
        "steps": generation["steps"] == candidate["steps"] == EXPECTED_STEPS,
        "cache_key": generation["cache_key"] == candidate["cache_key"],
        "model": generation["model"] == "hotdogs/omnivoice-thai",
        "revision": generation["revision"] == "252d5f2815a5d7300c7676422bee69141c7756de",
        "single_application_input": candidate["single_inference_expected"] is True,
        "boundary": candidate["spoken_text"].count(BOUNDARY) == 1,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"Pause B baseline audit failed: {failed}")
    return {
        "canonical_text": candidate["canonical_text"],
        "spoken_text": candidate["spoken_text"],
        "punctuation_strategy": "ellipsis U+2026 immediately before retained paragraph newline at target boundary",
        "seed": candidate["seed"],
        "voice": candidate["voice"],
        "instruction": candidate["instruction"],
        "speed": candidate["speed"],
        "steps": candidate["steps"],
        "model": generation["model"],
        "revision": generation["revision"],
        "cache_key": candidate["cache_key"],
        "sha256": actual_hash,
        "duration_seconds": generation["duration_seconds"],
        "estimated_audio_tokens": candidate["estimated_audio_tokens"],
        "audit_checks": checks,
    }


def excitement_punctuation(spoken: str) -> str:
    """Add restrained emphasis away from the accepted target boundary."""
    if spoken.count(OPENING) != 1 or spoken.count(FIRST_PARAGRAPH_END) != 1:
        raise RuntimeError("Pause B context anchors are not unique")
    changed = spoken.replace(OPENING, OPENING.rstrip() + " — ", 1)
    return changed.replace(FIRST_PARAGRAPH_END, "สงบศึกกันในที่สุด!\nและ", 1)


def _cache_key(spoken: str, speed: float) -> str:
    engine = tts.load_json(tts.ENGINE_PATH)
    payload = {
        "text": spoken,
        "model": engine["model"],
        "revision": engine["revision"],
        "voice_instruction": EXPECTED_INSTRUCTION,
        "speed": speed,
        "steps": EXPECTED_STEPS,
        "sample_rate": engine["sample_rate"],
        "audio_normalization": tts.AUDIO_NORMALIZATION,
    }
    return generation_cache_keys(payload, EXPECTED_SEED)[0]


def build_excitement_plan() -> dict:
    baseline = _baseline_evidence()
    e1_spoken = preview_text(excitement_punctuation(baseline["spoken_text"]), EXPECTED_VOICE)["prepared"]["spoken"]
    rows = [
        {
            "name": "E1",
            "output": "excitement_E1.wav",
            "exact_change": "speech punctuation only: add em dash after opening clause and ! before first paragraph newline",
            "spoken_text": e1_spoken,
            "speed": EXPECTED_SPEED,
        },
        {
            "name": "E2",
            "output": "excitement_E2.wav",
            "exact_change": "speed only: 1.00 -> 1.03",
            "spoken_text": baseline["spoken_text"],
            "speed": 1.03,
        },
    ]
    for row in rows:
        prepared = preview_text(row["spoken_text"], EXPECTED_VOICE)["prepared"]
        estimated_tokens = max(1, int(_estimate_tokens(prepared["spoken"]) / row["speed"]))
        row.update({
            "canonical_text": baseline["canonical_text"],
            "seed": EXPECTED_SEED,
            "voice": EXPECTED_VOICE,
            "instruction": EXPECTED_INSTRUCTION,
            "steps": EXPECTED_STEPS,
            "normalization_transformations": prepared["normalization"],
            "pronunciation_substitutions": prepared["substitutions"],
            "thai_only_gate": prepared["gate"].thai_only_gate_passed,
            "estimated_audio_tokens": estimated_tokens,
            "model_internal_segmentation_expected": estimated_tokens > MODEL_CHUNK_THRESHOLD_TOKENS,
            "application_input_count": 1,
            "application_semantic_chunks": 0,
            "cache_key": _cache_key(prepared["spoken"], row["speed"]),
        })
    return {
        "status": "PLANNED",
        "baseline": baseline,
        "target_word": TARGET_WORD,
        "target_phrase": TARGET_PHRASE,
        "target_boundary": BOUNDARY,
        "candidates": rows,
    }

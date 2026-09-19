"""Canonical fixture and deterministic forensic helpers for narrator continuity."""
from __future__ import annotations

from dataclasses import asdict

import tts
from novel_chunker import semantic_chunks
from studio_engine_adapter import (
    generation_cache_keys,
    preview_text,
    resolve_generation_seed,
)


CANONICAL_TEXT = (
    "เมื่อสงครามดำเนินมาถึงช่วงสุดท้าย อาณาจักรทั้งสามที่กำลังเผชิญหน้ากับการล่มสลายก็ได้ตกลงเจรจาสงบศึกกันในที่สุด\n"
    "และได้ก่อตั้งองค์กรนอร์เซเลียขึ้นมา เพื่อเป็นตัวกลางในการดูแลการค้าเหล็กและเกลืออย่างยุติธรรม\n"
    "ในที่สุดความสงบสุขได้กลับคืนสู่ทุกอาณาจักร"
)
TARGET_WORD = "เจรจา"
TARGET_PHRASE = "และได้ก่อตั้งองค์กรนอร์เซเลียขึ้นมา"
VOICE_ALIAS = "bright_female"
EXPECTED_INSTRUCTION = "female, young adult, high pitch"
EXPECTED_SPEED = 1.0
EXPECTED_SEED = 15016
STEPS = 32
TARGET = 100
HARD_MAX = 120


def _span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


def build_forensic_plan() -> dict:
    """Trace the fixture without loading or invoking the model."""
    preview = preview_text(CANONICAL_TEXT, VOICE_ALIAS)
    prepared = preview["prepared"]
    voice = preview["voice"]
    effective_seed = resolve_generation_seed(voice, None)
    engine = tts.load_json(tts.ENGINE_PATH)
    chunks = semantic_chunks(prepared["spoken"], TARGET, HARD_MAX)
    target_word_span = _span(prepared["spoken"], TARGET_WORD)
    target_phrase_span = _span(prepared["spoken"], TARGET_PHRASE)
    offset = 0
    rows = []
    for chunk in chunks:
        start = offset
        end = start + chunk.char_count
        payload = {
            "text": chunk.text,
            "model": engine["model"],
            "revision": engine["revision"],
            "voice_instruction": voice["voice_instruction"],
            "speed": EXPECTED_SPEED,
            "steps": STEPS,
            "sample_rate": engine["sample_rate"],
            "audio_normalization": tts.AUDIO_NORMALIZATION,
        }
        cache_key, _ = generation_cache_keys(payload, effective_seed)
        rows.append({
            **asdict(chunk),
            "start_char_0": start,
            "end_char_exclusive_0": end,
            "contains_target_word": start <= target_word_span[0] and target_word_span[1] <= end,
            "contains_target_phrase": start <= target_phrase_span[0] and target_phrase_span[1] <= end,
            "cache_key": cache_key,
        })
        offset = end
    full_payload = {
        "text": prepared["spoken"],
        "model": engine["model"],
        "revision": engine["revision"],
        "voice_instruction": voice["voice_instruction"],
        "speed": EXPECTED_SPEED,
        "steps": STEPS,
        "sample_rate": engine["sample_rate"],
        "audio_normalization": tts.AUDIO_NORMALIZATION,
    }
    full_key, _ = generation_cache_keys(full_payload, effective_seed)
    return {
        "canonical_text": CANONICAL_TEXT,
        "normalized_text": prepared["normalized"],
        "spoken_text": prepared["spoken"],
        "normalization_transformations": prepared["normalization"],
        "pronunciation_substitutions": prepared["substitutions"],
        "thai_only_gate": prepared["gate"].thai_only_gate_passed,
        "voice_alias": VOICE_ALIAS,
        "instruction": voice["voice_instruction"],
        "effective_speed": EXPECTED_SPEED,
        "effective_seed": effective_seed,
        "steps": STEPS,
        "model": engine["model"],
        "revision": engine["revision"],
        "sample_rate": engine["sample_rate"],
        "target_word": TARGET_WORD,
        "target_word_span": {"start_char_0": target_word_span[0], "end_char_exclusive_0": target_word_span[1]},
        "target_phrase": TARGET_PHRASE,
        "target_phrase_span": {"start_char_0": target_phrase_span[0], "end_char_exclusive_0": target_phrase_span[1]},
        "chunks": rows,
        "single_inference_cache_key": full_key,
    }

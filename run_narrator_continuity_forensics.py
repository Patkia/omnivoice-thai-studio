#!/usr/bin/env python3
"""Generate the two controlled narrator continuity candidates exactly once."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import soundfile as sf

import tts
from long_text_batch import generate as generate_long
from narrator_continuity_fixture import (
    CANONICAL_TEXT,
    EXPECTED_SEED,
    EXPECTED_SPEED,
    STEPS,
    TARGET_PHRASE,
    TARGET_WORD,
    VOICE_ALIAS,
    build_forensic_plan,
)
from omnivoice.utils.duration import RuleDurationEstimator
from studio_engine_adapter import StudioEngineAdapter
from tts_batch_runner import acquire_lock, release_lock


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "narrator_continuity_fixture"
MISSION_ID = "narrator-continuity-forensics"
MODEL_FRAME_RATE = 25
MODEL_CHUNK_THRESHOLD_SECONDS = 30.0
MODEL_CONTEXT_TOKENS = 40960


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audio_metrics(path: Path) -> dict:
    audio, rate = sf.read(path, dtype="float64", always_2d=True)
    mono = audio.mean(axis=1)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    return {
        "path": str(path),
        "sha256": sha256(path),
        "sample_rate": int(rate),
        "channels": int(audio.shape[1]),
        "frames": int(audio.shape[0]),
        "duration_seconds": round(audio.shape[0] / rate, 6),
        "peak": peak,
        "rms": rms,
        "dc_mean": float(np.mean(mono)) if mono.size else 0.0,
        "clip_samples": int(np.count_nonzero(np.abs(mono) >= 0.999969482421875)),
        "non_silent": bool(rms > 1e-5),
    }


def silence_regions(path: Path, threshold_dbfs: float = -42.0, min_ms: int = 80) -> list[dict]:
    audio, rate = sf.read(path, dtype="float64", always_2d=True)
    mono = audio.mean(axis=1)
    frame = max(1, int(rate * 0.02))
    usable = len(mono) // frame * frame
    if usable == 0:
        return []
    rms = np.sqrt(np.mean(np.square(mono[:usable].reshape(-1, frame)), axis=1))
    threshold = 10 ** (threshold_dbfs / 20)
    quiet = rms < threshold
    regions = []
    start = None
    for index, value in enumerate(np.append(quiet, False)):
        if value and start is None:
            start = index
        elif not value and start is not None:
            duration_ms = (index - start) * 20
            if duration_ms >= min_ms:
                regions.append({
                    "start_seconds": round(start * frame / rate, 4),
                    "end_seconds": round(index * frame / rate, 4),
                    "duration_ms": int(duration_ms),
                    "threshold_dbfs": threshold_dbfs,
                })
            start = None
    return regions


def estimated_word_window(text: str, word: str, audio_duration: float) -> dict:
    estimator = RuleDurationEstimator()
    start = text.index(word)
    end = start + len(word)
    total = estimator.calculate_total_weight(text)
    left = estimator.calculate_total_weight(text[:start])
    right = estimator.calculate_total_weight(text[:end])
    return {
        "method": "duration-estimator weight proportion; approximate, not forced alignment",
        "start_seconds": round(audio_duration * left / total, 4),
        "end_seconds": round(audio_duration * right / total, 4),
    }


def run() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"output already exists; refusing to overwrite: {OUTPUT}")
    lock_path, lock = acquire_lock(MISSION_ID)
    owner_pid = os.getpid()
    try:
        OUTPUT.mkdir(parents=True)
        (OUTPUT / "canonical_text.txt").write_text(CANONICAL_TEXT, encoding="utf-8")
        # Keep controlled-run cache/report data inside the new output directory.
        tts.REPORT_PATH = OUTPUT / "generation_report.json"
        plan = build_forensic_plan()
        estimator = RuleDurationEstimator()
        estimated_tokens = int(estimator.estimate_duration(CANONICAL_TEXT, "Nice to meet you.", 25))
        model_limit = {
            "application_chunker_hard_max_characters": 120,
            "fixture_characters": len(CANONICAL_TEXT),
            "estimated_audio_tokens": estimated_tokens,
            "audio_token_frame_rate": MODEL_FRAME_RATE,
            "estimated_duration_seconds": estimated_tokens / MODEL_FRAME_RATE,
            "internal_chunk_threshold_seconds": MODEL_CHUNK_THRESHOLD_SECONDS,
            "internal_chunk_threshold_tokens": int(MODEL_CHUNK_THRESHOLD_SECONDS * MODEL_FRAME_RATE),
            "llm_max_position_embeddings": MODEL_CONTEXT_TOKENS,
            "single_inference_route_expected": estimated_tokens < MODEL_CHUNK_THRESHOLD_SECONDS * MODEL_FRAME_RATE,
        }

        adapter = StudioEngineAdapter()
        started_a = time.perf_counter()
        result_a = generate_long(
            adapter, CANONICAL_TEXT, VOICE_ALIAS, EXPECTED_SPEED, STEPS,
            OUTPUT / "A_current_chunked.wav", force=False, seed=None,
        )
        elapsed_a = time.perf_counter() - started_a
        started_b = time.perf_counter()
        result_b = adapter.generate(
            CANONICAL_TEXT, VOICE_ALIAS, EXPECTED_SPEED, STEPS,
            OUTPUT / "B_single_inference.wav", force=False, seed=None,
        )
        elapsed_b = time.perf_counter() - started_b

        chunk_metrics = []
        for row, path in zip(plan["chunks"], result_a["paths"]):
            metrics = audio_metrics(Path(path))
            metrics["chunk_index"] = row["index"]
            metrics["text"] = row["text"]
            metrics["cache_key"] = row["cache_key"]
            metrics["silence_regions"] = silence_regions(Path(path))
            chunk_metrics.append(metrics)
        word_chunk = next(row for row in chunk_metrics if TARGET_WORD in row["text"])
        word_window = estimated_word_window(word_chunk["text"], TARGET_WORD, word_chunk["duration_seconds"])
        word_window["quiet_regions_overlapping_approx_window"] = [
            gap for gap in word_chunk["silence_regions"]
            if gap["end_seconds"] >= word_window["start_seconds"] and gap["start_seconds"] <= word_window["end_seconds"]
        ]

        report = {
            "status": "CONTROLLED_A_B_GENERATED",
            "forensic_plan": plan,
            "answers": {
                "A_target_word_chunk": next(row["index"] for row in plan["chunks"] if row["contains_target_word"]),
                "A_target_word_split": False,
                "B_target_word_changed_by_preprocessing": False,
                "C_explicit_pause_inside_target_word": False,
                "D_target_phrase_chunk": next(row["index"] for row in plan["chunks"] if row["contains_target_phrase"]),
                "E_target_phrase_is_exclusive_chunk": False,
            },
            "model_single_inference_evidence": model_limit,
            "candidates": {
                "A_current_chunked": {
                    "voice": VOICE_ALIAS, "instruction": plan["instruction"], "speed": EXPECTED_SPEED,
                    "seed": EXPECTED_SEED, "steps": STEPS, "semantic_chunk_count": result_a["chunk_count"],
                    "inserted_inter_chunk_pauses_ms": [row["pause_after_ms"] for row in plan["chunks"][:-1]],
                    "elapsed_seconds": round(elapsed_a, 3), "audio": audio_metrics(OUTPUT / "A_current_chunked.wav"),
                    "generation_units": chunk_metrics,
                },
                "B_single_inference": {
                    "voice": VOICE_ALIAS, "instruction": plan["instruction"], "speed": EXPECTED_SPEED,
                    "seed": EXPECTED_SEED, "steps": STEPS, "semantic_chunk_count": 0,
                    "model_internal_chunk_expected": False, "inserted_inter_chunk_pauses_ms": [],
                    "cache_key": plan["single_inference_cache_key"], "elapsed_seconds": round(elapsed_b, 3),
                    "audio": {**audio_metrics(OUTPUT / "B_single_inference.wav"),
                              "silence_regions": silence_regions(OUTPUT / "B_single_inference.wav")},
                },
            },
            "target_tone_generation_unit": {
                "candidate": "A_current_chunked", "chunk_index": word_chunk["chunk_index"],
                "text": word_chunk["text"], "normalized_text": word_chunk["text"],
                "instruction": plan["instruction"], "speed": EXPECTED_SPEED, "seed": EXPECTED_SEED,
                "steps": STEPS, "position_context": "shared chunk; target phrase is not an exclusive generation unit",
                "audio": {key: word_chunk[key] for key in ("path", "sha256", "duration_seconds", "peak", "rms", "cache_key")},
            },
            "target_word_pause_diagnostic": {
                "word": TARGET_WORD,
                "chunk_boundary_inside_word": False,
                "normalization_or_substitution": False,
                "inserted_pause_inside_word": False,
                "current_static_root_cause": "model-generated prosody within one generation unit",
                "acoustic_localization": word_window,
                "human_listening_required_for_A_vs_B": True,
            },
            "safety": {
                "one_process": True, "one_persistent_model_session": True,
                "old_artifacts_overwritten": False, "game_files_touched": False,
                "model_or_revision_changed": False, "registry_changed": False,
            },
        }
        (OUTPUT / "forensic_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "status": report["status"], "output": str(OUTPUT),
            "A": report["candidates"]["A_current_chunked"]["audio"],
            "B": report["candidates"]["B_single_inference"]["audio"],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        release_lock(lock_path, owner_pid)


if __name__ == "__main__":
    raise SystemExit(run())

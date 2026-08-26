#!/usr/bin/env python3
"""Mission 5: deterministic, Thai-only generic female voice-palette runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

from thai_speech_normalizer import normalize_text
from thai_text_preprocessor import preprocess_with_details


ROOT = Path(__file__).resolve().parent
ENGINE_PATH = ROOT / "engine_config.json"
CANDIDATES_PATH = ROOT / "female_voice_candidates.json"
TEST_PATH = ROOT / "female_voice_palette_test.json"
REPORT_PATH = ROOT / "output" / "female_voice_palette" / "report.json"
ARCHETYPE_DIR = {"bright_young_female": "bright", "warm_young_female": "warm", "cute_teen_female": "cute_teen"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    return parser.parse_args()


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def cases(candidates: dict, test: dict) -> list[dict]:
    result = []
    for archetype, group in candidates.items():
        for variant in group["variants"]:
            for dialogue_id, source in test["dialogues"].items():
                stem = f"{variant['candidate_id']}_{dialogue_id}"
                result.append({**variant, "archetype": archetype, "dialogue_id": dialogue_id, "source_text": source,
                               "output": f"output/female_voice_palette/{ARCHETYPE_DIR[archetype]}/{stem}.wav"})
    return result


def prepare(case: dict, engine: dict) -> dict:
    normalized = normalize_text(case["source_text"], enabled=True)
    spoken, substitutions = preprocess_with_details(normalized.text, ROOT / engine["normalization"]["pronunciation_dictionary_path"], enabled=True)
    gate = normalize_text(spoken, enabled=False)
    payload = {"text": spoken, "model": engine["model"], "revision": engine["revision"], "voice": case["voice_instruction"], "speed": case["speed"], "steps": engine["default_steps"], "sample_rate": engine["sample_rate"]}
    return {"case": case, "normalized": normalized, "spoken": spoken, "substitutions": substitutions, "gate": gate,
            "key": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()}


def main() -> int:
    cli = parse_args()
    engine = json.loads(ENGINE_PATH.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    test = json.loads(TEST_PATH.read_text(encoding="utf-8"))
    all_cases = cases(candidates, test)
    selected = all_cases[cli.start:cli.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    by_output = {r["output"]: r for r in report.get("runs", [])}
    prepared = [prepare(case, engine) for case in selected]
    pending = [p for p in prepared if not (ROOT / p["case"]["output"]).exists() or p["case"]["output"] not in by_output or by_output[p["case"]["output"]].get("cache_key") != p["key"]]
    invalid = [p["case"]["candidate_id"] for p in pending if not p["gate"].thai_only_gate_passed]
    if invalid:
        raise RuntimeError("Thai-only gate failed: " + ", ".join(invalid))
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    warnings = ["ไม่พบ CUDA GPU; สร้างเสียงด้วย CPU ซึ่งใช้เวลานานกว่า"] if device == "cpu" else []
    model = None
    if pending:
        model = OmniVoice.from_pretrained(engine["model"], revision=engine["revision"], device_map=device, dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    generated = cached = 0
    for p in prepared:
        case, output = p["case"], ROOT / p["case"]["output"]
        old = by_output.get(case["output"])
        if output.exists() and old and old.get("cache_key") == p["key"]:
            old["cache_status"] = "hit"
            old["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            by_output[case["output"]] = old
            cached += 1
            continue
        started = time.perf_counter()
        audio = np.asarray(model.generate(p["spoken"], instruct=case["voice_instruction"], speed=case["speed"], num_step=engine["default_steps"])[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{case['candidate_id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, engine["sample_rate"], subtype="PCM_16")
        by_output[case["output"]] = {
            "cache_key": p["key"], "cache_status": "generated", "created_at": datetime.now(timezone.utc).isoformat(),
            "archetype": case["archetype"], "candidate_id": case["candidate_id"], "dialogue_id": case["dialogue_id"],
            "source_text": case["source_text"], "normalized_text": p["spoken"], "transformations": p["normalized"].transformations,
            "pronunciation_dictionary_substitutions": p["substitutions"], "voice_instruction": case["voice_instruction"],
            "runtime_supported_tags": case["runtime_supported_tags"], "speed": case["speed"], "steps": engine["default_steps"],
            "model": engine["model"], "revision": engine["revision"], "output": case["output"], "duration": duration(output),
            "generation_seconds": round(time.perf_counter() - started, 3), "device": device, "thai_only_gate_passed": p["gate"].thai_only_gate_passed,
            "warnings": warnings, "errors": [],
        }
        generated += 1
    report.update({"human_approved_baseline": test["human_approved_baseline"], "engine": engine, "candidate_config": str(CANDIDATES_PATH.name),
                   "runtime_supported_voice_tag_categories": {"gender": ["male", "female"], "age": ["child", "teenager", "young adult", "middle-aged", "elderly"], "pitch": ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"]},
                   "runtime_limitations": "Tags เช่น cute, playful, warm, bright และ storytelling ไม่ใช่ native voice-design tags ของ runtime นี้.",
                   "candidate_selection": "Disabled; human listening test is required.",
                   "runs": [by_output[c["output"]] for c in all_cases if c["output"] in by_output]})
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), "generated": generated, "cached": cached, "total": len(all_cases), "report": str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Mission 4 generic-engine candidate runner, with one model load per selected batch."""

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
PROFILES_PATH = ROOT / "voice_profiles.json"
TEST_PATH = ROOT / "engine_candidate_test.json"
REPORT_PATH = ROOT / "output" / "engine_candidate" / "report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    return parser.parse_args()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def build_cases(engine: dict, profiles: dict, tests: dict) -> list[dict]:
    cases: list[dict] = []
    for profile_id, profile in profiles.items():
        speeds = engine["narrator_speed_candidates"] if profile_id == "narrator" else [profile["default_speed"]]
        for text_id, source in tests["voice_texts"].items():
            for speed in speeds:
                cases.append({
                    "test_id": f"voice_{profile_id}_{text_id}_{str(speed).replace('.', '_')}", "kind": "voice_diversity",
                    "profile_id": profile_id, "voice_instruction": profile["voice_instruction"], "source_text": source,
                    "speed": speed, "output": f"output/engine_candidate/voices/{profile_id}_{text_id}_{str(speed).replace('.', '_')}.wav",
                })
    narrator = profiles["narrator"]
    for item in tests["artifact_tests"]:
        cases.append({**item, "test_id": item["id"], "kind": "artifact_test", "profile_id": "narrator", "voice_instruction": narrator["voice_instruction"], "speed": 0.94})
    return cases


def prepare(case: dict, engine: dict) -> dict:
    normalized = normalize_text(case["source_text"], enabled=engine["normalization"]["thai_speech_normalizer_enabled"])
    spoken, substitutions = preprocess_with_details(
        normalized.text, ROOT / engine["normalization"]["pronunciation_dictionary_path"], enabled=True
    )
    gate = normalize_text(spoken, enabled=False)
    cache_payload = {"text": spoken, "model": engine["model"], "revision": engine["revision"], "voice": case["voice_instruction"], "speed": case["speed"], "steps": engine["default_steps"], "sample_rate": engine["sample_rate"]}
    return {"case": case, "normalized": normalized, "spoken": spoken, "substitutions": substitutions, "gate": gate,
            "key": hashlib.sha256(json.dumps(cache_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()}


def main() -> int:
    cli = parse_args()
    engine = json.loads(ENGINE_PATH.read_text(encoding="utf-8"))
    profiles = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    tests = json.loads(TEST_PATH.read_text(encoding="utf-8"))
    all_cases = build_cases(engine, profiles, tests)
    selected = all_cases[cli.start:cli.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    # Migrate the first candidate-report format, which recorded output but omitted test_id.
    case_id_by_output = {str(Path(c["output"]).relative_to("output")): c["test_id"] for c in all_cases}
    for record in report.get("runs", []):
        if "test_id" not in record and record.get("output") in case_id_by_output:
            record["test_id"] = case_id_by_output[record["output"]]
    by_id = {r["test_id"]: r for r in report.get("runs", []) if "test_id" in r}
    prepared = [prepare(case, engine) for case in selected]
    pending = [p for p in prepared if not (ROOT / p["case"]["output"]).exists() or p["case"]["test_id"] not in by_id or by_id[p["case"]["test_id"]].get("cache_key") != p["key"]]
    invalid = [p["case"]["test_id"] for p in pending if not p["gate"].thai_only_gate_passed]
    if invalid:
        raise RuntimeError("Thai-only gate failed: " + ", ".join(invalid))
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    warnings = ["CUDA GPU was not available; generated on CPU."] if device == "cpu" else []
    model = None
    if pending:
        model = OmniVoice.from_pretrained(engine["model"], revision=engine["revision"], device_map=device, dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    generated = cached = 0
    for p in prepared:
        case, output = p["case"], ROOT / p["case"]["output"]
        old = by_id.get(case["test_id"])
        if output.exists() and old and old.get("cache_key") == p["key"]:
            old["cache_status"] = "hit"
            old["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            by_id[case["test_id"]] = old
            cached += 1
            continue
        started = time.perf_counter()
        audio = np.asarray(model.generate(p["spoken"], instruct=case["voice_instruction"], speed=case["speed"], num_step=engine["default_steps"])[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{case['test_id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, engine["sample_rate"], subtype="PCM_16")
        by_id[case["test_id"]] = {
            "cache_key": p["key"], "cache_status": "generated", "created_at": datetime.now(timezone.utc).isoformat(),
            "test_id": case["test_id"], "kind": case["kind"], "profile_id": case["profile_id"], "voice_instruction": case["voice_instruction"],
            "source_text": case["source_text"], "normalized_text": p["spoken"], "transformations": p["normalized"].transformations,
            "pronunciation_dictionary_substitutions": p["substitutions"], "thai_only_gate_passed": p["gate"].thai_only_gate_passed,
            "speed": case["speed"], "steps": engine["default_steps"], "model": engine["model"], "revision": engine["revision"],
            "duration": wav_duration(output), "generation_seconds": round(time.perf_counter() - started, 3), "device": device,
            "output": str(Path(case["output"]).relative_to("output")), "warnings": warnings, "errors": [],
        }
        generated += 1
    report.update({"engine": engine, "voice_profiles": profiles, "candidate_selection": "Disabled; human listening test required.",
                   "batch_model_load_behavior": "One model load per invocation with uncached work; none on a cache-only invocation.",
                   "runs": [by_id[c["test_id"]] for c in all_cases if c["test_id"] in by_id]})
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), "generated": generated, "cached": cached, "total": len(all_cases), "report": str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

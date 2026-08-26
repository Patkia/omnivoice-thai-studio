#!/usr/bin/env python3
"""Mission 6 generic mock-scene generator; one model load per selected batch."""

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
REGISTRY_PATH = ROOT / "approved_voice_profiles.json"
SCENE_PATH = ROOT / "mock_game_scene.json"
REPORT_PATH = ROOT / "output" / "final_validation" / "report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    return parser.parse_args()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def profile_index(registry: dict) -> dict:
    return {key: value for status in ("approved", "usable", "experimental_secondary") for key, value in registry.get(status, {}).items()}


def prepare(line: dict, profile: dict, engine: dict) -> dict:
    normalized = normalize_text(line["text"], enabled=True)
    spoken, substitutions = preprocess_with_details(normalized.text, ROOT / engine["normalization"]["pronunciation_dictionary_path"], enabled=True)
    gate = normalize_text(spoken, enabled=False)
    speed = line.get("speed", profile.get("speed"))
    if speed is None:
        raise ValueError(f"No concrete speed for {line['line_id']}")
    output = f"output/final_validation/lines/{line['line_id']}_{line['role']}.wav"
    payload = {"text": spoken, "model": engine["model"], "revision": engine["revision"], "voice": profile["voice_instruction"], "speed": speed, "steps": engine["default_steps"], "sample_rate": engine["sample_rate"]}
    return {"line": line, "profile": profile, "spoken": spoken, "normalized": normalized, "substitutions": substitutions, "gate": gate, "speed": speed, "output": output,
            "key": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()}


def main() -> int:
    cli = parse_args()
    engine = json.loads(ENGINE_PATH.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    scene = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    profiles = profile_index(registry)
    all_prepared = [prepare(line, profiles[line["profile_key"]], engine) for line in scene["lines"]]
    selected = all_prepared[cli.start:cli.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    by_id = {r["line_id"]: r for r in report.get("runs", [])}
    pending = [p for p in selected if not (ROOT / p["output"]).exists() or p["line"]["line_id"] not in by_id or by_id[p["line"]["line_id"]].get("cache_key") != p["key"]]
    invalid = [p["line"]["line_id"] for p in pending if not p["gate"].thai_only_gate_passed]
    if invalid:
        raise RuntimeError("Thai-only gate failed: " + ", ".join(invalid))
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    warnings = ["ไม่พบ CUDA GPU; สร้างเสียงด้วย CPU ซึ่งใช้เวลานานกว่า"] if device == "cpu" else []
    model = None
    if pending:
        model = OmniVoice.from_pretrained(engine["model"], revision=engine["revision"], device_map=device, dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    generated = cached = 0
    for p in selected:
        line, profile, output = p["line"], p["profile"], ROOT / p["output"]
        old = by_id.get(line["line_id"])
        if output.exists() and old and old.get("cache_key") == p["key"]:
            old["cache_status"] = "hit"
            old["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            by_id[line["line_id"]] = old
            cached += 1
            continue
        started = time.perf_counter()
        audio = np.asarray(model.generate(p["spoken"], instruct=profile["voice_instruction"], speed=p["speed"], num_step=engine["default_steps"])[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{line['line_id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, engine["sample_rate"], subtype="PCM_16")
        by_id[line["line_id"]] = {
            "cache_key": p["key"], "cache_status": "generated", "created_at": datetime.now(timezone.utc).isoformat(), "line_id": line["line_id"],
            "role": line["role"], "profile_key": line["profile_key"], "source_text": line["text"], "normalized_text": p["spoken"],
            "transformations": p["normalized"].transformations, "pronunciation_dictionary_substitutions": p["substitutions"],
            "thai_only_gate_passed": p["gate"].thai_only_gate_passed, "voice_instruction": profile["voice_instruction"], "speed": p["speed"],
            "steps": engine["default_steps"], "model": engine["model"], "revision": engine["revision"], "output": p["output"],
            "duration": wav_duration(output), "generation_seconds": round(time.perf_counter() - started, 3), "device": device, "warnings": warnings, "errors": []}
        generated += 1
    report.update({"scene": scene, "engine": engine, "registry": "approved_voice_profiles.json", "technical_pipeline_status": "TECHNICAL_PIPELINE_READY pending final regression", "runs": [by_id[p["line"]["line_id"]] for p in all_prepared if p["line"]["line_id"] in by_id]})
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), "generated": generated, "cached": cached, "report": str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

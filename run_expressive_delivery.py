#!/usr/bin/env python3
"""Mission 7 controlled expressive-delivery runner; one model load per selected batch."""

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
CONFIG_PATH = ROOT / "expressive_delivery_candidates.json"
REPORT_PATH = ROOT / "output" / "expressive_delivery" / "report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    return parser.parse_args()


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def prepare(candidate: dict, engine: dict) -> dict:
    normalized = normalize_text(candidate["input_text"], enabled=True)
    spoken, substitutions = preprocess_with_details(normalized.text, ROOT / engine["normalization"]["pronunciation_dictionary_path"], enabled=True)
    gate = normalize_text(spoken, enabled=False)
    output = f"output/expressive_delivery/{candidate['candidate_id']}.wav"
    payload = {"text": spoken, "model": engine["model"], "revision": engine["revision"], "voice": candidate["voice_instruction"], "speed": candidate["speed"], "steps": engine["default_steps"], "sample_rate": engine["sample_rate"]}
    return {"candidate": candidate, "normalized": normalized, "spoken": spoken, "substitutions": substitutions, "gate": gate, "output": output,
            "key": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()}


def main() -> int:
    cli = parse_args()
    engine = json.loads(ENGINE_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    all_prepared = [prepare(candidate, engine) for candidate in config["candidates"]]
    selected = all_prepared[cli.start:cli.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    by_id = {r["candidate_id"]: r for r in report.get("runs", [])}
    pending = [p for p in selected if not (ROOT / p["output"]).exists() or p["candidate"]["candidate_id"] not in by_id or by_id[p["candidate"]["candidate_id"]].get("cache_key") != p["key"]]
    invalid = [p["candidate"]["candidate_id"] for p in pending if not p["gate"].thai_only_gate_passed]
    if invalid:
        raise RuntimeError("Thai-only gate failed: " + ", ".join(invalid))
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    warnings = ["ไม่พบ CUDA GPU; สร้างเสียงด้วย CPU ซึ่งใช้เวลานานกว่า"] if device == "cpu" else []
    model = None
    if pending:
        model = OmniVoice.from_pretrained(engine["model"], revision=engine["revision"], device_map=device, dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    generated = cached = 0
    for p in selected:
        candidate, output = p["candidate"], ROOT / p["output"]
        old = by_id.get(candidate["candidate_id"])
        if output.exists() and old and old.get("cache_key") == p["key"]:
            old["cache_status"] = "hit"
            old["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            by_id[candidate["candidate_id"]] = old
            cached += 1
            continue
        started = time.perf_counter()
        audio = np.asarray(model.generate(p["spoken"], instruct=candidate["voice_instruction"], speed=candidate["speed"], num_step=engine["default_steps"])[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{candidate['candidate_id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, engine["sample_rate"], subtype="PCM_16")
        by_id[candidate["candidate_id"]] = {
            "cache_key": p["key"], "cache_status":"generated", "created_at":datetime.now(timezone.utc).isoformat(),
            "source_line_id":candidate["source_line_id"], "candidate_id":candidate["candidate_id"], "source_text":candidate["input_text"], "tts_input_text":p["spoken"],
            "punctuation_changes":candidate["punctuation_strategy"], "voice_instruction":candidate["voice_instruction"], "speed":candidate["speed"],
            "native_emotion_control_available":False, "model":engine["model"], "revision":engine["revision"], "steps":engine["default_steps"],
            "duration":duration(output), "generation_seconds":round(time.perf_counter()-started,3), "output":p["output"], "device":device,
            "thai_only_gate_passed":p["gate"].thai_only_gate_passed, "pronunciation_dictionary_substitutions":p["substitutions"], "warnings":warnings, "errors":[]}
        generated += 1
    report.update({"native_emotion_control_available":False, "native_emotion_control_status":"native emotion control unavailable", "strategy":"controlled speed plus punctuation/phrasing; no unsupported style tags", "preset_for_preview":config["preset_for_preview"], "runs":[by_id[p["candidate"]["candidate_id"]] for p in all_prepared if p["candidate"]["candidate_id"] in by_id]})
    REPORT_PATH.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"selected":len(selected),"generated":generated,"cached":cached,"report":str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

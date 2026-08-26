#!/usr/bin/env python3
"""Generate the fixed Mission 1 pronunciation set while loading OmniVoice once."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

from thai_text_preprocessor import preprocess_text


ROOT = Path(__file__).resolve().parent
TEST_PATH = ROOT / "pronunciation_test.json"
DICT_PATH = ROOT / "pronunciation_dictionary.json"
REPORT_PATH = ROOT / "output" / "pronunciation" / "report.json"


def key_for(case: dict, baseline: dict) -> str:
    payload = {"text": case["input_text"], **baseline, "normalization": "peak -1 dBFS"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def main() -> int:
    spec = json.loads(TEST_PATH.read_text(encoding="utf-8"))
    baseline = spec["baseline"]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    existing = {entry["cache_key"]: entry for entry in report.get("runs", [])}
    pending = [case for case in spec["test_cases"] if not (ROOT / case["output"]).exists() or key_for(case, baseline) not in existing]
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    warnings = ["CUDA GPU was not available; generated on CPU."] if device == "cpu" else []
    model = None
    if pending:
        model = OmniVoice.from_pretrained(
            baseline["model"], revision=baseline["revision"], device_map=device,
            dtype=torch.float16 if device.startswith("cuda") else torch.float32,
        )
    resolved_revision = getattr(getattr(model, "config", None), "_commit_hash", None) if model else None
    entries = []
    for case in spec["test_cases"]:
        output = ROOT / case["output"]
        cache_key = key_for(case, baseline)
        if output.exists() and cache_key in existing:
            entry = existing[cache_key]
            entry["cache_status"] = "hit"
            entry["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            entries.append(entry)
            continue
        started = time.perf_counter()
        # The test itself compares literal spellings; preprocessing remains disabled.
        input_text = preprocess_text(case["input_text"], DICT_PATH, enabled=False)
        audio = np.asarray(model.generate(
            input_text, instruct=baseline["voice_instruction"], speed=baseline["speed"],
            num_step=baseline["steps"],
        )[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{case['id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, baseline["sample_rate"], subtype="PCM_16")
        entries.append({
            "cache_key": cache_key, "cache_status": "generated",
            "created_at": datetime.now(timezone.utc).isoformat(), "test_id": case["id"],
            "original_word": case["original_word"], "candidate_spelling": case["candidate_spelling"],
            "full_input_text": input_text, "preprocessing_enabled": False,
            "model": baseline["model"], "revision": resolved_revision or baseline["revision"],
            "voice_instruction": baseline["voice_instruction"], "speed": baseline["speed"],
            "steps": baseline["steps"], "output_filename": output.name,
            "sample_rate": baseline["sample_rate"], "duration_seconds": duration(output),
            "generation_seconds": round(time.perf_counter() - started, 3), "device": device,
            "warnings": warnings, "errors": [],
        })
    report.update({
        "mission": spec["mission"], "baseline": baseline, "candidate_selection": "Waiting for human listening test; no candidate has been selected.",
        "batch_model_load_behavior": "One model load per runner invocation when generation is needed; none when all entries are cached.",
        "runs": entries,
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"generated": len(pending), "cached": len(spec["test_cases"]) - len(pending), "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Mission 2 runner: fixed Thai stress corpus, one OmniVoice load per batch."""

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

from thai_text_preprocessor import preprocess_with_details


ROOT = Path(__file__).resolve().parent
SPEC_PATH = ROOT / "pronunciation_stress_test.json"
DICT_PATH = ROOT / "pronunciation_dictionary.json"
REPORT_PATH = ROOT / "output" / "pronunciation_stress" / "report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="Zero-based inclusive test-case index")
    parser.add_argument("--end", type=int, help="Zero-based exclusive test-case index")
    return parser.parse_args()


def cache_key(case: dict, baseline: dict, preprocessed_text: str) -> str:
    payload = {"text": preprocessed_text, **baseline, "normalization": "peak -1 dBFS"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def main() -> int:
    args = parse_args()
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    baseline = spec["baseline"]
    all_cases = spec["test_cases"]
    selected = all_cases[args.start:args.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    by_id = {entry["test_id"]: entry for entry in report.get("runs", [])}
    prepared = []
    for case in selected:
        text, substitutions = preprocess_with_details(
            case["original_text"], DICT_PATH, enabled=baseline["preprocessing_enabled"]
        )
        prepared.append((case, text, substitutions, cache_key(case, baseline, text)))
    pending = [item for item in prepared if not (ROOT / item[0]["output"]).exists() or item[0]["id"] not in by_id or by_id[item[0]["id"]].get("cache_key") != item[3]]
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    warnings = ["CUDA GPU was not available; generated on CPU."] if device == "cpu" else []
    model = None
    if pending:
        model = OmniVoice.from_pretrained(
            baseline["model"], revision=baseline["revision"], device_map=device,
            dtype=torch.float16 if device.startswith("cuda") else torch.float32,
        )
    revision = getattr(getattr(model, "config", None), "_commit_hash", None) if model else baseline["revision"]
    generated = cached = 0
    for case, text, substitutions, key in prepared:
        output = ROOT / case["output"]
        old = by_id.get(case["id"])
        if output.exists() and old and old.get("cache_key") == key:
            old["cache_status"] = "hit"
            old["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            by_id[case["id"]] = old
            cached += 1
            continue
        started = time.perf_counter()
        audio = np.asarray(model.generate(
            text, instruct=baseline["voice_instruction"], speed=baseline["speed"], num_step=baseline["steps"]
        )[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{case['id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, baseline["sample_rate"], subtype="PCM_16")
        by_id[case["id"]] = {
            "cache_key": key, "cache_status": "generated", "created_at": datetime.now(timezone.utc).isoformat(),
            "test_id": case["id"], "category": case["category"], "original_text": case["original_text"],
            "preprocessed_text": text, "pronunciation_substitutions_applied": substitutions,
            "model": baseline["model"], "revision": revision, "voice_instruction": baseline["voice_instruction"],
            "speed": baseline["speed"], "steps": baseline["steps"], "output_filename": output.name,
            "sample_rate": baseline["sample_rate"], "duration_seconds": duration(output),
            "generation_seconds": round(time.perf_counter() - started, 3), "device": device,
            "warnings": warnings, "errors": [],
        }
        generated += 1
    report.update({
        "mission": spec["mission"], "baseline": baseline,
        "accepted_dictionary_entries": {"แอปเปิล": "แอ๊ปเปิ้ล"},
        "automatic_candidate_selection": "Disabled; human listening test is required.",
        "batch_model_load_behavior": "One model load per runner invocation when its selected batch contains uncached work; none for an all-cache batch.",
        "runs": [by_id[case["id"]] for case in all_cases if case["id"] in by_id],
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), "generated": generated, "cached": cached, "report": str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

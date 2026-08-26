#!/usr/bin/env python3
"""Mission 3 focused Thai-only synthesis runner; one model load per selected batch."""

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
SPEC_PATH = ROOT / "thai_normalization_test.json"
DICT_PATH = ROOT / "pronunciation_dictionary.json"
REPORT_PATH = ROOT / "output" / "thai_normalization" / "report.json"


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    return parser.parse_args()


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def key_for(case: dict, baseline: dict, spoken: str) -> str:
    payload = {
        "spoken_text": spoken, "model": baseline["model"], "revision": baseline["revision"],
        "voice": baseline["voice"], "speed": case.get("speed", baseline["speed"]),
        "steps": baseline["steps"], "sample_rate": baseline["sample_rate"], "normalization": "peak -1 dBFS",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def prepare(case: dict, baseline: dict) -> dict:
    normalized = normalize_text(case["source_text"], enabled=True, time_style=case.get("time_style", "natural"))
    spoken, dictionary_subs = preprocess_with_details(normalized.text, DICT_PATH, enabled=True)
    # The gate is evaluated after both recorded stages, immediately before TTS.
    gate = normalize_text(spoken, enabled=False)
    return {
        "case": case, "normalized": normalized, "spoken": spoken, "dictionary_subs": dictionary_subs,
        "latin_remaining": gate.latin_remaining, "arabic_digits_remaining": gate.arabic_digits_remaining,
        "gate_passed": gate.thai_only_gate_passed, "key": key_for(case, baseline, spoken),
    }


def main() -> int:
    cli = args()
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    baseline, all_cases = spec["baseline"], spec["test_cases"]
    selected = all_cases[cli.start:cli.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {"runs": []}
    by_id = {x["test_id"]: x for x in report.get("runs", [])}
    prepared = [prepare(case, baseline) for case in selected]
    pending = [p for p in prepared if not (ROOT / p["case"]["output"]).exists() or p["case"]["id"] not in by_id or by_id[p["case"]["id"]].get("cache_key") != p["key"]]
    invalid = [p for p in pending if not p["gate_passed"]]
    if invalid:
        details = ", ".join(p["case"]["id"] for p in invalid)
        raise RuntimeError(f"Thai-only gate failed; no TTS generated for: {details}")
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
    for p in prepared:
        case, output = p["case"], ROOT / p["case"]["output"]
        old = by_id.get(case["id"])
        if output.exists() and old and old.get("cache_key") == p["key"]:
            old["category"] = case["category"]
            old["cache_status"] = "hit"
            old["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            by_id[case["id"]] = old
            cached += 1
            continue
        started = time.perf_counter()
        audio = np.asarray(model.generate(
            p["spoken"], instruct=baseline["voice"], speed=case.get("speed", baseline["speed"]),
            num_step=baseline["steps"],
        )[0], dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0:
            raise RuntimeError(f"{case['id']} produced silent audio")
        audio *= (10 ** (-1 / 20)) / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, baseline["sample_rate"], subtype="PCM_16")
        by_id[case["id"]] = {
            "cache_key": p["key"], "cache_status": "generated", "created_at": datetime.now(timezone.utc).isoformat(),
            "test_id": case["id"], "source_text": case["source_text"], "normalized_text": p["spoken"],
            "category": case["category"],
            "transformations": p["normalized"].transformations, "latin_remaining": p["latin_remaining"],
            "arabic_digits_remaining": p["arabic_digits_remaining"], "thai_only_gate_passed": p["gate_passed"],
            "pronunciation_dictionary_substitutions": p["dictionary_subs"], "model": baseline["model"],
            "revision": revision, "voice": baseline["voice"], "speed": case.get("speed", baseline["speed"]),
            "steps": baseline["steps"], "output": output.name, "duration": duration(output),
            "generation_seconds": round(time.perf_counter() - started, 3), "device": device,
            "warnings": warnings, "errors": [],
        }
        generated += 1
    report.update({
        "mission": spec["mission"], "baseline": baseline,
        "approved_dictionary_entries": {"แอปเปิล": "แอ๊ปเปิ้ล"},
        "candidate_selection": "Disabled; all non-approved candidates require human listening test.",
        "batch_model_load_behavior": "One model load per runner invocation when selected work is uncached; none for a fully cached invocation.",
        "runs": [by_id[c["id"]] for c in all_cases if c["id"] in by_id],
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), "generated": generated, "cached": cached, "report": str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

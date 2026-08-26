#!/usr/bin/env python3
"""Local, pretrained-only Thai TTS runner for the OmniVoice POC."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice


MODEL_ID = "hotdogs/omnivoice-thai"
SAMPLE_RATE = 24_000
DEFAULT_INSTRUCT = "male, middle-aged, low pitch"
VALID_INSTRUCT_ITEMS = {
    "american accent", "australian accent", "british accent", "canadian accent", "child",
    "chinese accent", "elderly", "female", "high pitch", "indian accent", "japanese accent",
    "korean accent", "low pitch", "male", "middle-aged", "moderate pitch", "portuguese accent",
    "russian accent", "teenager", "very high pitch", "very low pitch", "whisper", "young adult",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate local Thai TTS with OmniVoice Thai.")
    p.add_argument("--text", required=True, help="Thai text to synthesize")
    p.add_argument("--output", required=True, type=Path, help="Destination WAV file")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--revision", default="main")
    p.add_argument("--voice", help="Alias for a voice-design instruction")
    p.add_argument("--speaker", help="Alias for a voice-design instruction")
    p.add_argument("--style", help="Additional supported voice-design tags")
    p.add_argument("--speed", type=float, default=0.94, help="Speaking-rate multiplier")
    p.add_argument("--steps", type=int, default=32, help="Diffusion steps")
    p.add_argument("--reference-audio", type=Path, help="Reserved; disabled for this POC")
    p.add_argument("--force", action="store_true", help="Regenerate even when cached")
    return p.parse_args()


def cache_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as f:
        return round(f.getnframes() / f.getframerate(), 3)


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"runs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": [], "warnings": ["Existing report.json was invalid and has been replaced."]}


def resolve_instruct(*values: str | None) -> tuple[str, list[str]]:
    """Keep only the finite set of voice-design tags accepted by OmniVoice."""
    requested = [part.strip() for value in values if value for part in value.split(",") if part.strip()]
    accepted = [part for part in requested if part.lower() in VALID_INSTRUCT_ITEMS]
    dropped = [part for part in requested if part.lower() not in VALID_INSTRUCT_ITEMS]
    if not accepted:
        accepted = DEFAULT_INSTRUCT.split(", ")
        if requested:
            dropped.append("No supported tags supplied; used default male, middle-aged, low pitch")
    return ", ".join(accepted), dropped


def main() -> int:
    args = parse_args()
    if args.reference_audio:
        raise SystemExit("--reference-audio is disabled: this POC does not perform voice cloning.")
    if not 0.25 <= args.speed <= 3.0:
        raise SystemExit("--speed must be between 0.25 and 3.0")
    if args.steps < 1:
        raise SystemExit("--steps must be positive")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.output.parent / "report.json"
    instruct, unsupported_tags = resolve_instruct(args.voice, args.speaker, args.style)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    payload = {
        "text": args.text, "model": args.model, "revision": args.revision,
        "instruct": instruct, "speed": args.speed, "steps": args.steps,
        "sample_rate": SAMPLE_RATE, "normalization": "peak -1 dBFS",
    }
    key = cache_key(payload)
    report = load_report(report_path)
    cached = next((r for r in report.get("runs", []) if r.get("cache_key") == key and r.get("output") == str(args.output.name)), None)
    if args.output.exists() and cached and not args.force:
        cached["cache_hit_at"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"CACHE HIT: {args.output}")
        return 0

    warnings: list[str] = []
    if unsupported_tags:
        warnings.append("Unsupported voice/style phrases were ignored: " + "; ".join(unsupported_tags))
    if device == "cpu":
        warnings.append("CUDA GPU was not available; generated on CPU. This will be substantially slower.")
    started = time.perf_counter()
    model = OmniVoice.from_pretrained(args.model, revision=args.revision, device_map=device, dtype=dtype)
    audio = model.generate(args.text, instruct=instruct, speed=args.speed, num_step=args.steps)[0]
    audio = np.asarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak == 0:
        raise RuntimeError("Model returned silent audio.")
    audio *= (10 ** (-1 / 20)) / peak
    sf.write(args.output, audio, SAMPLE_RATE, subtype="PCM_16")
    elapsed = round(time.perf_counter() - started, 3)
    resolved_revision = getattr(getattr(model, "config", None), "_commit_hash", None) or args.revision
    entry = {
        "cache_key": key, "created_at": datetime.now(timezone.utc).isoformat(),
        "output": args.output.name, "model": args.model, "revision": resolved_revision,
        "speaker_style": instruct, "generation_parameters": {"speed": args.speed, "num_step": args.steps},
        "sample_rate": SAMPLE_RATE, "duration_seconds": wav_duration(args.output),
        "generation_seconds": elapsed, "device": device, "torch": torch.__version__,
        "cuda_version": torch.version.cuda, "platform": platform.platform(), "warnings": warnings, "errors": [],
    }
    report["model"] = args.model
    report["sample_rate"] = SAMPLE_RATE
    report["runs"] = [r for r in report.get("runs", []) if not (r.get("cache_key") == key and r.get("output") == args.output.name)] + [entry]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

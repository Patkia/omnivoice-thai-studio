#!/usr/bin/env python3
"""Production-oriented local CLI for the frozen OmniVoice Thai Engine v1."""

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
from audio_validation import validate_audible_audio
import torch

from thai_speech_normalizer import normalize_text
from thai_text_preprocessor import preprocess_with_details


ROOT = Path(__file__).resolve().parent
ENGINE_PATH = ROOT / "engine_config.json"
REGISTRY_PATH = ROOT / "approved_voice_profiles.json"
REPORT_PATH = ROOT / "output" / "tts_report.json"
AUDIO_NORMALIZATION = "peak -1 dBFS"
MAX_RECOMMENDED_CHARACTERS = 1_000


def configure_utf8_console() -> None:
    """Keep Thai CLI output usable in legacy Windows console code pages."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


class TtsInputError(ValueError):
    """A clear user-facing input or production-gate error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="สร้างเสียงภาษาไทยด้วย Thai TTS Engine v1")
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--text", help="ข้อความภาษาไทยที่จะสร้างเสียง")
    source.add_argument("--text-file", type=Path, help="ไฟล์ข้อความ UTF-8 ภาษาไทย")
    parser.add_argument("--voice", help="ชื่อ voice alias; ดูรายการด้วย --list-voices")
    parser.add_argument("--output", type=Path, help="ปลายทางไฟล์ WAV (จำเป็นเมื่อไม่ได้ใช้ --dry-run)")
    parser.add_argument("--speed", type=float, help="อัตราความเร็วเสียงพูด; override ค่า voice profile")
    parser.add_argument("--steps", type=int, help="จำนวน diffusion steps; ค่าเริ่มต้นจาก engine config")
    parser.add_argument("--force", action="store_true", help="สร้างใหม่แม้ cache ตรงกัน")
    parser.add_argument("--show-normalized", action="store_true", help="แสดงผล normalization และ Thai-only gate")
    parser.add_argument("--dry-run", action="store_true", help="ตรวจ pipeline โดยไม่โหลด model และไม่สร้าง WAV")
    parser.add_argument("--list-voices", action="store_true", help="แสดง voice aliases ที่ใช้งานได้ โดยไม่โหลด model")
    args = parser.parse_args()
    if args.list_voices:
        if args.text or args.text_file or args.output or args.voice or args.speed is not None or args.steps is not None or args.force or args.dry_run or args.show_normalized:
            parser.error("--list-voices ใช้เดี่ยว ๆ เท่านั้น")
        return args
    if not args.text and not args.text_file:
        parser.error("ต้องระบุ --text หรือ --text-file อย่างใดอย่างหนึ่ง")
    if not args.voice:
        parser.error("ต้องระบุ --voice; ใช้ --list-voices เพื่อดูรายการ")
    if not args.dry_run and not args.output:
        parser.error("ต้องระบุ --output เมื่อสร้าง WAV")
    if args.speed is not None and not 0.25 <= args.speed <= 3.0:
        parser.error("--speed ต้องอยู่ระหว่าง 0.25 และ 3.0")
    if args.steps is not None and args.steps < 1:
        parser.error("--steps ต้องเป็นจำนวนเต็มบวก")
    return args


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def profile_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: value for section in ("approved", "usable", "experimental_secondary") for key, value in registry.get(section, {}).items()}


def resolve_voice(alias: str, registry: dict[str, Any]) -> dict[str, Any]:
    alias_data = registry.get("aliases", {}).get(alias)
    if not alias_data:
        choices = ", ".join(registry.get("aliases", {}))
        raise TtsInputError(f"ไม่พบ voice alias '{alias}'. ใช้ได้: {choices}")
    profile = profile_index(registry).get(alias_data["profile_key"])
    if not profile:
        raise RuntimeError(f"registry ของ alias '{alias}' อ้าง profile ที่ไม่มีอยู่")
    if "speed" not in profile:
        raise RuntimeError(f"profile '{alias_data['profile_key']}' ไม่มี default speed ที่ใช้งานจริง")
    return {"alias": alias, "profile_key": alias_data["profile_key"], "description_th": alias_data["description_th"],
            "seed": profile.get("seed"), **profile}


def read_source(args: argparse.Namespace) -> tuple[str, str]:
    if args.text is not None:
        return args.text, "text"
    try:
        return args.text_file.read_text(encoding="utf-8"), "text-file"
    except UnicodeDecodeError as exc:
        raise TtsInputError(f"อ่าน {args.text_file} ไม่ได้: ต้องเป็น UTF-8") from exc
    except OSError as exc:
        raise TtsInputError(f"อ่าน {args.text_file} ไม่ได้: {exc}") from exc


def prepare_text(source_text: str, dictionary_path: Path, *, spoken_override: str | None = None) -> dict[str, Any]:
    normalized = normalize_text(source_text, enabled=True)
    if spoken_override is None:
        spoken, substitutions = preprocess_with_details(normalized.text, dictionary_path, enabled=True)
    else:
        # Explicit TTS text is authored for speech and must preserve intentional
        # whitespace without changing canonical/source normalization.
        spoken, substitutions = spoken_override, []
    gate = normalize_text(spoken, enabled=False)
    return {"original": source_text, "normalized": normalized.text, "spoken": spoken, "normalization": normalized.transformations, "substitutions": substitutions, "gate": gate}


def validate_gate(prepared: dict[str, Any]) -> None:
    gate = prepared["gate"]
    if not gate.thai_only_gate_passed:
        kinds: list[str] = []
        if gate.latin_remaining:
            kinds.append("Latin A-Z/a-z")
        if gate.arabic_digits_remaining:
            kinds.append("Arabic digits 0-9")
        raise TtsInputError(
            "Thai-only gate ไม่ผ่าน: final spoken text ยังมี " + ", ".join(kinds)
            + f"\nข้อความที่ต้องแก้: {prepared['spoken']}"
            + "\nกรุณาเพิ่ม normalization rule หรือ pronunciation dictionary ก่อน inference; ระบบจะไม่ลบอักขระทิ้งเอง"
        )


def cache_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return round(handle.getnframes() / handle.getframerate(), 3)


def load_report() -> dict[str, Any]:
    if not REPORT_PATH.exists():
        return {"runs": []}
    try:
        return load_json(REPORT_PATH)
    except json.JSONDecodeError:
        return {"runs": [], "warnings": ["รายงานเดิมอ่านไม่ได้ จึงเริ่มรายการใหม่"]}


def show_prepared(prepared: dict[str, Any], voice: dict[str, Any], speed: float, steps: int) -> None:
    gate = prepared["gate"]
    print("Original text:", prepared["original"])
    print("Normalized text:", prepared["normalized"])
    print("Final spoken text:", prepared["spoken"])
    print("Pronunciation substitutions:", json.dumps(prepared["substitutions"], ensure_ascii=False))
    print("Thai-only gate:", "PASS" if gate.thai_only_gate_passed else "FAIL")
    print("Voice:", voice["alias"], "->", voice["voice_instruction"])
    print("Parameters:", json.dumps({"speed": speed, "steps": steps, "seed": voice.get("seed")}, ensure_ascii=False))


def list_voices(registry: dict[str, Any]) -> None:
    for alias, item in registry.get("aliases", {}).items():
        profile = profile_index(registry)[item["profile_key"]]
        print(f"{alias}: {item['description_th']} ({profile['voice_instruction']}; speed {profile['speed']})")


def main() -> int:
    configure_utf8_console()
    args = parse_args()
    engine = load_json(ENGINE_PATH)
    registry = load_json(REGISTRY_PATH)
    if args.list_voices:
        list_voices(registry)
        return 0
    source_text, source_type = read_source(args)
    if not source_text.strip():
        raise TtsInputError("ข้อความว่างเปล่า; กรุณาระบุข้อความภาษาไทย")
    prepared = prepare_text(source_text, ROOT / engine["normalization"]["pronunciation_dictionary_path"])
    voice = resolve_voice(args.voice, registry)
    speed = args.speed if args.speed is not None else float(voice["speed"])
    steps = args.steps if args.steps is not None else int(engine["default_steps"])
    if args.show_normalized or args.dry_run:
        show_prepared(prepared, voice, speed, steps)
    validate_gate(prepared)
    if args.dry_run:
        print("DRY RUN: pipeline ผ่าน; ไม่ได้โหลด model และไม่ได้สร้าง WAV")
        return 0
    assert args.output is not None
    warnings: list[str] = []
    if len(prepared["spoken"]) > MAX_RECOMMENDED_CHARACTERS:
        warnings.append(f"ข้อความยาว {len(prepared['spoken'])} ตัวอักษร เกินคำแนะนำ {MAX_RECOMMENDED_CHARACTERS}; POC นี้ยังไม่มี segmentation")
    payload = {"text": prepared["spoken"], "model": engine["model"], "revision": engine["revision"], "voice_instruction": voice["voice_instruction"], "speed": speed, "steps": steps, "sample_rate": engine["sample_rate"], "audio_normalization": AUDIO_NORMALIZATION}
    if voice["seed"] is not None:
        payload["seed"] = voice["seed"]
    key = cache_key(payload)
    report = load_report()
    output_text = str(args.output)
    cached = next((run for run in report.get("runs", []) if run.get("cache_key") == key and run.get("output") == output_text), None)
    if args.output.exists() and cached and not args.force:
        cached_audio, _cached_rate = sf.read(args.output, dtype="float32")
        validate_audible_audio(cached_audio)
        cached["cache_status"] = "hit"
        cached["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"CACHE HIT: {args.output}")
        return 0
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        warnings.append("ไม่พบ CUDA GPU; สร้างเสียงด้วย CPU ซึ่งใช้เวลานานกว่า")
    # Import lazily so --list-voices and --dry-run can never load the model runtime.
    from omnivoice import OmniVoice
    if voice["seed"] is not None:
        from omnivoice.utils.common import fix_random_seed
        fix_random_seed(voice["seed"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model = OmniVoice.from_pretrained(engine["model"], revision=engine["revision"], device_map=device, dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    audio = np.asarray(model.generate(prepared["spoken"], instruct=voice["voice_instruction"], speed=speed, num_step=steps)[0], dtype=np.float32)
    peak = validate_audible_audio(audio)["peak"]
    audio *= (10 ** (-1 / 20)) / peak
    sf.write(args.output, audio, engine["sample_rate"], subtype="PCM_16")
    elapsed = round(time.perf_counter() - started, 3)
    entry = {"cache_key": key, "created_at": datetime.now(timezone.utc).isoformat(), "source_type": source_type, "original_text": source_text, "normalized_text": prepared["normalized"], "final_spoken_text": prepared["spoken"], "normalization_transformations": prepared["normalization"], "pronunciation_substitutions": prepared["substitutions"], "thai_only_gate": {"passed": True, "latin_remaining": False, "arabic_digits_remaining": False}, "voice_alias": voice["alias"], "resolved_voice_instruction": voice["voice_instruction"], "speed": speed, "steps": steps, "seed": voice["seed"], "model": engine["model"], "revision": engine["revision"], "sample_rate": engine["sample_rate"], "audio_normalization": AUDIO_NORMALIZATION, "output": output_text, "duration_seconds": wav_duration(args.output), "generation_seconds": elapsed, "device": device, "torch": torch.__version__, "cuda_version": torch.version.cuda, "platform": platform.platform(), "cache_status": "generated", "warnings": warnings, "errors": []}
    report["runs"] = [run for run in report.get("runs", []) if not (run.get("cache_key") == key and run.get("output") == output_text)] + [entry]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": output_text, "duration_seconds": entry["duration_seconds"], "generation_seconds": elapsed, "device": device, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TtsInputError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

"""Mission 15 listening pack; optional seeds are POC-only and never UI defaults."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from long_text_batch import merge
from studio_engine_adapter import StudioEngineAdapter
import tts


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "voice_continuity_poc"
REPORT_PATH = OUTPUT_DIR / "report.json"
CONTINUITY_TEXTS = (
    "คืนนี้ลมพัดผ่านหน้าต่างเบา ๆ ",
    "ฉันวางหนังสือลง แล้วฟังความเงียบอยู่ครู่หนึ่ง ",
    "ก่อนจะค่อย ๆ เดินกลับไปที่ห้องเดิม",
)
CONTINUITY_PAUSES_MS = (320, 320, 320)
SEEDS = {"narrator": 15015, "bright_female": 15016, "young_female": 15017}
LIGHTER_VOICES = ("bright_female", "young_female", "cute_teen_soft")


def synthesize(adapter, registry: dict, text: str, alias: str, output: Path, seed: int | None) -> dict:
    voice = tts.resolve_voice(alias, registry)
    return adapter.generate(text, alias, float(voice["speed"]), 32, output, force=False, seed=seed)


def result_record(label: str, index: int, text: str, alias: str, speed: float, seed: int | None,
                  pause_after_ms: int, output: Path, result: dict) -> dict:
    return {
        "set": label, "index": index, "text": text, "voice": alias, "speed": speed, "seed": seed,
        "pause_after_ms": pause_after_ms, "output": str(output.relative_to(ROOT)),
        "cache_hit": result["cache_hit"], "model_load_seconds": result["model_load_seconds"],
        "inference_seconds": result["inference_seconds"],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    registry = tts.load_json(ROOT / "approved_voice_profiles.json")
    for alias in ("narrator", *LIGHTER_VOICES):
        tts.resolve_voice(alias, registry)
    adapter = StudioEngineAdapter()
    records: list[dict] = []
    started = time.perf_counter()

    continuity_paths: dict[str, list[Path]] = {"current": [], "candidate": []}
    narrator_speed = float(tts.resolve_voice("narrator", registry)["speed"])
    for set_name, seed in (("current", None), ("candidate", SEEDS["narrator"])):
        for index, text in enumerate(CONTINUITY_TEXTS, 1):
            output = OUTPUT_DIR / f"continuity_{set_name}_{index:02}.wav"
            result = synthesize(adapter, registry, text, "narrator", output, seed)
            continuity_paths[set_name].append(output)
            records.append(result_record(set_name, index, text, "narrator", narrator_speed, seed,
                                         CONTINUITY_PAUSES_MS[index - 1], output, result))

    continuity_current = OUTPUT_DIR / "continuity_current.wav"
    continuity_candidate = OUTPUT_DIR / "continuity_candidate.wav"
    current_duration = merge(continuity_paths["current"], continuity_current,
                             pause_after_ms=list(CONTINUITY_PAUSES_MS))
    candidate_duration = merge(continuity_paths["candidate"], continuity_candidate,
                               pause_after_ms=list(CONTINUITY_PAUSES_MS))

    lighter_outputs: dict[str, dict] = {}
    for alias in LIGHTER_VOICES:
        voice = tts.resolve_voice(alias, registry)
        paths: list[Path] = []
        for index, text in enumerate(CONTINUITY_TEXTS[:2], 1):
            output = OUTPUT_DIR / f"lighter_{alias}_{index:02}.wav"
            result = synthesize(adapter, registry, text, alias, output, seed=SEEDS.get(alias))
            paths.append(output)
            records.append(result_record(f"lighter_{alias}", index, text, alias, float(voice["speed"]),
                                         SEEDS.get(alias), CONTINUITY_PAUSES_MS[index - 1], output, result))
        preview = OUTPUT_DIR / f"lighter_{alias}.wav"
        duration = merge(paths, preview, pause_after_ms=list(CONTINUITY_PAUSES_MS[:2]))
        lighter_outputs[alias] = {"preview": str(preview.relative_to(ROOT)), "duration_seconds": round(duration, 3)}

    total_inference = sum(row["inference_seconds"] for row in records)
    report = {
        "mission": "MISSION 15 — VOICE CONTINUITY & LIGHTER NARRATION POC",
        "model": adapter.engine["model"], "revision": adapter.engine["revision"], "steps": 32,
        "randomness": {"source": "OmniVoice iterative Gumbel sampling uses torch.rand", "seed_api": "no direct generate(seed=...) parameter", "poc_control": "omnivoice.utils.common.fix_random_seed called inside PersistentTtsSession lock"},
        "speaker_identity": {"fixed_speaker_without_reference_audio": False, "voice_design": "descriptive instruct tags only", "reference_audio_used": False},
        "seeds": SEEDS, "continuity_texts": list(CONTINUITY_TEXTS), "continuity_pause_after_ms": list(CONTINUITY_PAUSES_MS),
        "records": records, "model_load_count": adapter.session.model_load_count, "device": adapter.session.device,
        "total_inference_seconds": round(total_inference, 3), "total_wall_seconds": round(time.perf_counter() - started, 3),
        "cache_hits": sum(1 for row in records if row["cache_hit"]), "cache_misses": sum(1 for row in records if not row["cache_hit"]),
        "continuity_current": str(continuity_current.relative_to(ROOT)), "continuity_current_duration_seconds": round(current_duration, 3),
        "continuity_candidate": str(continuity_candidate.relative_to(ROOT)), "continuity_candidate_duration_seconds": round(candidate_duration, 3),
        "lighter_outputs": lighter_outputs, "trailing_silence_added": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

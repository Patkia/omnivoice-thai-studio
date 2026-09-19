"""Generate four descriptive Thai character-style candidates with one session."""
from __future__ import annotations

import json
import math
import sys
import time
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
import tts
from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "botw_voice_reference"
CONFIG = ROOT / "botw_style_voice_candidates.json"
TEXTS = {
    "mipha": "ไม่ต้องกังวลนะ ฉันจะอยู่ตรงนี้กับเธอเอง",
    "great_deku_tree": "เวลาผ่านไปเนิ่นนาน แต่ความทรงจำยังคงอยู่"
}


def meta(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        result = {"sample_rate": handle.getframerate(), "channels": handle.getnchannels(),
                  "sample_width": handle.getsampwidth(), "duration_seconds": round(handle.getnframes() / handle.getframerate(), 3)}
    audio, _ = sf.read(path, dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(audio)))
    return {**result, "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 3),
            "clipping_detected": bool(peak >= 1.0)}


def historic_generation(output: Path) -> dict:
    entry = next((row for row in tts.load_report().get("runs", []) if row.get("output") == str(output)), {})
    return {"model_load_seconds": entry.get("model_load_seconds"), "inference_seconds": entry.get("inference_seconds"),
            "generation_seconds": entry.get("generation_seconds")}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))["candidates"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    records, started = [], time.perf_counter()
    for key, candidate in config.items():
        character = "mipha" if key.startswith("mipha_") else "great_deku_tree"
        suffix = key.rsplit("_", 1)[-1]
        output = OUTPUT / f"{character}_candidate_{suffix}.wav"
        result = adapter.generate(TEXTS[character], "narrator", candidate["speed"], 32, output,
                                  force=False, seed=candidate["seed"], instruct_override=candidate["instruct"])
        records.append({"candidate": key, "text": TEXTS[character], "instruct": candidate["instruct"],
                        "speed": candidate["speed"], "seed": candidate["seed"], "output": str(output.relative_to(ROOT)),
                        "cache_hit": result["cache_hit"], "model_load_seconds": result["model_load_seconds"],
                        "inference_seconds": result["inference_seconds"], "historic_generation": historic_generation(output),
                        "wav": meta(output)})
    report = {"mission": "MISSION 19 — BOTW THAI AI VOICE STYLE REFERENCE POC",
              "model": adapter.engine["model"], "revision": adapter.engine["revision"], "steps": 32,
              "reference_audio_used_as_model_input": False, "speaker_embedding_used": False, "voice_cloning_used": False,
              "persistent_session": True, "model_load_count": adapter.session.model_load_count, "device": adapter.session.device,
              "records": records, "total_inference_seconds": round(sum(row["inference_seconds"] for row in records), 3),
              "total_initial_inference_seconds": round(sum(row["historic_generation"]["inference_seconds"] or 0 for row in records), 3),
              "total_wall_seconds": round(time.perf_counter() - started, 3),
              "cache_hits": sum(row["cache_hit"] for row in records), "cache_misses": sum(not row["cache_hit"] for row in records),
              "warnings": ["Human listening is required; no candidate winner is selected."]}
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Mission 21: generate exactly three focused candidates, then process Deku raw locally."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from character_voice_polish import render_subtle_resonance, wav_metadata
from run_botw_style_voice_poc import OUTPUT, ROOT, TEXTS, historic_generation
from studio_engine_adapter import StudioEngineAdapter

CONFIG = ROOT / "botw_style_voice_candidates.json"
REPORT_PATH = OUTPUT / "report.json"
JOBS = (
    ("great_deku_tree_polished_raw", "great_deku_tree", "great_deku_tree_polished_raw.wav"),
    ("mipha_style_C", "mipha", "mipha_candidate_C.wav"),
    ("mipha_style_D", "mipha", "mipha_candidate_D.wav"),
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))["mission_21"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    started, records = time.perf_counter(), []
    for key, character, filename in JOBS:
        candidate, output = config[key], OUTPUT / filename
        result = adapter.generate(TEXTS[character], "narrator", candidate["speed"], 32, output,
                                  force=False, seed=candidate["seed"], instruct_override=candidate["instruct"])
        records.append({
            "candidate": key, "text": TEXTS[character], "instruct": candidate["instruct"],
            "speed": candidate["speed"], "seed": candidate["seed"], "output": str(output.relative_to(ROOT)),
            "cache_hit": result["cache_hit"], "model_load_seconds": result.get("model_load_seconds", 0.0),
            "inference_seconds": result.get("inference_seconds", 0.0),
            "historic_generation": historic_generation(output), "wav": wav_metadata(output),
        })
    resonant = render_subtle_resonance(OUTPUT / "great_deku_tree_polished_raw.wav",
                                        OUTPUT / "great_deku_tree_polished_resonant.wav")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    report.update({
        "mission_21": "FINAL CHARACTER VOICE POLISH", "model": adapter.engine["model"],
        "revision": adapter.engine["revision"], "steps": 32, "persistent_session": True,
        "device": adapter.session.device, "model_load_count": adapter.session.model_load_count,
        "reference_audio_used_as_model_input": False, "speaker_embedding_used": False, "voice_cloning_used": False,
        "mission_21_records": records, "mission_21_resonant_processing": resonant,
        "mission_21_total_inference_seconds": round(sum(row["inference_seconds"] for row in records), 3),
        "mission_21_total_initial_inference_seconds": round(sum(row["historic_generation"]["inference_seconds"] or 0 for row in records), 3),
        "mission_21_total_wall_seconds": round(time.perf_counter() - started, 3),
        "mission_21_cache_hits": sum(row["cache_hit"] for row in records),
        "mission_21_cache_misses": sum(not row["cache_hit"] for row in records),
        "warnings": ["Human listening is required; no candidate winner is selected."],
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": records, "resonant": resonant, "model_load_count": adapter.session.model_load_count}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

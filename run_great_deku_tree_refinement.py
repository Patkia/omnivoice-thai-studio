"""Generate only Mission 20 Great Deku Tree descriptive candidates C--E."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from run_botw_style_voice_poc import OUTPUT, ROOT, TEXTS, historic_generation, meta
from studio_engine_adapter import StudioEngineAdapter

CONFIG = ROOT / "botw_style_voice_candidates.json"
REPORT_PATH = OUTPUT / "report.json"
KEYS = ("great_deku_tree_style_C", "great_deku_tree_style_D", "great_deku_tree_style_E")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    candidates = config["candidates"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    started, records = time.perf_counter(), []
    for key in KEYS:
        candidate = candidates[key]
        suffix = key.rsplit("_", 1)[-1]
        output = OUTPUT / f"great_deku_tree_candidate_{suffix}.wav"
        result = adapter.generate(
            TEXTS["great_deku_tree"], "narrator", candidate["speed"], 32, output,
            force=False, seed=candidate["seed"], instruct_override=candidate["instruct"],
        )
        records.append({
            "candidate": key, "text": TEXTS["great_deku_tree"], "instruct": candidate["instruct"],
            "speed": candidate["speed"], "seed": candidate["seed"],
            "output": str(output.relative_to(ROOT)), "cache_hit": result["cache_hit"],
            "model_load_seconds": result.get("model_load_seconds", 0.0),
            "inference_seconds": result.get("inference_seconds", 0.0),
            "historic_generation": historic_generation(output), "wav": meta(output),
        })
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    previous = [row for row in report.get("records", []) if row.get("candidate") not in KEYS]
    report.update({
        "mission_20": "GREAT DEKU TREE VOICE REFINEMENT",
        "model": adapter.engine["model"], "revision": adapter.engine["revision"], "steps": 32,
        "reference_audio_used_as_model_input": False, "speaker_embedding_used": False,
        "voice_cloning_used": False, "persistent_session": True,
        "device": adapter.session.device, "model_load_count": adapter.session.model_load_count,
        "records": previous + records,
        "mission_20_records": records,
        "mission_20_total_inference_seconds": round(sum(row["inference_seconds"] for row in records), 3),
        "mission_20_total_wall_seconds": round(time.perf_counter() - started, 3),
        "mission_20_cache_hits": sum(row["cache_hit"] for row in records),
        "mission_20_cache_misses": sum(not row["cache_hit"] for row in records),
        "warnings": ["Human listening is required; no Great Deku Tree candidate winner is selected."],
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mission_20_records": records, "model_load_count": adapter.session.model_load_count}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

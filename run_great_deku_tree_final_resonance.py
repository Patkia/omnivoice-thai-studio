"""Mission 22: one slower TTS render and two deterministic DSP alternatives."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from character_voice_polish import render_resonance_variant, wav_metadata
from run_botw_style_voice_poc import OUTPUT, ROOT, TEXTS, historic_generation
from studio_engine_adapter import StudioEngineAdapter

CONFIG = ROOT / "botw_style_voice_candidates.json"
REPORT_PATH = OUTPUT / "report.json"
VARIANTS = {
    "A": {"body_mix": 0.20, "pre_delay_ms": 22.0, "decay_ms": 400.0, "wet": 0.20},
    "B": {"body_mix": 0.25, "pre_delay_ms": 30.0, "decay_ms": 640.0, "wet": 0.28},
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    base = json.loads(CONFIG.read_text(encoding="utf-8"))["mission_21"]["great_deku_tree_polished_raw"]
    candidate = {**base, "speed": 0.68}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    adapter, started = StudioEngineAdapter(), time.perf_counter()
    raw_path = OUTPUT / "great_deku_tree_final_raw.wav"
    result = adapter.generate(TEXTS["great_deku_tree"], "narrator", candidate["speed"], 32, raw_path,
                              force=False, seed=candidate["seed"], instruct_override=candidate["instruct"])
    raw = {
        "candidate": "great_deku_tree_final_raw", "text": TEXTS["great_deku_tree"],
        "instruct": candidate["instruct"], "speed": candidate["speed"], "seed": candidate["seed"],
        "output": str(raw_path.relative_to(ROOT)), "cache_hit": result["cache_hit"],
        "model_load_seconds": result.get("model_load_seconds", 0.0), "inference_seconds": result.get("inference_seconds", 0.0),
        "historic_generation": historic_generation(raw_path), "wav": wav_metadata(raw_path),
    }
    resonance = {name: render_resonance_variant(raw_path, OUTPUT / f"great_deku_tree_resonance_{name}.wav", **settings)
                 for name, settings in VARIANTS.items()}
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    report.update({
        "mission_22": "GREAT DEKU TREE FINAL RESONANCE & PACE", "model": adapter.engine["model"],
        "revision": adapter.engine["revision"], "steps": 32, "persistent_session": True,
        "device": adapter.session.device, "model_load_count": adapter.session.model_load_count,
        "reference_audio_used_as_model_input": False, "speaker_embedding_used": False, "voice_cloning_used": False,
        "mission_22_raw": raw, "mission_22_resonance": resonance,
        "mission_22_total_inference_seconds": raw["inference_seconds"],
        "mission_22_total_initial_inference_seconds": raw["historic_generation"]["inference_seconds"],
        "mission_22_total_wall_seconds": round(time.perf_counter() - started, 3),
        "mission_22_cache_hits": int(raw["cache_hit"]), "mission_22_cache_misses": int(not raw["cache_hit"]),
        "warnings": ["Human listening is required; no resonance candidate winner is selected."],
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"raw": raw, "resonance": resonance, "model_load_count": adapter.session.model_load_count}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

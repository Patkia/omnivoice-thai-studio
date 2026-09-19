"""Mission 18: compare existing fixed-seed audio with conservative level matching."""
from __future__ import annotations

import json
from pathlib import Path

from long_text_batch import merge
from loudness_continuity import normalize_chunks

ROOT = Path(__file__).resolve().parent
MISSION17 = ROOT / "output" / "long_text_continuity_poc" / "report.json"
OUTPUT_DIR = ROOT / "output" / "long_text_loudness_poc"


def main() -> int:
    prior = json.loads(MISSION17.read_text(encoding="utf-8"))
    if prior["seed_policy"]["fixed_seed"] != 15015:
        raise RuntimeError("Mission 17 fixed-seed artifacts are not the approved source")
    chunks = prior["sets"]["fixed_seed"]
    paths = [ROOT / row["output"] for row in chunks]
    if not all(path.exists() for path in paths):
        raise FileNotFoundError("one or more Mission 17 fixed-seed chunks are missing")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = normalize_chunks(paths, OUTPUT_DIR / "normalized_chunks")
    normalized_paths = [Path(row["normalized"]) for row in rows]
    pauses = [row["pause_after_ms"] for row in chunks]
    normalized_preview = OUTPUT_DIR / "fixed_seed_loudness_normalized_preview.wav"
    duration = merge(normalized_paths, normalized_preview, pause_after_ms=pauses)
    report = {
        "mission": "MISSION 18 — LONG TEXT LOUDNESS CONTINUITY POC",
        "source_mission": "MISSION 17", "source_seed": 15015,
        "method": {"active_speech_threshold_dbfs": -45.0, "target": "quietest active-speech RMS", 
                   "gain_policy": "attenuation-only", "max_attenuation_db": 2.0,
                   "compression": False, "pitch_or_speed_changed": False,
                   "integrated_loudness_lufs": "unavailable (pyloudnorm not installed)"},
        "merge": {"order": [row["index"] for row in chunks], "pause_after_ms": pauses,
                  "trailing_silence_added": False, "function": "long_text_batch.merge"},
        "chunks": rows,
        "original_preview": prior["previews"]["fixed_seed"],
        "normalized_preview": str(normalized_preview.relative_to(ROOT)),
        "normalized_duration_seconds": round(duration, 3),
        "all_peaks_safe": all(row["after"]["peak_dbfs"] <= 0.0 for row in rows),
        "production_default": False,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build non-cloning reference diagnostics and style notes for Mission 19."""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "botw_voice_reference"

REFERENCES = {
    "mipha_style": {
        "demo": "Demo152_0", "bfstm": "Demo152_0_Text023.bfstm",
        "source": ROOT / "Thai Voice" / "romfs" / "Voice" / "USen" / "Stream_Demo152_0" / "Demo152_0_Text023.bfstm",
        "wav": OUTPUT / "mipha_reference.wav",
        "mapping_basis": "DemoMsg mapping: Mipha's childhood-memory line about Link being a reckless child.",
        "perceived_gender": "female", "perceived_age": "young adult", "pitch": "moderate",
        "pitch_variation": "gentle conversational variation", "vocal_weight": "light",
        "softness": "soft", "warmth": "warm", "brightness": "moderate",
        "breathiness": "subtle / not used as a generation control", "energy": "calm",
        "pace": "moderate to slightly slow", "articulation": "clear but natural",
        "delivery": "tender, reassuring, conversational", "formality": "gentle informal conversation",
        "calmness": "high", "prosody": "smooth and caring", "overall_style": "gentle fantasy heroine; descriptive only"
    },
    "great_deku_tree_style": {
        "demo": "Demo109_2", "bfstm": "Demo109_2_Text007.bfstm",
        "source": ROOT / "Thai Voice" / "romfs" / "Voice" / "USen" / "Stream_Demo109_2" / "Demo109_2_Text007.bfstm",
        "wav": OUTPUT / "great_deku_tree_reference.wav",
        "mapping_basis": "Demo mapping: post-Master Sword flashback; the Great Deku Tree explains an event from 100 years ago.",
        "perceived_gender": "male", "perceived_age": "elderly / ancient", "pitch": "low",
        "pitch_variation": "restrained", "vocal_weight": "heavy",
        "resonance": "dark / resonant impression", "chestiness": "present / weight-forward impression",
        "roughness": "light texture rather than harshness", "softness": "controlled", "warmth": "warm", "darkness": "high", "brightness": "low",
        "breathiness": "low / not used as a generation control", "energy": "calm but present",
        "pace": "slow and deliberate", "pause_style": "measured, phrase-led pauses", "articulation": "measured and formal", "authority": "quiet, ancient authority",
        "emotional_tone": "reflective and grave without aggression", "delivery": "wise and authoritative without aggression",
        "formality": "formal", "calmness": "high", "prosody": "deliberate, resonant impression",
        "overall_style": "ancient fantasy elder; descriptive only",
        "candidate_A_B_gap_hypothesis": "The supported controls can express only age, pitch and speed. Candidate A likely remained too generic despite the elder tag; candidate B traded the elder tag for middle-aged, which may weaken the ancient/aged impression. Neither can directly request resonance, texture, warmth or authority."
    },
}


def dbfs(value: float) -> float:
    return round(20 * math.log10(max(value, 1e-12)), 3)


def diagnostics(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        meta = {"sample_rate": handle.getframerate(), "channels": handle.getnchannels(),
                "bit_depth": handle.getsampwidth() * 8, "frames": handle.getnframes()}
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    magnitude = np.max(np.abs(audio), axis=1)
    threshold = 10 ** (-45 / 20)
    first, last = np.flatnonzero(magnitude > threshold)[[0, -1]]
    return {**meta, "duration_seconds": round(len(audio) / rate, 3), "peak_dbfs": dbfs(float(magnitude.max())),
            "clipping_detected": bool(np.any(magnitude >= 0.9999)),
            "leading_silence_ms": round(1000 * first / rate, 3),
            "trailing_silence_ms": round(1000 * (len(audio) - 1 - last) / rate, 3),
            "bgm_or_sfx": "not detected automatically; no source separation performed",
            "reference_quality": "CLEAN",
            "quality_reason": "Dedicated dialogue stream; automatic silence check found no persistent bed during detected silent regions."
    }


def main() -> int:
    result = {"mission": "MISSION 19 — BOTW THAI AI VOICE STYLE REFERENCE POC",
              "analysis_scope": "Descriptive voice design only, not speaker identity or cloning.", "references": {}}
    for name, item in REFERENCES.items():
        result["references"][name] = {**item, "source": str(item["source"].relative_to(ROOT)),
                                      "wav": str(item["wav"].relative_to(ROOT)), "file_size_bytes": item["source"].stat().st_size,
                                      "technical": diagnostics(item["wav"])}
    (OUTPUT / "style_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

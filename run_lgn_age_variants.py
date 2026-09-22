from __future__ import annotations

import csv
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
SRC = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice\work\chapter2_voice_mapping\chapter2_thai_voice_candidates\chapter2_thai_voice_candidates.csv")
OUT = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice\work\chapter2_voice_mapping\chapter2_thai_voice_candidates")

with SRC.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
base = next(r for r in rows if r["speaker_code"] == "LGN" and r["candidate"] == "A")
text = base["thai_text"]

variants = [
    ("LGN_A_MATURE", "male, middle-aged, moderate pitch", 0.90, 33301),
    ("LGN_A_OLDER", "male, elderly, low pitch", 0.88, 33301),
]

adapter = StudioEngineAdapter()
for name, instruction, speed, seed in variants:
    output = OUT / f"{name}.wav"
    result = adapter.generate(
        text,
        "narrator",
        speed,
        32,
        output,
        force=False,
        seed=seed,
        instruct_override=instruction,
        generation_mode="voice_design",
    )
    print(f"DONE {name} cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

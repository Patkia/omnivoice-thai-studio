from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
APPROVED = TRIANGLE / "work/chapter2_voice_mapping/chapter2_voice_references/chapter2_human_approved_references.csv"
OUT = TRIANGLE / "work/chapter2_voice_mapping/chapter2_thai_voice_candidates"
REF = ROOT / "assets/triangle-strategy/approved_voice_references/candidates/lgn_ch2/lgn_english_approved_24k.wav"
META = ROOT / "assets/triangle-strategy/approved_voice_references/candidates/lgn_ch2/lgn_english_approved_24k.json"

with APPROVED.open("r", encoding="utf-8-sig", newline="") as f:
    row = next(r for r in csv.DictReader(f) if r["speaker_code"] == "LGN")
meta = json.loads(META.read_text(encoding="utf-8"))
reference_text = meta["reference_text"]
reference_sha = meta["runtime_reference_sha256"]
text_sha = meta["reference_text_sha256"]
thai_text = row["thai_text"].strip()
if hashlib.sha256(REF.read_bytes()).hexdigest() != reference_sha:
    raise RuntimeError("LGN runtime reference SHA mismatch")

output = OUT / "LGN_EN_CLONE_VERY_OLD.wav"
adapter = StudioEngineAdapter()
result = adapter.generate(
    thai_text,
    "narrator",
    0.80,
    32,
    output,
    force=False,
    seed=33312,
    generation_mode="reference_first",
    reference_conditioning=True,
    reference_audio=str(REF.relative_to(ROOT)),
    reference_sha256=reference_sha,
    reference_text=reference_text,
    reference_text_sha256=text_sha,
    language="Thai",
    denoise=True,
    postprocess_output=True,
    voice_project="triangle-strategy",
)
print(f"DONE cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

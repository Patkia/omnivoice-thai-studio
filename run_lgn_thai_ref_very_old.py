from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
OUT = TRIANGLE / "work/chapter2_voice_mapping/chapter2_thai_voice_candidates"
MANIFEST = OUT / "chapter2_thai_voice_candidates.csv"
RUNTIME_REF = ROOT / "assets/triangle-strategy/approved_voice_references/runtime_lgn/LGN_A_OLDER_thai.wav"

with MANIFEST.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
base = next(r for r in rows if r["speaker_code"] == "LGN" and r["candidate"] == "A")
text = base["thai_text"]

if not RUNTIME_REF.is_file():
    raise FileNotFoundError(RUNTIME_REF)

ref_sha = hashlib.sha256(RUNTIME_REF.read_bytes()).hexdigest()
text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
output = OUT / "LGN_THAI_REF_VERY_OLD.wav"

adapter = StudioEngineAdapter()
result = adapter.generate(
    text,
    "narrator",
    0.78,
    32,
    output,
    force=False,
    seed=33324,
    generation_mode="reference_first",
    language="Thai",
    denoise=True,
    postprocess_output=True,
    voice_project="triangle-strategy",
    reference_conditioning=True,
    reference_audio=str(RUNTIME_REF.relative_to(ROOT)),
    reference_sha256=ref_sha,
    reference_text=text,
    reference_text_sha256=text_sha,
)
print(f"DONE cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

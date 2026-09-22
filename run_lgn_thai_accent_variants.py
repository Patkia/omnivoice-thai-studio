from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
OUT = TRIANGLE / "work/chapter2_voice_mapping/chapter2_thai_voice_candidates"
MANIFEST = OUT / "chapter2_thai_voice_candidates.csv"
REF_DIR = ROOT / "assets" / "triangle-strategy" / "approved_voice_references" / "runtime_lgn"

with MANIFEST.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
base = next(r for r in rows if r["speaker_code"] == "LGN" and r["candidate"] == "A")
text = base["thai_text"]

adapter = StudioEngineAdapter()
OUT.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)

# 1) Pure Thai voice-design path: keeps Thai articulation and pushes age/body further.
voice_design_variants = [
    ("LGN_THAI_OLD", "male, elderly, low pitch", 0.84, 33321),
    ("LGN_THAI_VERY_OLD", "male, elderly, very low pitch", 0.80, 33322),
]
for name, instruction, speed, seed in voice_design_variants:
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

# 2) Thai-reference clone path: use the already Thai LGN_A_OLDER as identity/prosody anchor,
# so the clone prompt itself contains Thai pronunciation instead of English accent.
source_ref = OUT / "LGN_A_OLDER.wav"
if not source_ref.is_file():
    raise FileNotFoundError(source_ref)

# OmniVoice reference files must be inside workspace; copy bytes unchanged (already 24k mono PCM16 output).
runtime_ref = REF_DIR / "LGN_A_OLDER_thai.wav"
runtime_ref.write_bytes(source_ref.read_bytes())
ref_sha = hashlib.sha256(runtime_ref.read_bytes()).hexdigest()
text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

for name, speed, seed in [
    ("LGN_THAI_REF_OLD", 0.84, 33323),
    ("LGN_THAI_REF_VERY_OLD", 0.78, 33324),
]:
    output = OUT / f"{name}.wav"
    result = adapter.generate(
        text,
        "narrator",
        speed,
        32,
        output,
        force=False,
        seed=seed,
        generation_mode="reference_first",
        language="Thai",
        denoise=True,
        postprocess_output=True,
        voice_project="triangle-strategy",
        reference_conditioning=True,
        reference_audio=str(runtime_ref.relative_to(ROOT)),
        reference_sha256=ref_sha,
        reference_text=text,
        reference_text_sha256=text_sha,
    )
    print(f"DONE {name} cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

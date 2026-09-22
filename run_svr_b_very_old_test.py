from __future__ import annotations

import csv
import hashlib
import wave
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
MANIFEST = TRIANGLE / "work/extended_voice_candidates/thai_candidates/extended_voice_candidates.csv"
OUT = TRIANGLE / "work/extended_voice_candidates/age_tests"
OUT_WAV = OUT / "SVR_B_VERY_OLD.wav"

with MANIFEST.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
row = next(r for r in rows if r["user_code"] == "SVR" and r["candidate"] == "B")

text = row["thai_text"]
old_instruction = row["instruction"]
new_instruction = "male, elderly, very low pitch"
speed = 0.84
seed = int(row["seed"]) + 1
steps = 12

OUT.mkdir(parents=True, exist_ok=True)
adapter = StudioEngineAdapter()
result = adapter.generate(
    text,
    "narrator",
    speed,
    steps,
    OUT_WAV,
    force=True,
    seed=seed,
    instruct_override=new_instruction,
    generation_mode="voice_design",
)

sha = hashlib.sha256(OUT_WAV.read_bytes()).hexdigest()
with wave.open(str(OUT_WAV), "rb") as w:
    duration = w.getnframes() / w.getframerate()

print("SOURCE=SVR_B.wav")
print(f"OLD_INSTRUCTION={old_instruction}")
print(f"NEW_INSTRUCTION={new_instruction}")
print(f"SPEED={speed:.2f}")
print(f"SEED={seed}")
print(f"STEPS={steps}")
print(f"OUTPUT={OUT_WAV}")
print(f"SHA256={sha}")
print(f"DURATION_SEC={duration:.3f}")
print(f"CACHE_HIT={bool(result.get('cache_hit'))}")
print(f"INFERENCE_SECONDS={float(result.get('inference_seconds', 0.0)):.3f}")

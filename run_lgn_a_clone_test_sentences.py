from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
SRC_DIR = TRIANGLE / "work/chapter2_voice_mapping/chapter2_thai_voice_candidates"
SRC_WAV = SRC_DIR / "LGN_A.wav"
MANIFEST = SRC_DIR / "chapter2_thai_voice_candidates.csv"
OUT = SRC_DIR / "LGN_A_clone_tests"
REF_DIR = ROOT / "assets/triangle-strategy/approved_voice_references/runtime_lgn_a_clone_test"
REF_WAV = REF_DIR / "LGN_A.wav"

TESTS = [
    "วันนี้อากาศสงบดีนะ ถ้าไม่มีเรื่องด่วน เราก็ค่อย ๆ คุยกันได้",
    "ข้าอยากให้ทุกคนคิดให้รอบคอบ ก่อนจะตัดสินใจเรื่องสำคัญเช่นนี้",
    "พรุ่งนี้เช้าเราจะออกเดินทางพร้อมกัน ขอให้ทุกคนเตรียมตัวให้พร้อม",
    "ไม่ต้องกังวลไป เรื่องนี้ยังพอมีทางแก้ ขอเพียงเราไม่รีบร้อนจนเกินไป",
    "เมื่อถึงเวลาที่เหมาะสม ข้าจะบอกทุกอย่างให้พวกเจ้าฟังด้วยตัวเอง",
]

with MANIFEST.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
base = next(r for r in rows if r["speaker_code"] == "LGN" and r["candidate"] == "A")
reference_text = base["thai_text"]

if not SRC_WAV.is_file():
    raise FileNotFoundError(SRC_WAV)

OUT.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)
REF_WAV.write_bytes(SRC_WAV.read_bytes())

ref_sha = hashlib.sha256(REF_WAV.read_bytes()).hexdigest()
ref_text_sha = hashlib.sha256(reference_text.encode("utf-8")).hexdigest()

adapter = StudioEngineAdapter()
for i, text in enumerate(TESTS, 1):
    output = OUT / f"LGN_A_CLONE_TEST_{i:02d}.wav"
    result = adapter.generate(
        text,
        "narrator",
        0.90,
        32,
        output,
        force=False,
        seed=33301,
        generation_mode="reference_first",
        language="Thai",
        denoise=True,
        postprocess_output=True,
        voice_project="triangle-strategy",
        reference_conditioning=True,
        reference_audio=str(REF_WAV.relative_to(ROOT)),
        reference_sha256=ref_sha,
        reference_text=reference_text,
        reference_text_sha256=ref_text_sha,
    )
    print(f"DONE {i:02d} cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

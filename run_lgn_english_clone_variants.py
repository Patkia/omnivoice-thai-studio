from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
APPROVED = TRIANGLE / "work/chapter2_voice_mapping/chapter2_voice_references/chapter2_human_approved_references.csv"
REF_ROOT = TRIANGLE / "work/chapter2_voice_mapping/chapter2_voice_references"
OUT = TRIANGLE / "work/chapter2_voice_mapping/chapter2_thai_voice_candidates"
RUNTIME_REF = ROOT / "assets/triangle-strategy/approved_voice_references/candidates/lgn_ch2/lgn_english_approved_24k.wav"
META = ROOT / "assets/triangle-strategy/approved_voice_references/candidates/lgn_ch2/lgn_english_approved_24k.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


rows = read_rows(APPROVED)
row = next(r for r in rows if r["speaker_code"] == "LGN")
source = REF_ROOT / row["candidate_wav"]
reference_text = row["english_text"].strip()
thai_text = row["thai_text"].strip()
if not source.is_file():
    raise FileNotFoundError(source)
if not reference_text or not thai_text:
    raise RuntimeError("LGN approved row is missing exact English/Thai text")

audio, sr = sf.read(source, dtype="float64", always_2d=False)
if audio.ndim != 1:
    raise RuntimeError(f"Expected mono source, got shape={audio.shape}")
if sr != 48000:
    raise RuntimeError(f"Expected 48k approved source, got {sr}")

# Runtime derivative only: resample 48k -> 24k with no gain/normalization/trim/denoise/EQ/compression/time-stretch.
runtime = resample_poly(audio, 1, 2)
peak = float(np.max(np.abs(runtime))) if runtime.size else 0.0
if not runtime.size or not np.isfinite(runtime).all() or peak <= 0:
    raise RuntimeError("Invalid runtime derivative")
if peak >= 1.0:
    raise RuntimeError(f"Runtime derivative would clip (peak={peak})")
RUNTIME_REF.parent.mkdir(parents=True, exist_ok=True)
sf.write(RUNTIME_REF, runtime, 24000, subtype="PCM_16")

info = sf.info(RUNTIME_REF)
if (info.samplerate, info.channels, info.subtype) != (24000, 1, "PCM_16"):
    raise RuntimeError(f"Bad runtime reference format: {info}")

ref_sha = sha256_file(RUNTIME_REF)
text_sha = sha256_bytes(reference_text.encode("utf-8"))
META.write_text(json.dumps({
    "source_master": str(source),
    "source_master_sha256": sha256_file(source),
    "runtime_reference": str(RUNTIME_REF),
    "runtime_reference_sha256": ref_sha,
    "reference_text": reference_text,
    "reference_text_sha256": text_sha,
    "sample_rate": info.samplerate,
    "channels": info.channels,
    "subtype": info.subtype,
    "processing": "48k->24k resample only; no normalization/gain/trim/denoise/EQ/compression/time-stretch",
}, ensure_ascii=False, indent=2), encoding="utf-8")

adapter = StudioEngineAdapter()
variants = [
    ("LGN_EN_CLONE_OLD", 0.88, 33311),
    ("LGN_EN_CLONE_VERY_OLD", 0.80, 33312),
]
OUT.mkdir(parents=True, exist_ok=True)
for name, speed, seed in variants:
    output = OUT / f"{name}.wav"
    result = adapter.generate(
        thai_text,
        "narrator",
        speed,
        32,
        output,
        force=False,
        seed=seed,
        generation_mode="reference_first",
        reference_conditioning=True,
        reference_audio=str(RUNTIME_REF.relative_to(ROOT)),
        reference_sha256=ref_sha,
        reference_text=reference_text,
        reference_text_sha256=text_sha,
        language="Thai",
        denoise=True,
        postprocess_output=True,
        voice_project="triangle-strategy",
    )
    print(f"DONE {name} cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

print(f"RUNTIME_REF={RUNTIME_REF}")
print(f"REFERENCE_SOURCE={source}")

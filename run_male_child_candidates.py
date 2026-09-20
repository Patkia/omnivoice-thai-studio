from __future__ import annotations

import hashlib
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from studio_engine_adapter import StudioEngineAdapter
from studio_generation import generate_studio_request

OUT_DIR = ROOT / "assets" / "triangle-strategy" / "approved_voice_references" / "candidates" / "male_child"
TEXT = "วันนี้อากาศดีจัง ข้าอยากออกไปดูข้างนอกสักหน่อย เผื่อจะมีอะไรน่าสนใจเกิดขึ้น"
STEPS = 32

CANDIDATES = [
    {"id": "MALE_CHILD_B_01", "instruction": "male, child, high pitch", "speed": 1.05, "seed": 27101, "hint": "bright/energetic"},
    {"id": "MALE_CHILD_B_02", "instruction": "male, child, very high pitch", "speed": 1.08, "seed": 27102, "hint": "brighter/more energetic"},
    {"id": "MALE_CHILD_B_03", "instruction": "male, child, moderate pitch", "speed": 1.04, "seed": 27103, "hint": "natural energetic"},
    {"id": "MALE_CHILD_C_01", "instruction": "male, child, moderate pitch", "speed": 0.95, "seed": 27201, "hint": "soft/calm"},
    {"id": "MALE_CHILD_C_02", "instruction": "male, child, high pitch", "speed": 0.96, "seed": 27202, "hint": "gentle youthful"},
    {"id": "MALE_CHILD_C_03", "instruction": "male, child, moderate pitch", "speed": 0.92, "seed": 27203, "hint": "quiet/shy"},
]


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav:
        return {
            "sample_rate": wav.getframerate(),
            "channels": wav.getnchannels(),
            "sample_width": wav.getsampwidth(),
            "duration_sec": round(wav.getnframes() / wav.getframerate(), 3),
        }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    manifest = []
    for item in CANDIDATES:
        out = OUT_DIR / f"{item['id']}.wav"
        if out.exists():
            print(f"SKIP {item['id']}")
        else:
            started = time.perf_counter()
            generate_studio_request(
                adapter,
                TEXT,
                "young_male",
                item["speed"],
                STEPS,
                out,
                True,
                seed=item["seed"],
                instruction_override=item["instruction"],
                reference_conditioning=False,
            )
            print(f"DONE {item['id']} {time.perf_counter() - started:.1f}s")
        info = wav_info(out)
        manifest.append({
            **item,
            "text": TEXT,
            "steps": STEPS,
            "file": out.name,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            **info,
        })
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"READY {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import time
import wave
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter
from studio_generation import generate_studio_request

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "assets" / "triangle-strategy" / "approved_voice_references" / "candidates" / "rough"
TEXT = "พวกเจ้าคิดว่าจะผ่านข้าไปได้ง่าย ๆ อย่างนั้นหรือ ถ้าอยากลองดีก็เข้ามา"
STEPS = 32

CASES = [
    {"id": "MALE_ROUGH_A_01", "instruction": "male, middle-aged, low pitch", "speed": 0.96, "seed": 28101, "hint": "adult low, firm"},
    {"id": "MALE_ROUGH_A_02", "instruction": "male, middle-aged, very low pitch", "speed": 0.94, "seed": 28102, "hint": "adult very low, heavier"},
    {"id": "MALE_ROUGH_A_03", "instruction": "male, elderly, low pitch", "speed": 0.95, "seed": 28103, "hint": "aged low, weathered"},
    {"id": "MALE_ROUGH_B_01", "instruction": "male, young adult, low pitch", "speed": 1.02, "seed": 28201, "hint": "younger rough/quick"},
    {"id": "MALE_ROUGH_B_02", "instruction": "male, middle-aged, low pitch", "speed": 1.03, "seed": 28202, "hint": "adult aggressive/quick"},
    {"id": "MALE_ROUGH_B_03", "instruction": "male, middle-aged, moderate pitch", "speed": 1.00, "seed": 28203, "hint": "natural coarse candidate"},
    {"id": "FEMALE_ROUGH_A_01", "instruction": "female, middle-aged, low pitch", "speed": 0.97, "seed": 28301, "hint": "adult low, stern"},
    {"id": "FEMALE_ROUGH_A_02", "instruction": "female, middle-aged, very low pitch", "speed": 0.95, "seed": 28302, "hint": "adult very low, heavy"},
    {"id": "FEMALE_ROUGH_A_03", "instruction": "female, elderly, low pitch", "speed": 0.96, "seed": 28303, "hint": "aged low, weathered"},
    {"id": "FEMALE_ROUGH_B_01", "instruction": "female, young adult, low pitch", "speed": 1.02, "seed": 28401, "hint": "younger low, assertive"},
    {"id": "FEMALE_ROUGH_B_02", "instruction": "female, middle-aged, low pitch", "speed": 1.03, "seed": 28402, "hint": "adult brisk, stern"},
    {"id": "FEMALE_ROUGH_B_03", "instruction": "female, middle-aged, moderate pitch", "speed": 1.00, "seed": 28403, "hint": "natural coarse candidate"},
]


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        return {
            "sample_rate": w.getframerate(),
            "channels": w.getnchannels(),
            "sample_width": w.getsampwidth(),
            "duration_sec": round(w.getnframes() / w.getframerate(), 3),
        }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    rows = []
    for case in CASES:
        out = OUT_DIR / f"{case['id']}.wav"
        if out.exists():
            print(f"SKIP {case['id']}")
        else:
            started = time.perf_counter()
            generate_studio_request(
                adapter,
                TEXT,
                "narrator",
                case["speed"],
                STEPS,
                out,
                True,
                seed=case["seed"],
                instruction_override=case["instruction"],
                reference_conditioning=False,
            )
            print(f"DONE {case['id']} {time.perf_counter()-started:.1f}s")
        row = {**case, "text": TEXT, "steps": STEPS, "file": out.name,
               "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), **wav_info(out)}
        rows.append(row)
    (OUT_DIR / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"READY {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

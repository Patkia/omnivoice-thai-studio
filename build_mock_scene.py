"""Concatenate validated Mission 6 line WAVs with 350 ms silence; no ffmpeg required."""

import json
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "output" / "final_validation" / "report.json"
OUTPUT = ROOT / "output" / "final_validation" / "mock_scene.wav"
SILENCE_SECONDS = 0.35


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    runs = sorted(report["runs"], key=lambda item: item["line_id"])
    if len(runs) != 10:
        raise RuntimeError(f"Expected 10 line WAVs, found {len(runs)}")
    chunks, sample_rate = [], None
    for entry in runs:
        audio, rate = sf.read(ROOT / entry["output"], dtype="float32")
        if sample_rate is None:
            sample_rate = rate
        if rate != sample_rate:
            raise RuntimeError("All scene WAVs must share the same sample rate")
        chunks.append(audio)
    silence = np.zeros(int(sample_rate * SILENCE_SECONDS), dtype=np.float32)
    joined = np.concatenate([part for index, chunk in enumerate(chunks) for part in (chunk, silence) if index < len(chunks) - 1 or part is chunk])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sf.write(OUTPUT, joined, sample_rate, subtype="PCM_16")
    report["mock_scene"] = {"output": "output/final_validation/mock_scene.wav", "line_count": len(runs), "silence_seconds": SILENCE_SECONDS, "sample_rate": sample_rate}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

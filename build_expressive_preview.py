"""Build a NOT HUMAN-APPROVED preview using the deterministic expr_02 preset."""

import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
BASE_REPORT = ROOT / "output" / "final_validation" / "report.json"
EXPR_REPORT = ROOT / "output" / "expressive_delivery" / "report.json"
OUT = ROOT / "output" / "expressive_delivery" / "mock_scene_expressive_preview.wav"


def main() -> int:
    base = {entry["line_id"]: entry for entry in json.loads(BASE_REPORT.read_text(encoding="utf-8"))["runs"]}
    expr_data = json.loads(EXPR_REPORT.read_text(encoding="utf-8"))
    expr = {entry["source_line_id"]: entry for entry in expr_data["runs"] if entry["candidate_id"].endswith("expr_02")}
    replacements = {"001", "002", "004", "007"}
    ordered = []
    for line_id in [f"{n:03d}" for n in range(1, 11)]:
        entry = expr[line_id] if line_id in replacements else base[line_id]
        ordered.append(ROOT / entry["output"])
    chunks, rate = [], None
    for path in ordered:
        audio, current_rate = sf.read(path, dtype="float32")
        if rate is None:
            rate = current_rate
        if current_rate != rate:
            raise RuntimeError("Sample-rate mismatch")
        chunks.append(audio)
    silence = np.zeros(int(rate * 0.35), dtype=np.float32)
    merged = np.concatenate([piece for i, audio in enumerate(chunks) for piece in ((audio, silence) if i < len(chunks) - 1 else (audio,))])
    sf.write(OUT, merged, rate, subtype="PCM_16")
    expr_data["expressive_preview"] = {"output":"output/expressive_delivery/mock_scene_expressive_preview.wav", "preset":"expr_02", "not_human_approved":True, "replaced_lines":["001","002","004","007"], "silence_seconds":0.35}
    EXPR_REPORT.write_text(json.dumps(expr_data,ensure_ascii=False,indent=2),encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

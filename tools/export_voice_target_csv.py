from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from csv_batch import batch_voice_project, read_csv, resolve_generation_config

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description="Export one voice_target from an OmniVoice Studio CSV")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--voice-target", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    src = args.input if args.input.is_absolute() else ROOT / args.input
    dst = args.output if args.output.is_absolute() else ROOT / args.output

    rows = read_csv(src)
    selected = [r for r in rows if r.metadata("voice_target") == args.voice_target]
    if not selected:
        raise SystemExit(f"No rows found for voice_target={args.voice_target!r}")

    voice_project = batch_voice_project(selected)
    resolved = resolve_generation_config(selected[0], "narrator", 1.0, 32)
    fieldnames = list(selected[0].values.keys())
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in selected:
            values = dict(row.values)
            if "reference_audio" in values and resolved.reference_audio:
                values["reference_audio"] = resolved.reference_audio
            if "status" in values:
                values["status"] = "PENDING_REGEN_CANONICAL_REFERENCE"
            w.writerow(values)

    print(f"EXPORTED={len(selected)}")
    print(f"VOICE_TARGET={args.voice_target}")
    print(f"VOICE_PROJECT={voice_project or '(none)'}")
    print(f"REFERENCE={resolved.reference_audio}")
    print(dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

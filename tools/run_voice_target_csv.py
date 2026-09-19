from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from csv_batch import (ERROR, batch_voice_project, build_job, read_csv,
                       validate_rows, write_job)
from tts_batch_runner import run_job

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one voice_target from an OmniVoice Studio CSV")
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--voice-target", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--line-timeout", type=float, default=1800.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = args.csv if args.csv.is_absolute() else ROOT / args.csv
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir

    rows = [r for r in read_csv(csv_path) if r.metadata("voice_target") == args.voice_target]
    if not rows:
        raise SystemExit(f"No rows found for voice_target={args.voice_target!r}")

    voice_project = batch_voice_project(rows)
    validate_rows(
        rows,
        output_dir,
        "narrator",
        skip_existing=not args.overwrite,
    )

    errors = [r for r in rows if r.status == ERROR]
    if errors:
        for r in errors:
            print(f"ERROR csv_row={r.csv_row_number} file={r.file_name} stage={r.error_stage}: {r.error}")
        raise SystemExit(f"Validation failed: {len(errors)} row(s)")

    for r in rows:
        r.selected = args.overwrite or r.status != "SKIPPED"

    selected = [r for r in rows if r.selected]
    if not selected:
        print(f"Nothing to do: all {len(rows)} row(s) already exist")
        return 0

    mission_id = f"{csv_path.stem}-{voice_project or 'legacy'}-{args.voice_target}"
    job = build_job(
        rows,
        output_dir,
        "narrator",
        1.0,
        32,
        mission_id=mission_id,
        overwrite_selected=args.overwrite,
    )
    job_path = ROOT / "work" / "jobs" / f"{mission_id}.json"
    write_job(job_path, job)

    print(f"CSV={csv_path}")
    print(f"VOICE_TARGET={args.voice_target}")
    print(f"VOICE_PROJECT={voice_project or '(none)'}")
    print(f"ROWS_TOTAL={len(rows)}")
    print(f"ROWS_SELECTED={len(selected)}")
    print(f"OUTPUT_DIR={output_dir}")
    print(f"JOB={job_path}")

    return run_job(job_path, line_timeout=args.line_timeout, reset=args.reset)


if __name__ == "__main__":
    raise SystemExit(main())

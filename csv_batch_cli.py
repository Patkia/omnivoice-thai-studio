from __future__ import annotations

import argparse
import sys
from pathlib import Path

from csv_batch import (
    ERROR,
    CsvBatchError,
    build_job,
    new_mission_id,
    read_csv,
    validate_rows,
    write_job,
)
from tts_batch_runner import DEFAULT_LINE_TIMEOUT_SECONDS, cancel_mission, run_job

ROOT = Path(__file__).resolve().parent
JOB_ROOT = ROOT / "output" / "batch_jobs"


def default_csv_output_dir(csv_path: Path) -> Path:
    return csv_path.resolve().parent / "input_wav"


def prepare_job(
    csv_path: Path,
    *,
    output_dir: Path | None = None,
    voice: str = "narrator",
    speed: float = 1.0,
    steps: int = 32,
    overwrite: bool = False,
    mission_id: str | None = None,
) -> tuple[dict | None, dict]:
    csv_path = csv_path.resolve()
    rows = read_csv(csv_path)
    output_dir = (output_dir or default_csv_output_dir(csv_path)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    validate_rows(
        rows,
        output_dir,
        voice,
        speed=speed,
        steps=steps,
        skip_existing=not overwrite,
        reset_selection=True,
    )

    if overwrite:
        for row in rows:
            if row.status != ERROR:
                row.selected = True

    errors = [row for row in rows if row.status == ERROR]
    selected = [row for row in rows if row.selected and row.status != ERROR]
    existing = [row for row in rows if not row.selected and (output_dir / row.file_name).exists()]
    summary = {
        "csv": str(csv_path),
        "output_dir": str(output_dir),
        "total": len(rows),
        "selected": len(selected),
        "existing": len(existing),
        "errors": len(errors),
    }
    if errors:
        details = "; ".join(f"row {row.csv_row_number}: {row.error}" for row in errors[:5])
        raise CsvBatchError(f"CSV validation failed ({len(errors)} row): {details}")
    if not selected:
        return None, summary

    mission_id = mission_id or new_mission_id(selected)
    job = build_job(
        rows,
        output_dir,
        voice,
        speed,
        steps,
        mission_id=mission_id,
        overwrite_selected=overwrite,
    )
    return job, summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate OmniVoice Thai WAV files from a Studio-compatible CSV."
    )
    parser.add_argument("csv", type=Path, help="CSV file to generate")
    parser.add_argument("--output", type=Path, help="Output directory (default: <CSV folder>/input_wav)")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate WAV files that already exist")
    parser.add_argument("--voice", default="narrator", help="Fallback voice alias for rows without voice_target")
    parser.add_argument("--speed", type=float, default=1.0, help="Fallback speed for rows without mapped speed")
    parser.add_argument("--steps", type=int, default=32, help="Fallback inference steps")
    parser.add_argument("--line-timeout", type=float, default=DEFAULT_LINE_TIMEOUT_SECONDS,
                        help="Soft watchdog seconds per row")
    parser.add_argument("--mission-id", help="Reuse an explicit mission id/checkpoint")
    parser.add_argument("--reset", action="store_true", help="Reset checkpoint for the selected mission")
    parser.add_argument(
        "--performance",
        choices=("normal", "max"),
        default="normal",
        help="CPU performance mode. 'max' uses all logical CPU threads and High process priority on Windows without changing audio quality.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        job, summary = prepare_job(
            args.csv,
            output_dir=args.output,
            voice=args.voice,
            speed=args.speed,
            steps=args.steps,
            overwrite=args.overwrite,
            mission_id=args.mission_id,
        )
    except (CsvBatchError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"CSV: {summary['csv']}")
    print(f"Output: {summary['output_dir']}")
    print(
        f"Rows: total={summary['total']} selected={summary['selected']} "
        f"existing={summary['existing']} errors={summary['errors']}"
    )
    if job is None:
        print("Nothing to generate: all WAV files already exist.")
        return 0

    job["performance_mode"] = args.performance
    if args.performance == "max":
        print("Performance: max (all logical CPU threads + High priority on Windows; audio quality unchanged)")

    mission_id = job["mission_id"]
    job_path = JOB_ROOT / f"{mission_id}.json"
    write_job(job_path, job)
    print(f"Mission: {mission_id}")
    print(f"Job: {job_path}")
    try:
        return run_job(job_path, args.line_timeout, reset=args.reset)
    except KeyboardInterrupt:
        print("\nCtrl+C received — cancelling OmniVoice batch worker...", file=sys.stderr)
        try:
            cancel_mission(mission_id)
        except Exception as exc:
            print(f"WARNING: automatic batch cancel failed: {exc}", file=sys.stderr)
            return 130
        print("Batch cancelled. Worker tree stopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

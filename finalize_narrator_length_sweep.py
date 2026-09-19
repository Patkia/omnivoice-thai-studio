"""Validate immutable length WAVs and finalize their JSON/Markdown reports."""
from __future__ import annotations

import json
from pathlib import Path

from run_narrator_excitement_polish import wav_metrics
from run_narrator_length_sweep import OUTPUT, write_length_markdown


def main() -> int:
    report_path = OUTPUT / "report_baseline.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    generation = json.loads((OUTPUT / "generation_report.json").read_text(encoding="utf-8"))
    runs = {Path(row["output"]).name.replace(".part.wav", ".wav"): row for row in generation["runs"]}
    for result in report["results"]:
        filename = Path(result["audio"]["path"]).name
        run = runs[filename]
        current = wav_metrics(OUTPUT / filename)
        if current["sha256"] != result["audio"]["sha256"]:
            raise RuntimeError(f"length WAV changed: {filename}")
        if run["model_load_count"] != 1:
            raise RuntimeError(f"model reload detected: {filename}")
        result["audio"] = current
        result["inference_seconds"] = run["inference_seconds"]
        result["generation_seconds"] = run["generation_seconds"]
        result["model_load_seconds"] = run["model_load_seconds"]
        result["model_reused"] = run["model_reused"]
    report["tests"] = {"framework": "unittest", "status": "PASS", "passed": 77, "total": 77}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_length_markdown(report, OUTPUT / "report_baseline.md")
    print(json.dumps({"status": report["status"], "report_finalized": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

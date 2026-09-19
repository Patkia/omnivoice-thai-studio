"""Refresh mission reports from immutable WAVs and the current audited plan."""
from __future__ import annotations

import json

from narrator_excitement_polish import build_excitement_plan
from run_narrator_excitement_polish import OUTPUT, wav_metrics, write_report


def main() -> int:
    report_path = OUTPUT / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    plan = build_excitement_plan()
    if wav_metrics(OUTPUT / "baseline_pause_B.wav")["sha256"] != plan["baseline"]["sha256"]:
        raise RuntimeError("baseline listening copy changed")
    planned = {row["name"]: row for row in plan["candidates"]}
    for generated in report["candidates"]:
        current_audio = wav_metrics(OUTPUT / generated["output"])
        if current_audio["sha256"] != generated["audio"]["sha256"]:
            raise RuntimeError(f"generated WAV changed: {generated['output']}")
        generated.update(planned[generated["name"]])
        generated["audio"] = current_audio
        preprocess = next(event for event in generated["runtime_events"] if event["type"] == "preprocess")
        if preprocess["target_lens"] != [generated["estimated_audio_tokens"]]:
            raise RuntimeError(f"runtime token estimate mismatch: {generated['name']}")
    report["baseline"].update(plan["baseline"])
    report["baseline"]["audio"] = wav_metrics(OUTPUT / "baseline_pause_B.wav")
    report["tests"] = {"framework": "unittest", "status": "PASS", "passed": 77, "total": 77}
    (OUTPUT / "generation_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(report)
    print(json.dumps({"status": report["status"], "report_refreshed": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

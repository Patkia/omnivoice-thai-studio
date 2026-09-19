#!/usr/bin/env python3
"""Prepare length fixtures by default; execute only after explicit human choice."""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import psutil

from narrator_length_sweep import build_length_sweep_plan


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "narrator_length_sweep"
MISSION_ID = "narrator-length-sweep-v1"


class PeakRssMonitor:
    def __init__(self, process, interval_seconds: float = 0.1):
        self.process = process
        self.interval_seconds = interval_seconds
        self.peak = process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.peak = max(self.peak, self.process.memory_info().rss)
            except psutil.Error:
                return

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self.peak = max(self.peak, self.process.memory_info().rss)
        except psutil.Error:
            pass


def write_length_markdown(report: dict, path: Path) -> None:
    lines = []
    for row in report["results"]:
        lines.extend([
            f"### {row['actual_characters']} characters",
            "",
            f"- estimated audio tokens: {row['estimated_audio_tokens']}",
            f"- application input count: {row['application_input_count']}",
            f"- model internal segmentation route: {'YES' if row['model_internal_segmentation_triggered'] else 'NO'}",
            f"- internal segments produced: {row['internal_segment_count']}",
            f"- output duration: {row['audio']['duration_seconds']:.3f}s",
            f"- inference time: {row['inference_seconds']:.3f}s",
            f"- total call elapsed time: {row['elapsed_seconds']:.3f}s",
            f"- peak RSS: {row['peak_rss_bytes']} bytes",
            f"- model load count: {row['model_load_count']}",
            f"- clipping: {row['audio']['clip_samples']} samples",
            f"- output: `{row['audio']['path']}`",
            "",
        ])
    tests = report.get("tests", {"status": "PENDING", "passed": 0, "total": 0})
    markdown = "# NARRATOR LENGTH SWEEP\n\n"
    markdown += "Approved winner: `baseline_pause_B.wav`\n\n"
    markdown += "Exact controls: `bright_female`, `female, young adult, high pitch`, seed `15016`, speed `1.00`, steps `32`.\n\n"
    markdown += "Application route: one input per fixture, no application semantic chunks.\n\n"
    markdown += "\n".join(lines)
    markdown += f"## Tests\n\nFull regression: {tests['status']} {tests['passed']}/{tests['total']}\n\n"
    markdown += "## HUMAN LISTENING TEST\n\nWAITING\n"
    path.write_text(markdown, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--winner", choices=("baseline", "E1", "E2"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-human-winner", action="store_true")
    args = parser.parse_args()
    winner = args.winner or "baseline"
    plan = build_length_sweep_plan(winner)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixture_path = OUTPUT / f"fixture_{winner}.json"
    fixture_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.execute:
        print(json.dumps({"status": "READY_NOT_GENERATED", "fixture": str(fixture_path), "winner_placeholder": winner}, ensure_ascii=False))
        return 0
    if not args.winner or not args.confirm_human_winner:
        raise RuntimeError("execution requires --winner and --confirm-human-winner after human listening")
    if args.winner != "baseline":
        raise RuntimeError("this mission approved baseline only; refusing a rejected candidate")
    import tts
    from run_narrator_excitement_polish import (
        competing_tts_processes,
        observe_model_segmentation,
        wav_metrics,
    )
    from studio_engine_adapter import StudioEngineAdapter
    from tts_batch_runner import acquire_lock, release_lock

    conflicts = competing_tts_processes()
    if conflicts:
        raise RuntimeError(f"competing TTS/Studio process detected: {conflicts}")
    outputs = [OUTPUT / row["output"] for row in plan["fixtures"]]
    if any(path.exists() for path in outputs):
        raise RuntimeError("refusing to overwrite an existing length-sweep WAV")

    lock_path, _ = acquire_lock(MISSION_ID)
    owner_pid = os.getpid()
    try:
        tts.REPORT_PATH = OUTPUT / "generation_report.json"
        adapter = StudioEngineAdapter()
        process = psutil.Process()
        results = []
        with observe_model_segmentation() as events:
            for row, output in zip(plan["fixtures"], outputs):
                part = output.with_suffix(".part.wav")
                event_start = len(events)
                rss_before = process.memory_info().rss
                started = time.perf_counter()
                with PeakRssMonitor(process) as memory:
                    meta = adapter.generate(row["text"], plan["voice"], plan["speed"], plan["steps"], part, False, seed=plan["seed"])
                os.replace(part, output)
                call_events = events[event_start:]
                chunk_events = [event for event in call_events if event["type"] == "internal_chunking"]
                internal_segment_count = (
                    chunk_events[0]["chunk_counts"][0]
                    if chunk_events and chunk_events[0]["chunk_counts"]
                    else 1
                )
                results.append({
                    **row, "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "inference_seconds": meta["inference_seconds"],
                    "rss_before_bytes": rss_before, "rss_after_bytes": process.memory_info().rss,
                    "peak_rss_bytes": memory.peak,
                    "model_internal_segmentation_triggered": any(event["type"] == "internal_chunking" for event in call_events),
                    "internal_segment_count": internal_segment_count,
                    "runtime_events": call_events, "model_load_count": meta["model_load_count"],
                    "audio": wav_metrics(output), "voice_continuity": "WAITING_FOR_HUMAN",
                    "paragraph_pause_behavior": "WAITING_FOR_HUMAN",
                })
        report = {
            **plan,
            "status": "WAITING_FOR_HUMAN_LISTENING",
            "human_decision": {
                "approved": "baseline_pause_B.wav",
                "rejected": {
                    "excitement_E1.wav": "voice drifted into male-like tone",
                    "excitement_E2.wav": "abnormal long pause / stalled delivery",
                },
            },
            "controls": {
                "single_process": True,
                "persistent_model_session": True,
                "model_load_count": adapter.session.model_load_count,
                "competing_processes_before_run": conflicts,
                "variables_changed_from_baseline": [],
            },
            "results": results,
            "tests": {"status": "PENDING", "passed": 0, "total": 0},
            "human_listening_test": "WAITING",
        }
        report_path = OUTPUT / f"report_{args.winner}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_length_markdown(report, OUTPUT / f"report_{args.winner}.md")
        print(json.dumps({"status": report["status"], "outputs": [str(path) for path in outputs], "model_load_count": adapter.session.model_load_count}, ensure_ascii=False))
        return 0
    finally:
        release_lock(lock_path, owner_pid)


if __name__ == "__main__":
    raise SystemExit(main())

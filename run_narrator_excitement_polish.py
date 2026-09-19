#!/usr/bin/env python3
"""Generate exactly two excitement candidates in one guarded model session."""
from __future__ import annotations

import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import psutil
import numpy as np
import soundfile as sf
from omnivoice import OmniVoice

import tts
from narrator_excitement_polish import BASELINE_WAV, build_excitement_plan, sha256
from studio_engine_adapter import StudioEngineAdapter
from tts_batch_runner import acquire_lock, release_lock


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "narrator_excitement_polish"
MISSION_ID = "narrator-excitement-polish-v1"


def competing_tts_processes() -> list[dict]:
    current = psutil.Process()
    excluded = {current.pid, *(parent.pid for parent in current.parents())}
    exact = {"studio.py", "generate_tts.py", "tts_batch_runner.py", "quick_voice_preview.py"}
    rows = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            args = process.info.get("cmdline") or []
            scripts = [Path(arg).name.lower() for arg in args if str(arg).lower().endswith(".py")]
            relevant = any(name in exact or name.startswith("run_") for name in scripts)
            in_workspace = any(str(ROOT).lower() in str(arg).lower() for arg in args)
            if process.pid not in excluded and relevant and in_workspace:
                rows.append({"pid": process.pid, "name": process.info.get("name"), "scripts": scripts})
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return rows


@contextmanager
def observe_model_segmentation():
    events: list[dict] = []
    original_preprocess = OmniVoice._preprocess_all
    original_chunked = OmniVoice._generate_chunked

    def tracked_preprocess(model, *args, **kwargs):
        task = original_preprocess(model, *args, **kwargs)
        events.append({"type": "preprocess", "target_lens": list(task.target_lens), "text_lengths": [len(x) for x in task.texts]})
        return task

    def tracked_chunked(model, task, config):
        event = {"type": "internal_chunking", "target_lens": list(task.target_lens), "chunk_counts": None}
        events.append(event)
        result = original_chunked(model, task, config)
        event["chunk_counts"] = [len(chunks) for chunks in result]
        return result

    OmniVoice._preprocess_all = tracked_preprocess
    OmniVoice._generate_chunked = tracked_chunked
    try:
        yield events
    finally:
        OmniVoice._preprocess_all = original_preprocess
        OmniVoice._generate_chunked = original_chunked


def wav_metrics(path: Path) -> dict:
    info = sf.info(path)
    audio, rate = sf.read(path, dtype="float64", always_2d=True)
    mono = audio.mean(axis=1)
    clip_threshold = 32767 / 32768
    return {
        "path": str(path), "sha256": sha256(path), "sample_rate": info.samplerate,
        "channels": info.channels, "frames": info.frames,
        "duration_seconds": round(info.frames / info.samplerate, 6),
        "peak": float(np.max(np.abs(mono))) if mono.size else 0.0,
        "rms": float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0,
        "clip_samples": int(np.count_nonzero(np.abs(mono) >= clip_threshold)),
    }


def write_report(report: dict) -> None:
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    baseline = report["baseline"]
    rows = {row["name"]: row for row in report["candidates"]}
    tests = report.get("tests", {"status": "PENDING", "passed": 0, "total": 0})
    md = f"""# NARRATOR EXCITEMENT POLISH

## Status

HUMAN LISTENING TEST: WAITING

## Baseline Pause B

- seed: {baseline['seed']}
- speed: {baseline['speed']:.2f}
- punctuation: {baseline['punctuation_strategy']}
- duration: {baseline['audio']['duration_seconds']:.3f}s
- output: `baseline_pause_B.wav`

## E1

- exact change: {rows['E1']['exact_change']}
- duration: {rows['E1']['audio']['duration_seconds']:.3f}s
- output: `excitement_E1.wav`

## E2

- exact change: {rows['E2']['exact_change']}
- duration: {rows['E2']['audio']['duration_seconds']:.3f}s
- output: `excitement_E2.wav`

## Controls

- application input count: 1 per candidate
- application semantic chunks: 0
- persistent model session: {str(report['controls']['persistent_model_session']).lower()}
- model load count: {report['controls']['model_load_count']}
- winner selected: false

## Length sweep

READY / NOT GENERATED

## Tests

- full regression: {tests['status']} {tests['passed']}/{tests['total']}

## Files changed

- `narrator_excitement_polish.py`
- `run_narrator_excitement_polish.py`
- `finalize_narrator_excitement_polish.py`
- `narrator_length_sweep.py`
- `run_narrator_length_sweep.py`
- `test_narrator_excitement_polish.py`
- `output/narrator_excitement_polish/`
- `output/narrator_length_sweep/fixture_baseline.json`

## HUMAN LISTENING TEST

WAITING

Listen in order: baseline Pause B, E1, E2. Report the best tone, whether excitement is sufficient, and whether the paragraph pause remains correct.
"""
    (OUTPUT / "report.md").write_text(md, encoding="utf-8")


def main() -> int:
    plan = build_excitement_plan()
    conflicts = competing_tts_processes()
    if conflicts:
        raise RuntimeError(f"competing TTS/Studio process detected: {conflicts}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    targets = [OUTPUT / "baseline_pause_B.wav", *(OUTPUT / row["output"] for row in plan["candidates"])]
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise RuntimeError(f"refusing to overwrite listening artifacts: {existing}")
    shutil.copyfile(BASELINE_WAV, targets[0])
    (OUTPUT / "generation_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lock_path, _ = acquire_lock(MISSION_ID)
    owner_pid = os.getpid()
    try:
        tts.REPORT_PATH = OUTPUT / "generation_report.json"
        adapter = StudioEngineAdapter()
        process = psutil.Process()
        generated = []
        with observe_model_segmentation() as events:
            for row in plan["candidates"]:
                output = OUTPUT / row["output"]
                part = output.with_suffix(".part.wav")
                before_events = len(events)
                rss_before = process.memory_info().rss
                started = time.perf_counter()
                result = adapter.generate(
                    row["spoken_text"], row["voice"], row["speed"], row["steps"],
                    part, force=False, seed=row["seed"],
                )
                os.replace(part, output)
                call_events = events[before_events:]
                generated.append({
                    **row,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "rss_before_bytes": rss_before,
                    "rss_after_bytes": process.memory_info().rss,
                    "model_internal_segmentation_triggered": any(event["type"] == "internal_chunking" for event in call_events),
                    "runtime_events": call_events,
                    "model_load_count": result["model_load_count"],
                    "model_reused": result["model_reused"],
                    "audio": wav_metrics(output),
                })
        report = {
            "status": "WAITING_FOR_HUMAN_LISTENING",
            "baseline": {**plan["baseline"], "audio": wav_metrics(targets[0])},
            "candidates": generated,
            "controls": {
                "candidate_count": len(generated), "single_process": True,
                "persistent_model_session": True, "model_load_count": adapter.session.model_load_count,
                "application_input_count_each": 1, "application_semantic_chunks": 0,
                "competing_processes_before_run": conflicts, "winner_selected": False,
            },
            "length_sweep": "READY_NOT_GENERATED",
            "tests": {"status": "PENDING", "passed": 0, "total": 0},
            "human_listening_test": "WAITING",
        }
        write_report(report)
        print(json.dumps({"status": report["status"], "output": str(OUTPUT), "model_load_count": adapter.session.model_load_count}, ensure_ascii=False))
        return 0
    finally:
        release_lock(lock_path, owner_pid)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create a resumable, single-process narrator seed/punctuation listening pack."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

import tts
from narrator_single_inference_tuning import build_tuning_plan
from studio_engine_adapter import StudioEngineAdapter
from tts_batch_runner import acquire_lock, release_lock


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "narrator_single_inference_tuning"
SOURCE = ROOT / "output" / "narrator_continuity_fixture"
STATE = OUTPUT / "run_state.json"
MISSION_ID = "narrator-single-inference-tuning-v1"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _copy_exact(source: Path, target: Path) -> dict:
    raw = source.read_bytes()
    if target.exists():
        if target.read_bytes() != raw:
            raise RuntimeError(f"existing reference differs; refusing overwrite: {target}")
    else:
        target.write_bytes(raw)
    return {"source": str(source), "output": str(target), "sha256": _hash_bytes(raw), "byte_identical": True}


def _metrics(path: Path) -> dict:
    audio, rate = sf.read(path, dtype="float64", always_2d=True)
    mono = audio.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0
    return {
        "path": str(path), "sha256": _hash_file(path), "sample_rate": int(rate),
        "channels": int(audio.shape[1]), "frames": int(audio.shape[0]),
        "duration_seconds": round(audio.shape[0] / rate, 6),
        "peak": float(np.max(np.abs(mono))) if mono.size else 0.0,
        "rms": rms, "dc_mean": float(np.mean(mono)) if mono.size else 0.0,
        "clip_samples": int(np.count_nonzero(np.abs(mono) >= 0.999969482421875)),
        "non_silent": bool(rms > 1e-5),
    }


def _load_state(plan_hash: str) -> dict:
    if not STATE.exists():
        return {"plan_hash": plan_hash, "status": "running", "candidates": {}}
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("plan_hash") != plan_hash:
        raise RuntimeError("existing run_state belongs to a different plan; refusing overwrite")
    return state


def main() -> int:
    plan = build_tuning_plan()
    plan_raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan_hash = _hash_bytes(plan_raw)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    canonical_path = OUTPUT / "canonical_text.txt"
    canonical_bytes = plan["canonical_text"].encode("utf-8")
    if canonical_path.exists() and canonical_path.read_bytes() != canonical_bytes:
        raise RuntimeError("existing canonical_text differs; refusing overwrite")
    canonical_path.write_bytes(canonical_bytes)
    plan_path = OUTPUT / "tuning_plan.json"
    if plan_path.exists() and _hash_bytes(plan_path.read_bytes()) != _hash_bytes(json.dumps(plan, ensure_ascii=False, indent=2).encode("utf-8")):
        raise RuntimeError("existing tuning_plan differs; refusing overwrite")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    references = {
        "A_chunk2_target": _copy_exact(SOURCE / "batch_chunks" / "A_current_chunked" / "002.wav", OUTPUT / "A_chunk2_target.wav"),
        "B_single_inference_seed15016": _copy_exact(SOURCE / "B_single_inference.wav", OUTPUT / "B_single_inference_seed15016.wav"),
    }
    lock_path, _lock = acquire_lock(MISSION_ID)
    owner_pid = os.getpid()
    try:
        tts.REPORT_PATH = OUTPUT / "generation_report.json"
        state = _load_state(plan_hash)
        adapter = StudioEngineAdapter()
        for candidate in plan["candidates"]:
            name = candidate["name"]
            output = OUTPUT / candidate["output"]
            previous = state["candidates"].get(name)
            if previous and previous.get("status") == "completed" and output.is_file() and previous.get("sha256") == _hash_file(output):
                continue
            if output.exists():
                raise RuntimeError(f"unowned candidate exists; refusing overwrite: {output}")
            part = output.with_suffix(".part.wav")
            if part.exists():
                part.unlink()
            state["candidates"][name] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
            _atomic_json(STATE, state)
            started = time.perf_counter()
            try:
                result = adapter.generate(
                    candidate["spoken_text"], candidate["voice"], candidate["speed"], candidate["steps"],
                    part, force=False, seed=candidate["seed"],
                )
                os.replace(part, output)
            except Exception as exc:
                part.unlink(missing_ok=True)
                state["candidates"][name] = {"status": "failed", "error": str(exc)}
                _atomic_json(STATE, state)
                raise
            metrics = _metrics(output)
            state["candidates"][name] = {
                "status": "completed", "elapsed_seconds": round(time.perf_counter() - started, 3),
                "seed": candidate["seed"], "cache_key": candidate["cache_key"], **metrics,
            }
            _atomic_json(STATE, state)
        state["status"] = "completed"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state["references"] = references
        _atomic_json(STATE, state)
        report = {
            "status": "LISTENING_PACK_READY",
            "plan": plan,
            "references": {name: {**data, "audio": _metrics(Path(data["output"]))} for name, data in references.items()},
            "candidates": state["candidates"],
            "controls": {
                "single_process": True, "persistent_model_session": True, "application_semantic_chunks": 0,
                "model": tts.load_json(tts.ENGINE_PATH)["model"], "revision": tts.load_json(tts.ENGINE_PATH)["revision"],
                "source_canonical_changed": False, "game_files_touched": False, "winner_selected": False,
            },
            "human_listening_test": "WAITING",
        }
        (OUTPUT / "forensic_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "output": str(OUTPUT), "candidates": state["candidates"]}, ensure_ascii=False, indent=2))
        return 0
    finally:
        release_lock(lock_path, owner_pid)


if __name__ == "__main__":
    raise SystemExit(main())

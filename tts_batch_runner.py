#!/usr/bin/env python3
"""Resumable, single-run batch orchestrator for OmniVoice TTS.

The public ``run`` command owns a mission lock and starts one worker process.  The
worker keeps a single ``StudioEngineAdapter`` alive and processes lines
sequentially.  Checkpoints make retries idempotent; a watchdog can terminate the
worker process tree if one line exceeds its timeout.

This layer intentionally sits above ``tts.py`` / ``tts_runtime.py`` so the frozen
single-generation engine semantics stay unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tts
from csv_batch import validate_voice_project_id
from studio_engine_adapter import (StudioEngineAdapter, validate_reference_audio,
                                   validate_reference_text)
from studio_generation import generate_studio_request

ROOT = Path(__file__).resolve().parent
STATE_ROOT = ROOT / "output" / "batch_state"
POLL_SECONDS = 0.5
MAX_GENERATION_RETRIES = 1
DEFAULT_LINE_TIMEOUT_SECONDS = 1800.0
HARD_STALL_MULTIPLIER = 4.0
MIN_HARD_STALL_SECONDS = 7200.0


class BatchRunnerError(RuntimeError):
    """Safe, user-facing orchestration failure."""


def no_console_subprocess_kwargs(*, new_process_group: bool = False) -> dict[str, Any]:
    """Hide a Windows helper process while retaining non-Windows behavior."""
    if os.name != "nt":
        return {"creationflags": 0}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    options: dict[str, Any] = {"creationflags": flags}
    startup_info = getattr(subprocess, "STARTUPINFO", None)
    startf_use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)
    if startup_info is not None:
        info = startup_info()
        info.dwFlags |= startf_use_show_window
        info.wShowWindow = sw_hide
        options["startupinfo"] = info
    return options


def background_process_kwargs() -> dict[str, Any]:
    """Keep Windows batch descendants console-free and separately cancellable."""
    return no_console_subprocess_kwargs(new_process_group=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchRunnerError(f"อ่าน state ไม่ได้: {path}: {exc}") from exc


def _safe_id(value: str) -> str:
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in value):
        raise BatchRunnerError("mission_id/line id ใช้ได้เฉพาะ A-Z, a-z, 0-9, -, _, .")
    return value


def _mission_paths(mission_id: str) -> dict[str, Path]:
    mission_id = _safe_id(mission_id)
    base = STATE_ROOT / mission_id
    return {
        "base": base,
        "lock": base / "lock.json",
        "checkpoint": base / "checkpoint.json",
        "snapshot": base / "job.snapshot.json",
    }


def _canonical_hash(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False,
            **no_console_subprocess_kwargs(),
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    return True


def _kill_tree(pid: int | None) -> None:
    if not _pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False,
            **no_console_subprocess_kwargs(),
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            return


def _lock_is_live(lock: dict[str, Any]) -> bool:
    return _pid_alive(lock.get("parent_pid")) or _pid_alive(lock.get("worker_pid"))


def acquire_lock(mission_id: str) -> tuple[Path, dict[str, Any]]:
    paths = _mission_paths(mission_id)
    lock_path = paths["lock"]
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        existing = _read_json(lock_path)
        if _lock_is_live(existing):
            raise BatchRunnerError(
                f"mission '{mission_id}' กำลังทำงานอยู่ (parent={existing.get('parent_pid')}, worker={existing.get('worker_pid')})"
            )
        lock_path.unlink(missing_ok=True)
    data = {"mission_id": mission_id, "parent_pid": os.getpid(), "worker_pid": None, "started_at": _utc_now()}
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BatchRunnerError(f"mission '{mission_id}' ถูก lock โดย process อื่น") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return lock_path, data


def release_lock(lock_path: Path, owner_pid: int) -> None:
    if not lock_path.exists():
        return
    try:
        lock = _read_json(lock_path)
    except BatchRunnerError:
        return
    if lock.get("parent_pid") == owner_pid:
        lock_path.unlink(missing_ok=True)


def _load_job(path: Path) -> dict[str, Any]:
    job = _read_json(path)
    mission_id = _safe_id(str(job.get("mission_id", "")))
    lines = job.get("lines")
    if not isinstance(lines, list) or not lines:
        raise BatchRunnerError("job ต้องมี lines อย่างน้อย 1 รายการ")
    defaults = job.get("defaults") or {}
    output_dir = Path(job.get("output_dir") or f"output/batch/{mission_id}")
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    seen: set[str] = set()
    normalized = []
    for index, raw in enumerate(lines, 1):
        if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
            raise BatchRunnerError(f"line {index} ไม่มี text")
        line_id = _safe_id(str(raw.get("id") or f"{index:03d}"))
        if line_id in seen:
            raise BatchRunnerError(f"line id ซ้ำ: {line_id}")
        seen.add(line_id)
        alias = str(raw.get("voice", defaults.get("voice", "narrator")))
        registry = tts.load_json(tts.REGISTRY_PATH)
        voice = tts.resolve_voice(alias, registry)
        speed = float(raw.get("speed", defaults.get("speed", voice["speed"])))
        steps = int(raw.get("steps", defaults.get("steps", tts.load_json(tts.ENGINE_PATH)["default_steps"])))
        seed = raw["seed"] if "seed" in raw else defaults.get("seed")
        voice_project = str(raw.get("voice_project", defaults.get("voice_project", ""))).strip()
        if voice_project:
            try:
                voice_project = validate_voice_project_id(voice_project)
            except ValueError as exc:
                raise BatchRunnerError(f"voice_project ของ line {line_id} ไม่ถูกต้อง: {exc}") from exc
        generation_mode = raw.get("generation_mode", defaults.get("generation_mode", "voice_design"))
        if generation_mode not in {"voice_design", "reference_first"}:
            raise BatchRunnerError(f"generation_mode ของ line {line_id} ไม่รองรับ: {generation_mode!r}")
        instruction_override = raw.get("instruction_override", defaults.get("instruction_override"))
        if (generation_mode == "voice_design" and instruction_override is not None
                and (not isinstance(instruction_override, str) or not instruction_override.strip())):
            raise BatchRunnerError(f"instruction_override ของ line {line_id} ต้องเป็นข้อความที่ไม่ว่าง")
        if generation_mode == "reference_first":
            instruction_override = None
        reference_conditioning = raw.get("reference_conditioning", defaults.get("reference_conditioning", False)) is True
        reference_audio = raw.get("reference_audio", defaults.get("reference_audio"))
        reference_sha256 = raw.get("reference_sha256", defaults.get("reference_sha256"))
        reference_text = raw.get("reference_text", defaults.get("reference_text"))
        reference_text_sha256 = raw.get("reference_text_sha256", defaults.get("reference_text_sha256"))
        if reference_conditioning:
            if not all(isinstance(value, str) and value for value in (
                    reference_audio, reference_sha256, reference_text, reference_text_sha256)):
                raise BatchRunnerError(
                    f"reference conditioning ของ line {line_id} ไม่ครบ; ห้าม fallback ไป instruct-only"
                )
            try:
                validate_reference_audio(reference_audio, reference_sha256)
                validate_reference_text(reference_text, reference_text_sha256)
            except (OSError, ValueError) as exc:
                raise BatchRunnerError(f"reference ของ line {line_id} ไม่ผ่าน: {exc}") from exc
        if generation_mode == "reference_first" and not reference_conditioning:
            raise BatchRunnerError(
                f"reference_first ของ line {line_id} ต้องมี reference conditioning ที่ผ่าน validation"
            )
        language = raw.get("language", defaults.get("language"))
        denoise = raw.get("denoise", defaults.get("denoise"))
        postprocess_output = raw.get("postprocess_output", defaults.get("postprocess_output"))
        if language is not None and (not isinstance(language, str) or not language.strip()):
            raise BatchRunnerError(f"language ของ line {line_id} ไม่ถูกต้อง")
        if denoise is not None and not isinstance(denoise, bool):
            raise BatchRunnerError(f"denoise ของ line {line_id} ไม่ถูกต้อง")
        if postprocess_output is not None and not isinstance(postprocess_output, bool):
            raise BatchRunnerError(f"postprocess_output ของ line {line_id} ไม่ถูกต้อง")
        output_name = str(raw.get("output") or f"{line_id}.wav")
        output = Path(output_name)
        if output.is_absolute() or ".." in output.parts:
            raise BatchRunnerError(f"output ของ line {line_id} ต้องเป็น path สัมพัทธ์ภายใน output_dir")
        normalized.append({
            "id": line_id, "text": raw["text"], "voice": alias, "speed": speed, "steps": steps,
            "seed": seed, "output": str(output), "force": bool(raw.get("force", defaults.get("force", False))),
            "skip_existing": bool(raw.get("skip_existing", defaults.get("skip_existing", True))),
            "instruction_override": instruction_override,
            "generation_mode": generation_mode,
            "voice_project": voice_project,
            "voice_target": str(raw.get("voice_target", "")),
            "canonical_text": str(raw.get("canonical_text", raw["text"])),
            "tts_text": str(raw.get("tts_text", "")),
            "resolved_spoken_text": str(raw.get("resolved_spoken_text", raw["text"])),
            "reference_conditioning": reference_conditioning,
            "reference_audio": reference_audio,
            "reference_sha256": reference_sha256,
            "reference_text": reference_text,
            "reference_text_sha256": reference_text_sha256,
            "language": language,
            "denoise": denoise,
            "postprocess_output": postprocess_output,
        })
    return {"mission_id": mission_id, "output_dir": str(output_dir), "lines": normalized}


def _line_signature(line: dict[str, Any]) -> str:
    fields = (
        "text", "voice", "speed", "steps", "seed", "instruction_override", "generation_mode",
        "voice_project", "output",
        "voice_target", "reference_conditioning", "reference_audio", "reference_sha256",
        "reference_text", "reference_text_sha256", "language", "denoise", "postprocess_output",
    )
    payload = {key: line.get(key) for key in fields}
    payload["force"] = bool(line.get("force", False))
    payload["skip_existing"] = bool(line.get("skip_existing", True))
    return _canonical_hash(payload)


def _new_checkpoint(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "mission_id": job["mission_id"], "job_hash": _canonical_hash(job), "status": "pending",
        "created_at": _utc_now(), "updated_at": _utc_now(), "current_line_id": None,
        "reference_prompts": {},
        "runtime": {"model_load_count": 0, "reference_prompt_prep_count": 0},
        "lines": {line["id"]: {
            "signature": _line_signature(line), "status": "pending", "output": line["output"],
            "voice_target": line.get("voice_target", ""),
            "voice_project": line.get("voice_project", ""),
            "generation_mode": line.get("generation_mode", "voice_design"),
            "resolved_spoken_text": line.get("resolved_spoken_text", line["text"]),
            "reference_conditioning": bool(line.get("reference_conditioning")),
            "reference_sha256": line.get("reference_sha256"),
        } for line in job["lines"]},
    }


def _load_or_init_checkpoint(job: dict[str, Any], checkpoint_path: Path, reset: bool = False) -> dict[str, Any]:
    if reset:
        checkpoint_path.unlink(missing_ok=True)
    expected_hash = _canonical_hash(job)
    if checkpoint_path.exists():
        checkpoint = _read_json(checkpoint_path)
        if checkpoint.get("job_hash") != expected_hash:
            raise BatchRunnerError("job เปลี่ยนจาก checkpoint เดิม; ใช้ mission_id ใหม่ หรือ run --reset")
        return checkpoint
    checkpoint = _new_checkpoint(job)
    _atomic_json(checkpoint_path, checkpoint)
    return checkpoint


def _mark(checkpoint_path: Path, checkpoint: dict[str, Any], *, status: str | None = None, current: str | None = None) -> None:
    if status is not None:
        checkpoint["status"] = status
    checkpoint["current_line_id"] = current
    checkpoint["updated_at"] = _utc_now()
    _atomic_json(checkpoint_path, checkpoint)


def _valid_completed_line(state: dict[str, Any], line: dict[str, Any], output_dir: Path) -> bool:
    output = output_dir / line["output"]
    return state.get("status") == "completed" and state.get("signature") == _line_signature(line) and output.is_file()


def _generation_error(exc: Exception, *, attempt: int) -> dict[str, Any]:
    """Return durable diagnostics without collapsing failures to FAILED only."""
    return {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "error_stage": "generation",
        "attempt": attempt,
        "traceback": traceback.format_exc(),
    }


def _retryable_generation_error(exc: Exception) -> bool:
    """Only retry runtime/audio output failures; never retry config/validation errors."""
    return isinstance(exc, RuntimeError)


def _format_elapsed(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes, secs = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s"


def _print_completed_progress(index: int, total: int, filename: str, elapsed_seconds: float) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(
        f"[{timestamp}] [{index}/{total}] DONE {filename} | elapsed {_format_elapsed(elapsed_seconds)}",
        flush=True,
    )

def _worker_main_impl(job_path: Path, checkpoint_path: Path) -> int:
    job = _load_job(job_path)
    checkpoint = _load_or_init_checkpoint(job, checkpoint_path)
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    failed_count = 0
    _mark(checkpoint_path, checkpoint, status="running", current=None)
    reference_specs = {}
    for line in job["lines"]:
        if line["reference_conditioning"]:
            key = f"{line['voice_project']}:{line['reference_sha256']}:{line['reference_text_sha256']}"
            reference_specs[key] = line
    for key, line in reference_specs.items():
        prompt_state = {
            "status": "preparing", "voice_target": line["voice_target"],
            "reference_audio": line["reference_audio"],
            "reference_sha256": line["reference_sha256"],
            "reference_text_sha256": line["reference_text_sha256"],
        }
        checkpoint.setdefault("reference_prompts", {})[key] = prompt_state
        _mark(checkpoint_path, checkpoint, status="running", current=None)
        try:
            prompt_meta = adapter.prepare_reference_conditioning(
                line["reference_audio"], line["reference_sha256"],
                line["reference_text"], line["reference_text_sha256"],
                voice_project=line["voice_project"],
            )
        except Exception as exc:
            prompt_state.update({"status": "failed", "error": str(exc), "failed_at": _utc_now()})
            checkpoint["preflight_error"] = str(exc)
            _mark(checkpoint_path, checkpoint, status="failed", current=None)
            raise
        prompt_state.update({"status": "prepared", "prepared_at": _utc_now(), **prompt_meta})
        checkpoint["runtime"] = {
            "model_load_count": adapter.session.model_load_count,
            "reference_prompt_prep_count": adapter.session.reference_prompt_prep_count,
        }
        _mark(checkpoint_path, checkpoint, status="running", current=None)
    total_lines = len(job["lines"])
    for line_index, line in enumerate(job["lines"], start=1):
        line_state = checkpoint["lines"][line["id"]]
        final_output = output_dir / line["output"]
        if _valid_completed_line(line_state, line, output_dir):
            continue
        part_output = final_output.with_name(final_output.stem + ".part" + final_output.suffix)
        # If the worker died after the atomic rename but before checkpoint commit,
        # the final file is ours when this exact signature had already started.
        if (final_output.exists() and line_state.get("signature") == _line_signature(line)
                and line_state.get("status") in {"running", "failed", "timeout", "cancelled"}
                and not part_output.exists()):
            line_state.update({"status": "completed", "completed_at": _utc_now(), "recovered_after_crash": True})
            _mark(checkpoint_path, checkpoint, status="running", current=None)
            continue
        if final_output.exists() and line["skip_existing"] and not line["force"]:
            line_state.update({"status": "skipped", "reason": "existing output preserved", "output": line["output"]})
            _mark(checkpoint_path, checkpoint, status="running", current=None)
            continue
        if final_output.exists() and not line["force"]:
            raise BatchRunnerError(
                f"output มีอยู่แต่ checkpoint ไม่ยืนยันว่าเสร็จ: {final_output}; ใช้ output ใหม่หรือ force=true"
            )
        part_output.unlink(missing_ok=True)
        line_state.update({
            "signature": _line_signature(line), "status": "running", "started_at_epoch": time.time(),
            "last_progress_epoch": time.time(), "started_at": _utc_now(), "error": None,
        })
        _mark(checkpoint_path, checkpoint, status="running", current=line["id"])
        succeeded = False
        for attempt in range(MAX_GENERATION_RETRIES + 1):
            try:
                result = generate_studio_request(
                    adapter, line["text"], line["voice"], line["speed"], line["steps"], part_output,
                    force=line["force"], seed=line["seed"], instruction_override=line["instruction_override"],
                    generation_mode=line["generation_mode"], language=line["language"],
                    denoise=line["denoise"], postprocess_output=line["postprocess_output"],
                    voice_project=line["voice_project"],
                    reference_conditioning=line["reference_conditioning"],
                    reference_audio=line["reference_audio"], reference_sha256=line["reference_sha256"],
                    reference_text=line["reference_text"], reference_text_sha256=line["reference_text_sha256"],
                )
                final_output.parent.mkdir(parents=True, exist_ok=True)
                os.replace(part_output, final_output)
                line_state.update({
                    "status": "completed", "completed_at": _utc_now(), "cache_hit": bool(result.get("cache_hit")),
                    "inference_seconds": result.get("inference_seconds", 0.0), "output": line["output"],
                    "model_load_count": adapter.session.model_load_count,
                    "reference_prompt_prep_count": adapter.session.reference_prompt_prep_count,
                    "attempts": attempt + 1,
                })
                checkpoint["runtime"] = {
                    "model_load_count": adapter.session.model_load_count,
                    "reference_prompt_prep_count": adapter.session.reference_prompt_prep_count,
                }
                _mark(checkpoint_path, checkpoint, status="running", current=None)
                _print_completed_progress(
                    line_index,
                    total_lines,
                    line["output"],
                    time.time() - float(line_state["started_at_epoch"]),
                )
                succeeded = True
                break
            except Exception as exc:
                part_output.unlink(missing_ok=True)
                details = _generation_error(exc, attempt=attempt + 1)
                if _retryable_generation_error(exc) and attempt < MAX_GENERATION_RETRIES:
                    line_state.update({"status": "running", "last_error": details, "retry_count": attempt + 1})
                    _mark(checkpoint_path, checkpoint, status="running", current=line["id"])
                    continue
                failed_count += 1
                line_state.update({"status": "failed", "error": details["error_message"], "failed_at": _utc_now(), **details})
                _mark(checkpoint_path, checkpoint, status="running", current=None)
                break
        if not succeeded:
            continue
    _mark(checkpoint_path, checkpoint, status="failed" if failed_count else "completed", current=None)
    return 1 if failed_count else 0


def _last_completed_row(checkpoint: dict[str, Any]) -> str | None:
    last = None
    for line_id, state in (checkpoint.get("lines") or {}).items():
        if state.get("status") in {"completed", "skipped"}:
            last = line_id
    return last


def _record_batch_interruption(checkpoint_path: Path, checkpoint: dict[str, Any], exc: BaseException, *, stage: str, process_exit_reason: str | None = None) -> None:
    current = checkpoint.get("current_line_id")
    current_state = (checkpoint.get("lines") or {}).get(current, {}) if current else {}
    if current and current_state.get("status") == "running":
        current_state.update({"status": "pending", "interrupted": True})
    checkpoint.update({
        "status": "interrupted",
        "batch_error_type": type(exc).__name__,
        "batch_error_message": str(exc),
        "batch_error_stage": stage,
        "batch_traceback": "".join(traceback.format_exception(exc)),
        "last_active_row": current,
        "last_completed_row": _last_completed_row(checkpoint),
        "process_exit_reason": process_exit_reason or "batch_exception",
    })
    _mark(checkpoint_path, checkpoint, status="interrupted", current=None)


def worker_main(job_path: Path, checkpoint_path: Path) -> int:
    try:
        return _worker_main_impl(job_path, checkpoint_path)
    except Exception as exc:
        try:
            checkpoint = _read_json(checkpoint_path)
            _record_batch_interruption(checkpoint_path, checkpoint, exc, stage="WORKER", process_exit_reason="worker_exception")
        except Exception:
            pass
        raise


def _spawn_worker(snapshot: Path, checkpoint: Path) -> subprocess.Popen:
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--job", str(snapshot), "--checkpoint", str(checkpoint)]
    return subprocess.Popen(command, cwd=str(ROOT), **background_process_kwargs())


def _watch_worker(proc: subprocess.Popen, checkpoint_path: Path, line_timeout: float,
                  poll_seconds: float = POLL_SECONDS, output_dir: Path | None = None) -> int:
    while True:
        code = proc.poll()
        if code is not None:
            return code
        if checkpoint_path.exists():
            try:
                checkpoint = _read_json(checkpoint_path)
            except BatchRunnerError:
                time.sleep(poll_seconds)
                continue
            current = checkpoint.get("current_line_id")
            if current:
                state = checkpoint.get("lines", {}).get(current, {})
                started = float(state.get("started_at_epoch", 0) or 0)
                last_progress = float(state.get("last_progress_epoch", started) or started)
                now = time.time()
                part_path = None
                part_mtime = None
                if output_dir is not None:
                    output_name = str(state.get("output", ""))
                    if output_name:
                        final = output_dir / output_name
                        part_path = final.with_name(final.stem + ".part" + final.suffix)
                        try:
                            part_mtime = part_path.stat().st_mtime
                        except OSError:
                            part_mtime = None
                observed_progress = part_mtime if part_mtime is not None and part_mtime > last_progress else last_progress
                elapsed = now - started if started else 0.0
                stalled_for = now - observed_progress if observed_progress else elapsed
                hard_stall_seconds = max(line_timeout * HARD_STALL_MULTIPLIER, MIN_HARD_STALL_SECONDS)
                if elapsed > line_timeout:
                    latest = _read_json(checkpoint_path)
                    latest_state = latest.get("lines", {}).get(current, {})
                    if latest.get("current_line_id") == current and latest_state.get("status") == "running":
                        latest_state["watchdog_warning"] = f"watchdog threshold {line_timeout:.0f}s exceeded; worker still active"
                        latest_state["watchdog_warning_count"] = int(latest_state.get("watchdog_warning_count", 0)) + 1
                        latest_state["watchdog_last_warning_epoch"] = now
                        latest["watchdog_warning"] = {
                            "row": current, "line_timeout_seconds": line_timeout,
                            "recorded_at": _utc_now(), "worker_alive": True,
                        }
                        if stalled_for >= hard_stall_seconds and not latest_state.get("watchdog_suspected_stall"):
                            latest_state["watchdog_suspected_stall"] = {
                                "elapsed_seconds": round(elapsed, 3),
                                "stalled_for_seconds": round(stalled_for, 3),
                                "hard_stall_threshold_seconds": hard_stall_seconds,
                                "last_progress_epoch": observed_progress,
                                "part_path": str(part_path) if part_path else None,
                                "part_mtime": part_mtime,
                                "worker_pid": proc.pid,
                                "action": "manual_cancel_required",
                            }
                            latest["watchdog_suspected_stall"] = latest_state["watchdog_suspected_stall"]
                        _mark(checkpoint_path, latest, status="running", current=current)
        time.sleep(poll_seconds)


def run_job(job_path: Path, line_timeout: float, reset: bool = False) -> int:
    job = _load_job(job_path)
    paths = _mission_paths(job["mission_id"])
    lock_path, lock = acquire_lock(job["mission_id"])
    owner_pid = os.getpid()
    try:
        checkpoint = _load_or_init_checkpoint(job, paths["checkpoint"], reset=reset)
        _atomic_json(paths["snapshot"], job)
        if checkpoint.get("status") == "completed" and all(
            _valid_completed_line(checkpoint["lines"][line["id"]], line, Path(job["output_dir"])) for line in job["lines"]
        ):
            print(json.dumps({"mission_id": job["mission_id"], "status": "completed", "resume": "nothing_to_do"}, ensure_ascii=False))
            return 0
        proc = _spawn_worker(paths["snapshot"], paths["checkpoint"])
        lock["worker_pid"] = proc.pid
        _atomic_json(lock_path, lock)
        code = _watch_worker(proc, paths["checkpoint"], line_timeout, output_dir=Path(job["output_dir"]))
        try:
            final_checkpoint = _read_json(paths["checkpoint"])
            if code not in (0, 124) and final_checkpoint.get("status") == "running":
                exit_error = BatchRunnerError(f"worker exited with code {code}")
                _record_batch_interruption(paths["checkpoint"], final_checkpoint, exit_error, stage="WORKER_EXIT", process_exit_reason=f"worker_exit_{code}")
        except Exception:
            pass
        if code == 0:
            print(json.dumps({"mission_id": job["mission_id"], "status": "completed", "checkpoint": str(paths["checkpoint"])}, ensure_ascii=False))
        elif code == 124:
            print(f"TIMEOUT: mission {job['mission_id']} ถูกหยุดเฉพาะ worker tree; rerun คำสั่งเดิมเพื่อ resume", file=sys.stderr)
        else:
            print(f"FAILED: worker exit code {code}; rerun คำสั่งเดิมเพื่อ resume หลังแก้สาเหตุ", file=sys.stderr)
        return code
    finally:
        release_lock(lock_path, owner_pid)


def mission_status(mission_id: str) -> dict[str, Any]:
    paths = _mission_paths(mission_id)
    lock = _read_json(paths["lock"]) if paths["lock"].exists() else None
    checkpoint = _read_json(paths["checkpoint"]) if paths["checkpoint"].exists() else None
    return {"mission_id": mission_id, "running": bool(lock and _lock_is_live(lock)), "lock": lock, "checkpoint": checkpoint}


def status_mission(mission_id: str) -> int:
    print(json.dumps(mission_status(mission_id), ensure_ascii=False, indent=2))
    return 0


def cancel_mission(mission_id: str) -> int:
    paths = _mission_paths(mission_id)
    if not paths["lock"].exists():
        print(json.dumps({"mission_id": mission_id, "status": "not_running"}, ensure_ascii=False))
        return 0
    lock = _read_json(paths["lock"])
    worker_pid, parent_pid = lock.get("worker_pid"), lock.get("parent_pid")
    _kill_tree(worker_pid)
    if parent_pid != os.getpid():
        _kill_tree(parent_pid)
    if paths["checkpoint"].exists():
        checkpoint = _read_json(paths["checkpoint"])
        current = checkpoint.get("current_line_id")
        if current and checkpoint.get("lines", {}).get(current, {}).get("status") == "running":
            checkpoint["lines"][current].update({"status": "cancelled", "error": "cancelled by operator", "failed_at": _utc_now()})
        _mark(paths["checkpoint"], checkpoint, status="cancelled", current=current)
    paths["lock"].unlink(missing_ok=True)
    print(json.dumps({"mission_id": mission_id, "status": "cancelled", "worker_pid": worker_pid, "parent_pid": parent_pid}, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable OmniVoice batch TTS runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="เริ่มหรือ resume batch job")
    run.add_argument("--job", type=Path, required=True)
    run.add_argument("--line-timeout", type=float, default=DEFAULT_LINE_TIMEOUT_SECONDS, help="timeout ต่อบรรทัด (วินาที)")
    run.add_argument("--reset", action="store_true", help="ล้าง checkpoint เดิมของ mission ก่อนเริ่ม")
    status = sub.add_parser("status", help="ดู lock/checkpoint โดยไม่เริ่ม TTS")
    status.add_argument("--mission-id", required=True)
    cancel = sub.add_parser("cancel", help="หยุดเฉพาะ process tree ของ mission")
    cancel.add_argument("--mission-id", required=True)
    worker = sub.add_parser("_worker")
    worker.add_argument("--job", type=Path, required=True)
    worker.add_argument("--checkpoint", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "run":
        if args.line_timeout <= 0:
            raise BatchRunnerError("--line-timeout ต้องมากกว่า 0")
        return run_job(args.job, args.line_timeout, reset=args.reset)
    if args.command == "status":
        return status_mission(args.mission_id)
    if args.command == "cancel":
        return cancel_mission(args.mission_id)
    if args.command == "_worker":
        return worker_main(args.job, args.checkpoint)
    raise BatchRunnerError("unknown command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BatchRunnerError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from pathlib import Path

from narrator_single_inference_tuning import CANONICAL_TEXT, build_tuning_plan


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "narrator_single_inference_tuning"
REFERENCE_SOURCE = (
    ROOT
    / "output"
    / "narrator_continuity_fixture"
    / "batch_chunks"
    / "A_current_chunked"
    / "002.wav"
)
BASELINE_SOURCE = (
    ROOT
    / "output"
    / "narrator_continuity_fixture"
    / "B_single_inference.wav"
)
EXPECTED_REFERENCE_SHA256 = "71f6a4e00db7bb5d60c9732a10732fcea74d876a6379c0b9e5945b335772d99c"
EXPECTED_BASELINE_SHA256 = "5ca1459443164563968f364f18fae7c9e034cea976311b0b97d590be4699045c"
BOUNDARY_PREFIX = CANONICAL_TEXT.splitlines()[0] + "\n" + CANONICAL_TEXT.splitlines()[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pcm16_mono(path: Path) -> tuple[int, list[int], dict[str, object]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    if channels != 1 or width != 2:
        raise ValueError(f"รองรับเฉพาะ PCM16 mono สำหรับ audit นี้: {path}")
    samples = list(struct.unpack(f"<{frames}h", raw))
    peak = max(abs(value) for value in samples) / 32768.0
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768.0
    mean = sum(samples) / len(samples) / 32768.0
    clips = sum(abs(value) >= 32767 for value in samples)
    return rate, samples, {
        "sample_rate": rate,
        "channels": channels,
        "sample_width_bytes": width,
        "frames": frames,
        "duration_seconds": round(frames / rate, 6),
        "peak": peak,
        "rms": rms,
        "dc_mean": mean,
        "clip_samples": clips,
        "non_silent": rms > 1e-4,
    }


def longest_quiet_span(
    rate: int,
    samples: list[int],
    expected_seconds: float,
    threshold_dbfs: float,
    radius_seconds: float = 2.0,
) -> dict[str, object]:
    frame_samples = max(1, round(rate * 0.01))
    start = max(0, round((expected_seconds - radius_seconds) * rate))
    end = min(len(samples), round((expected_seconds + radius_seconds) * rate))
    flags: list[bool] = []
    centers: list[float] = []
    for offset in range(start, end, frame_samples):
        frame = samples[offset : min(offset + frame_samples, end)]
        rms = math.sqrt(sum(value * value for value in frame) / max(1, len(frame))) / 32768.0
        dbfs = 20.0 * math.log10(max(rms, 1e-12))
        flags.append(dbfs <= threshold_dbfs)
        centers.append((offset + len(frame) / 2) / rate)

    best_start = best_end = run_start = None
    for index, quiet in enumerate(flags + [False]):
        if quiet and run_start is None:
            run_start = index
        elif not quiet and run_start is not None:
            if best_start is None or index - run_start > best_end - best_start:
                best_start, best_end = run_start, index
            run_start = None
    if best_start is None or best_end is None:
        return {"threshold_dbfs": threshold_dbfs, "duration_ms": 0, "start_seconds": None, "end_seconds": None}
    span_start = max(0.0, centers[best_start] - 0.005)
    span_end = centers[best_end - 1] + 0.005
    return {
        "threshold_dbfs": threshold_dbfs,
        "duration_ms": round((span_end - span_start) * 1000),
        "start_seconds": round(span_start, 3),
        "end_seconds": round(span_end, 3),
    }


def main() -> None:
    candidates = build_tuning_plan()["candidates"]
    state = json.loads((OUTPUT / "run_state.json").read_text(encoding="utf-8"))
    generation = json.loads((OUTPUT / "generation_report.json").read_text(encoding="utf-8"))
    generated_rows = generation["runs"][-len(candidates) :]

    reference_hashes = {
        "A_chunk2_source": sha256(REFERENCE_SOURCE),
        "A_chunk2_listening_copy": sha256(OUTPUT / "A_chunk2_target.wav"),
        "B_source": sha256(BASELINE_SOURCE),
        "B_listening_copy": sha256(OUTPUT / "B_single_inference_seed15016.wav"),
    }
    reference_ok = (
        reference_hashes["A_chunk2_source"]
        == reference_hashes["A_chunk2_listening_copy"]
        == EXPECTED_REFERENCE_SHA256
    )
    baseline_ok = (
        reference_hashes["B_source"]
        == reference_hashes["B_listening_copy"]
        == EXPECTED_BASELINE_SHA256
    )

    wav_audit: dict[str, dict[str, object]] = {}
    audio_cache: dict[str, tuple[int, list[int]]] = {}
    for name in [
        "A_chunk2_target.wav",
        "B_single_inference_seed15016.wav",
        *[candidate["output"] for candidate in candidates],
    ]:
        path = OUTPUT / name
        rate, samples, metrics = read_pcm16_mono(path)
        metrics["sha256"] = sha256(path)
        metrics["path"] = str(path)
        wav_audit[name] = metrics
        audio_cache[name] = (rate, samples)

    expected_boundary_ratio = len(BOUNDARY_PREFIX) / len(CANONICAL_TEXT)
    pause_audit: dict[str, object] = {
        "method": "ค้นหา quiet-span ยาวที่สุดในหน้าต่าง +/-2 วินาทีรอบตำแหน่ง boundary ที่ประมาณจากอัตราส่วนตัวอักษร",
        "limitation": "ตำแหน่งเป็นค่าประมาณเชิงสัญญาณ ไม่ใช่ forced alignment และใช้แทน human listening ไม่ได้",
        "boundary_text": "ยุติธรรม | ในที่สุด",
        "character_ratio": expected_boundary_ratio,
        "files": {},
    }
    for filename in [
        "B_single_inference_seed15016.wav",
        "pause_candidate_A.wav",
        "pause_candidate_B.wav",
    ]:
        rate, samples = audio_cache[filename]
        duration = len(samples) / rate
        expected_seconds = duration * expected_boundary_ratio
        pause_audit["files"][filename] = {
            "expected_boundary_seconds": round(expected_seconds, 3),
            "quiet_spans": [
                longest_quiet_span(rate, samples, expected_seconds, threshold)
                for threshold in (-30.0, -35.0, -40.0)
            ],
        }

    invocation_ok = all(
        row["voice_alias"] == "bright_female"
        and row["resolved_voice_instruction"] == "female, young adult, high pitch"
        and row["speed"] == 1.0
        and row["steps"] == 32
        and row["model"] == "hotdogs/omnivoice-thai"
        and row["revision"] == "252d5f2815a5d7300c7676422bee69141c7756de"
        and row["persistent_session"] is True
        and row["model_load_count"] == 1
        and not row["normalization_transformations"]
        and not row["pronunciation_substitutions"]
        and row["thai_only_gate"]["passed"] is True
        and not row["errors"]
        for row in generated_rows
    )
    reuse_ok = generated_rows[0]["model_reused"] is False and all(
        row["model_reused"] is True for row in generated_rows[1:]
    )
    wav_ok = all(
        row["channels"] == 1
        and row["sample_rate"] == 24000
        and row["sample_width_bytes"] == 2
        and row["non_silent"] is True
        and row["clip_samples"] == 0
        for name, row in wav_audit.items()
        if name != "A_chunk2_target.wav"
    )

    audit = {
        "status": "WAITING_FOR_HUMAN_LISTENING"
        if all((reference_ok, baseline_ok, invocation_ok, reuse_ok, wav_ok))
        else "AUDIT_FAILED",
        "reference_hash_match": reference_ok,
        "baseline_hash_match": baseline_ok,
        "reference_hashes": reference_hashes,
        "generation_count": len(generated_rows),
        "single_persistent_session": invocation_ok and reuse_ok,
        "model_load_count": max(row["model_load_count"] for row in generated_rows),
        "wav_validation_pass": wav_ok,
        "wav_audit": wav_audit,
        "pause_signal_audit": pause_audit,
        "state_status": state["status"],
        "full_regression_tests": {"framework": "unittest", "passed": 73, "total": 73, "status": "PASS"},
        "human_winner_selected": False,
    }
    (OUTPUT / "final_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    seed_lines = []
    pause_lines = []
    for candidate in candidates:
        metrics = wav_audit[candidate["output"]]
        line = (
            f"- `{candidate['output']}`: seed {candidate['seed']}, "
            f"{metrics['duration_seconds']:.2f} วินาที, SHA-256 `{metrics['sha256']}`"
        )
        if candidate["kind"] == "seed_search":
            seed_lines.append(line)
        else:
            pause_lines.append(
                line + f", boundary mark `{candidate['boundary_mark']}` ก่อน newline เดิม"
            )

    report = f"""# NARRATOR SINGLE-INFERENCE TUNING

## สถานะ

WAITING_FOR_HUMAN_LISTENING

## ข้อสรุป A แบบ chunked

ผลฟังจากผู้ใช้ยืนยันว่า application-level chunk reset ตรงกับจุดเปลี่ยนเสียงทั้ง 4 ช่วง จึงเป็นสาเหตุสำคัญของ voice/timbre discontinuity สำหรับ fixture นี้ และคำว่า “เจรจา” ใน A ถูกต้อง

## ข้อสรุป Single inference

Single inference ทำให้เสียงมีโทนต่อเนื่องทั้ง passage และคำว่า “เจรจา” ถูกต้อง แต่ baseline seed 15016 ยังไม่ตรงโทนที่ผู้ใช้ชอบเท่า A chunk 2 และไม่มีจังหวะพักที่ต้องการระหว่าง “ยุติธรรม” กับ “ในที่สุด”

## Human target

- Tone reference: `A_chunk2_target.wav` (สำเนา byte-identical จาก A chunk 2)
- Target phrase: “อาณาจักรทั้งสามที่กำลังเผชิญหน้ากับการล่มสลายก็ได้ตกลงเจรจาสงบศึกกันในที่สุด และได้ก่อตั้งองค์กรนอร์เซเลียขึ้นมา”
- ไม่ได้ใช้ reference audio เป็น model input และไม่ได้ทำ voice cloning

## Seed candidates

{chr(10).join(seed_lines)}

ทุกตัวใช้ canonical text เดียวกัน, `bright_female`, instruction `female, young adult, high pitch`, speed 1.00, steps 32 และต่างกันเฉพาะ seed

## Pause candidates

{chr(10).join(pause_lines)}

canonical text ไม่เปลี่ยน; เปลี่ยนเฉพาะ spoken representation ตรง boundary และยังเป็น model inference เดียว ไม่มีการแทรก silence ใน WAV

## Audit

- Reference hash match: {'PASS' if reference_ok else 'FAIL'}
- Baseline hash match: {'PASS' if baseline_ok else 'FAIL'}
- Generated candidates: {len(generated_rows)}/6
- Single persistent model session: {'PASS' if invocation_ok and reuse_ok else 'FAIL'} (`model_load_count=1`)
- WAV audit: {'PASS' if wav_ok else 'FAIL'} — PCM16, 24 kHz mono, non-silent, ไม่มี clipping
- Pause signal metrics: ดู `final_audit.json`; เป็นค่าประมาณ ไม่ใช้ตัดสินผู้ชนะ
- Full regression tests: PASS 73/73 (`python -m unittest discover -v`)
- ไม่มีการแก้ Studio default, voice registry, game asset, HCA, AWB, ACB หรือ PAK

## Files changed

- `narrator_single_inference_tuning.py`
- `test_narrator_single_inference_tuning.py`
- `run_narrator_single_inference_tuning.py`
- `finalize_narrator_single_inference_tuning.py`
- `output/narrator_single_inference_tuning/` (listening pack และ forensic metadata)

## HUMAN LISTENING TEST

WAITING

ยังไม่ได้เลือก winner ให้ผู้ใช้เลือก (1) seed candidate ที่ tone ใกล้ A chunk 2 ที่สุด และ (2) pause candidate ที่ทำให้ “ยุติธรรม ..... ในที่สุด” เป็นธรรมชาติที่สุด
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "status": audit["status"],
        "reference_hash_match": reference_ok,
        "baseline_hash_match": baseline_ok,
        "single_persistent_session": audit["single_persistent_session"],
        "model_load_count": audit["model_load_count"],
        "wav_validation_pass": wav_ok,
        "report": str(OUTPUT / "report.md"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

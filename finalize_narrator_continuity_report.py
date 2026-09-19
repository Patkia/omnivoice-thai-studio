#!/usr/bin/env python3
"""Append measured A/B diagnostics and test evidence to the forensic report."""
from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "narrator_continuity_fixture"
REPORT = OUTPUT / "forensic_report.json"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    a = report["candidates"]["A_current_chunked"]["audio"]
    b = report["candidates"]["B_single_inference"]["audio"]
    report["target_word_pause_diagnostic"]["multi_threshold_local_analysis"] = {
        "alignment_warning": "ช่วงเวลาอิง duration-estimator จึงเป็นตำแหน่งประมาณ ไม่ใช่ forced alignment",
        "A_chunk_2_approx_word_window_seconds": [4.45, 4.979],
        "A_low_energy_regions_near_window": {
            "below_-25_dbfs_min_40ms": [[4.44, 4.50, 60], [4.74, 4.82, 80], [4.95, 5.04, 90]],
            "below_-30_dbfs_min_40ms": [[4.45, 4.49, 40], [4.75, 4.80, 50], [4.95, 5.01, 60]],
            "below_-40_dbfs_min_40ms": [[4.75, 4.79, 40]],
            "below_-42_dbfs_min_80ms": [],
        },
        "B_approx_word_window_seconds": [7.316, 7.853],
        "B_low_energy_regions_near_window": {
            "below_-25_dbfs_min_40ms": [[7.12, 7.19, 70], [7.25, 7.34, 90], [7.55, 7.62, 70], [7.82, 7.91, 90]],
            "below_-30_dbfs_min_40ms": [],
            "below_-42_dbfs_min_80ms": [],
        },
        "measured_conclusion": (
            "A ไม่มี digital silence ยาว >=80 ms ที่ต่ำกว่า -42 dBFS ในหน้าต่างประมาณของคำ; "
            "มีเพียง low-energy micro-gaps 40-60 ms ที่เกณฑ์ -30 dBFS. B ไม่มี gap ต่ำกว่า -30 dBFS ใกล้หน้าต่างประมาณ. "
            "ดังนั้นหลักฐานไม่รองรับ chunk/merge pause ภายในคำ และสอดคล้องกับ model prosody/articulation"
        ),
    }
    report["audio_comparison"] = {
        "A_duration_seconds": a["duration_seconds"],
        "B_duration_seconds": b["duration_seconds"],
        "A_dc_mean": a["dc_mean"],
        "B_dc_mean": b["dc_mean"],
        "A_abs_dc_to_rms_ratio": abs(a["dc_mean"]) / a["rms"],
        "B_abs_dc_to_rms_ratio": abs(b["dc_mean"]) / b["rms"],
        "B_dc_level_dbfs": 20 * math.log10(abs(b["dc_mean"])),
        "clipping": {"A": a["clip_samples"], "B": b["clip_samples"]},
        "warning": (
            "B สร้างสำเร็จและไม่ clip แต่มี DC mean -0.04136 (ประมาณ -27.67 dBFS; 34.1% ของ RMS) "
            "ซึ่งสูงกว่า A มาก ต้องให้ผู้ใช้ฟังก่อนตัดสินและห้ามประกาศ winner"
        ),
    }
    report["tests"] = {
        "relevant": {"command": "python -m unittest -v test_narrator_continuity_fixture test_semantic_chunking test_studio_engine_adapter", "result": "PASS", "count": 16},
        "full_suite": {"command": "python -m unittest discover -v", "result": "PASS", "count": 70},
        "dependency_note": "รอบแรก 57 tests ผ่านและ 2 modules import ไม่ได้เพราะ .venv-recovered ขาด PySide6; ติดตั้ง PySide6 6.11.2 ตาม requirements เดิม แล้ว full suite ผ่าน 70/70",
    }
    report["files_changed"] = [
        "narrator_continuity_fixture.py (new)",
        "test_narrator_continuity_fixture.py (new)",
        "run_narrator_continuity_forensics.py (new)",
        "finalize_narrator_continuity_report.py (new)",
        "output/narrator_continuity_fixture/ (new controlled artifacts)",
        ".venv-recovered: installed PySide6 6.11.2 required by existing test suite",
    ]
    report["recommendation"] = {
        "next_gate": "HUMAN LISTENING TEST",
        "listen_for": [
            "ความต่อเนื่องของ timbre/tone/prosody ตลอด A เทียบ B",
            "การออกเสียงและจังหวะภายในคำว่า เจรจา",
            "ความสม่ำเสมอกับช่วง และได้ก่อตั้งองค์กรนอร์เซเลียขึ้นมา",
            "เสียงผิดปกติหรือ low-frequency offset ใน B ตาม DC-bias warning",
        ],
        "candidate_C_generated": False,
        "reason_C_not_generated": "B ผ่าน model/runtime single-inference path; Phase 5 จึงยังไม่เข้าเงื่อนไข",
        "winner_selected": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

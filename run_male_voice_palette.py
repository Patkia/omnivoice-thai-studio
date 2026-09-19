from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from studio_engine_adapter import StudioEngineAdapter
from studio_generation import generate_studio_request

CANDIDATES_PATH = ROOT / "male_voice_candidates.json"
OUT_DIR = ROOT / "output" / "male_voice_palette"
MANIFEST_PATH = OUT_DIR / "manifest.json"
HTML_PATH = OUT_DIR / "index.html"

TEXT = "ยินดีที่ได้พบ ข้าหวังว่าเราจะร่วมเดินทางไปด้วยกันได้"
STEPS = 32
BASE_SEED = 26000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int)
    return p.parse_args()


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        return {
            "duration_sec": round(w.getnframes() / w.getframerate(), 3),
            "sample_rate": w.getframerate(),
            "channels": w.getnchannels(),
            "sample_width": w.getsampwidth(),
        }


def load_cases() -> list[dict]:
    data = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    cases = []
    for group, items in data.items():
        for item in items:
            cases.append({**item, "group": group})
    return cases


def build_outputs(cases: list[dict]) -> list[dict]:
    rows = []
    for idx, item in enumerate(cases, start=1):
        wav = OUT_DIR / f"{item['id']}.wav"
        if not wav.exists():
            continue
        info = wav_info(wav)
        rows.append({
            **item,
            "seed": BASE_SEED + idx,
            "text": TEXT,
            "steps": STEPS,
            "file_name": wav.name,
            "relative_path": str(wav.relative_to(ROOT)).replace("\\", "/"),
            "absolute_path": str(wav),
            "sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
            **info,
        })
    return rows


def write_manifest_and_html(cases: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_outputs(cases)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "thai_first_generic_male_voice_palette_no_reference_conditioning",
        "comparison_text": TEXT,
        "runtime_supported_controls": ["gender", "age", "pitch", "speed"],
        "note": "character_hint is a human selection hint only; it is not passed to OmniVoice as an unsupported style tag.",
        "source_project": str(ROOT),
        "candidate_config": str(CANDIDATES_PATH),
        "count": len(rows),
        "voices": rows,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cards = []
    for row in rows:
        cards.append(
            "<section class='card'>"
            f"<h2>{html.escape(row['id'])} — {html.escape(row['label'])}</h2>"
            f"<p><b>แนวตัวละคร:</b> {html.escape(row['character_hint'])}</p>"
            f"<p><b>Engine controls:</b> {html.escape(row['instruction'])} · speed {row['speed']:.2f}</p>"
            f"<audio controls preload='none' src='{html.escape(row['file_name'])}'></audio>"
            f"<p class='path'><b>Original path:</b> {html.escape(row['absolute_path'])}</p>"
            f"<p class='meta'>duration {row['duration_sec']:.2f}s · {row['sample_rate']} Hz · SHA256 {row['sha256']}</p>"
            "</section>"
        )

    page = """<!doctype html>
<meta charset='utf-8'>
<title>OmniVoice Thai Male Voice Palette</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:28px auto;padding:0 18px;background:#f4f6f8;color:#202124}
h1{margin-bottom:6px}.lead{background:#fff7d6;padding:14px 16px;border-radius:12px;line-height:1.5}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px;margin-top:18px}
.card{background:white;border-radius:14px;padding:16px;box-shadow:0 1px 5px #d7dce1}.card h2{font-size:18px;margin:0 0 8px}
audio{width:100%;margin:8px 0}.path{font-family:Consolas,monospace;font-size:12px;word-break:break-all;background:#f6f7f8;padding:8px;border-radius:7px}
.meta{font-size:11px;color:#666;word-break:break-all}
</style>
<h1>Thai Male Voice Palette</h1>
<p class='lead'>ทุกเสียงใช้ข้อความไทยเดียวกันและไม่มี reference conditioning เพื่อให้เปรียบเทียบตัวเสียงได้ตรง ๆ<br>
คำว่า “แนวตัวละคร” เป็นเพียงคำแนะนำสำหรับการฟัง ไม่ได้ถูกส่งเข้าโมเดลเป็น style tag</p>
<div class='grid'>""" + "".join(cards) + "</div>"
    HTML_PATH.write_text(page, encoding="utf-8")


def main() -> int:
    args = parse_args()
    cases = load_cases()
    selected = cases[args.start:args.end]
    if not selected:
        raise SystemExit("Selected batch is empty")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    for global_idx, item in enumerate(cases, start=1):
        if item not in selected:
            continue
        out = OUT_DIR / f"{item['id']}.wav"
        if out.exists():
            print(f"SKIP {item['id']}")
            continue
        started = time.perf_counter()
        generate_studio_request(
            adapter,
            TEXT,
            "young_male",
            item["speed"],
            STEPS,
            out,
            True,
            seed=BASE_SEED + global_idx,
            instruction_override=item["instruction"],
            reference_conditioning=False,
        )
        print(f"DONE {item['id']} {time.perf_counter()-started:.1f}s")
    write_manifest_and_html(cases)
    print(f"READY {HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

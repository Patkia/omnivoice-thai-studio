from __future__ import annotations

import csv
import hashlib
import html
import wave
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
SRC_DIR = TRIANGLE / "work/extended_voice_candidates/thai_candidates"
SRC_MANIFEST = SRC_DIR / "extended_voice_candidates.csv"
OUT = TRIANGLE / "work/extended_voice_candidates/prosody_fix_tests"
REF_DIR = ROOT / "assets/triangle-strategy/approved_voice_references/runtime_extended_prosody_tests"
MANIFEST = OUT / "prosody_fix_tests.csv"
HTML = OUT / "prosody_fix_tests.html"

CASES = {
    ("SLV", "A"): {
        "fix": "นครหลวงถูกโจมตีอย่างนั้นหรือ ฝีมือใครกันแน่",
        "tests": [
            "ข้าจะจัดการเรื่องนี้เอง เจ้าไม่จำเป็นต้องกังวล",
            "หากทุกอย่างเป็นไปตามแผน พรุ่งนี้เราจะเดินทางต่อทันที",
            "ข้าเข้าใจสถานการณ์แล้ว ต่อจากนี้ปล่อยให้เป็นหน้าที่ของข้า",
        ],
    },
    ("JUL", "C"): {
        "fix": "ขอบคุณที่มาพบข้าขอรับ ข้ามีนามว่ายูลิโอ้ และข้ามีเรื่องสำคัญจะเรียนให้ท่านทราบ",
        "tests": [
            "ข้าได้ตรวจสอบเอกสารทั้งหมดเรียบร้อยแล้วขอรับ",
            "เรื่องนี้จำเป็นต้องพิจารณาอย่างรอบคอบ ก่อนที่เราจะตัดสินใจ",
            "หากท่านเห็นชอบ ข้าจะดำเนินการตามแผนทันที",
        ],
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def read_rows() -> list[dict]:
    with SRC_MANIFEST.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_outputs(rows: list[dict]) -> None:
    fields = [
        "voice", "test_id", "text", "source_wav", "source_text", "speed", "seed",
        "output_wav", "sha256", "duration_sec", "cache_hit", "inference_seconds",
    ]
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

    by_voice: dict[str, list[dict]] = {}
    for r in rows:
        by_voice.setdefault(r["voice"], []).append(r)
    parts = [
        '<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>SLV_A / JUL_C Prosody Fix Tests</title>',
        '<style>body{font-family:Segoe UI,Tahoma,Arial,sans-serif;background:#f6f7f9;color:#222;margin:24px;line-height:1.5}.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:18px;margin-bottom:18px}.item{border-top:1px solid #eee;padding-top:12px;margin-top:12px}.meta{color:#666;font-size:13px}audio{width:100%;max-width:900px}</style></head><body>',
        '<h1>Prosody Fix Tests — SLV_A / JUL_C</h1>',
        '<p>FIX = ปรับข้อความเพื่อหลีกเลี่ยงปลายประโยคพุ่งสูงผิดธรรมชาติ; TEST 01-03 = ประโยคใหม่เพื่อเช็กว่าอาการเกิดเฉพาะประโยคเดิมหรือเกิดกับ voice identity ด้วย</p>'
    ]
    for voice, items in by_voice.items():
        parts.append(f'<div class="card"><h2>{html.escape(voice)}</h2>')
        for r in items:
            rel = Path(r["output_wav"]).name
            parts.append('<div class="item">')
            parts.append(f'<h3>{html.escape(r["test_id"])}</h3><div>{html.escape(r["text"])}</div>')
            parts.append(f'<div class="meta">speed={html.escape(r["speed"])} · seed={html.escape(r["seed"])}</div>')
            parts.append(f'<audio controls preload="none" src="{html.escape(rel)}"></audio></div>')
        parts.append('</div>')
    parts.append('</body></html>')
    HTML.write_text(''.join(parts), encoding="utf-8")


def main() -> int:
    rows = read_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    REF_DIR.mkdir(parents=True, exist_ok=True)
    adapter = StudioEngineAdapter()
    results: list[dict] = []

    for (code, cand), spec in CASES.items():
        base = next(r for r in rows if r["user_code"] == code and r["candidate"] == cand)
        source = SRC_DIR / f"{code}_{cand}.wav"
        if not source.is_file():
            raise FileNotFoundError(source)
        ref = REF_DIR / source.name
        ref.write_bytes(source.read_bytes())
        ref_sha = sha256(ref)
        ref_text = base["thai_text"]
        ref_text_sha = hashlib.sha256(ref_text.encode("utf-8")).hexdigest()
        speed = float(base["speed"])
        seed = int(base["seed"])
        items = [("FIX", spec["fix"])] + [(f"TEST_{i:02d}", t) for i, t in enumerate(spec["tests"], 1)]
        for test_id, text in items:
            output = OUT / f"{code}_{cand}_{test_id}.wav"
            result = adapter.generate(
                text,
                "narrator",
                speed,
                32,
                output,
                force=False,
                seed=seed,
                generation_mode="reference_first",
                language="Thai",
                denoise=True,
                postprocess_output=True,
                voice_project="triangle-strategy",
                reference_conditioning=True,
                reference_audio=str(ref.relative_to(ROOT)),
                reference_sha256=ref_sha,
                reference_text=ref_text,
                reference_text_sha256=ref_text_sha,
            )
            row = {
                "voice": f"{code}_{cand}",
                "test_id": test_id,
                "text": text,
                "source_wav": str(source),
                "source_text": ref_text,
                "speed": f"{speed:.2f}",
                "seed": str(seed),
                "output_wav": str(output),
                "sha256": sha256(output),
                "duration_sec": f"{wav_duration(output):.3f}",
                "cache_hit": str(bool(result.get("cache_hit"))).upper(),
                "inference_seconds": f"{float(result.get('inference_seconds', 0.0)):.3f}",
            }
            results.append(row)
            write_outputs(results)
            print(f"DONE {code}_{cand}_{test_id} cache={row['cache_hit']} sec={row['inference_seconds']} path={output}")

    print(f"MANIFEST={MANIFEST}")
    print(f"HTML={HTML}")
    print(f"OUTPUTS={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

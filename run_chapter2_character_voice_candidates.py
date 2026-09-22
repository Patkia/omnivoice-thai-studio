from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
APPROVED = TRIANGLE / "work/chapter2_voice_mapping/chapter2_voice_references/chapter2_human_approved_references.csv"
OUT = TRIANGLE / "work/chapter2_voice_mapping/chapter2_thai_voice_candidates"
MANIFEST = OUT / "chapter2_thai_voice_candidates.csv"
HTML = OUT / "chapter2_thai_voice_candidates.html"

# Three intentionally close but distinct age/pitch candidates per character.
# OmniVoice supports gender + age + pitch; speed/seed provide controlled variation.
VOICE_SPECS = {
    "DRG": {
        "name": "ดราแกน", "age_note": "young adult (~mid-20s)",
        "variants": [
            ("A", "male, young adult, moderate pitch", 1.02, 33201),
            ("B", "male, young adult, high pitch", 1.00, 33202),
            ("C", "male, young adult, low pitch", 0.98, 33203),
        ],
    },
    "LGN": {
        "name": "เร็กน่า", "age_note": "elderly king (~60s)",
        "variants": [
            ("A", "male, elderly, moderate pitch", 0.90, 33301),
            ("B", "male, elderly, low pitch", 0.88, 33302),
            ("C", "male, elderly, very low pitch", 0.86, 33303),
        ],
    },
    "LYL": {
        "name": "ไลล่า", "age_note": "mature adult (~mid-30s)",
        "variants": [
            ("A", "female, middle-aged, moderate pitch", 0.98, 33401),
            ("B", "female, middle-aged, low pitch", 0.96, 33402),
            ("C", "female, young adult, low pitch", 0.99, 33403),
        ],
    },
    "MAX": {
        "name": "แม็กซ์เวลล์", "age_note": "mature veteran (~50s)",
        "variants": [
            ("A", "male, middle-aged, low pitch", 0.92, 33501),
            ("B", "male, middle-aged, very low pitch", 0.90, 33502),
            ("C", "male, elderly, low pitch", 0.90, 33503),
        ],
    },
    "EGS": {
        "name": "เอกซ์เฮม", "age_note": "young adult (~20s)",
        "variants": [
            ("A", "male, young adult, moderate pitch", 1.00, 33601),
            ("B", "male, young adult, low pitch", 0.98, 33602),
            ("C", "male, young adult, high pitch", 1.02, 33603),
        ],
    },
    "SLS": {
        "name": "ซอสเลย์", "age_note": "older adult (~50s-60s)",
        "variants": [
            ("A", "male, middle-aged, moderate pitch", 0.94, 33701),
            ("B", "male, middle-aged, low pitch", 0.92, 33702),
            ("C", "male, elderly, moderate pitch", 0.91, 33703),
        ],
    },
    "TRS": {
        "name": "ธาลาส", "age_note": "young adult (~20s)",
        "variants": [
            ("A", "male, young adult, moderate pitch", 1.02, 33801),
            ("B", "male, young adult, high pitch", 1.03, 33802),
            ("C", "male, young adult, low pitch", 1.00, 33803),
        ],
    },
    "ABR": {
        "name": "อัฟโลร่า", "age_note": "adult warrior (~late-20s/30s)",
        "variants": [
            ("A", "female, young adult, low pitch", 0.97, 33901),
            ("B", "female, middle-aged, low pitch", 0.96, 33902),
            ("C", "female, young adult, moderate pitch", 0.98, 33903),
        ],
    },
    "CRD": {
        "name": "คอร์เดเลีย", "age_note": "teenage princess (~16-17)",
        "variants": [
            ("A", "female, teenager, moderate pitch", 1.02, 34001),
            ("B", "female, teenager, high pitch", 1.01, 34002),
            ("C", "female, young adult, high pitch", 1.00, 34003),
        ],
    },
    "ERK": {
        "name": "เอริก้า", "age_note": "young adult (~early-20s)",
        "variants": [
            ("A", "female, young adult, moderate pitch", 1.02, 34101),
            ("B", "female, young adult, high pitch", 1.02, 34102),
            ("C", "female, young adult, low pitch", 1.00, 34103),
        ],
    },
}


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = text.replace("…", "...")
    return " ".join(text.split()).strip()


def build_html(rows: list[dict]) -> None:
    by_code: dict[str, list[dict]] = {}
    for row in rows:
        by_code.setdefault(row["speaker_code"], []).append(row)
    parts = [
        '<!doctype html><html lang="th"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Chapter 2 Thai Voice Candidates</title>',
        '<style>body{font-family:Segoe UI,Tahoma,Arial,sans-serif;margin:24px;background:#f6f7f9;color:#222;line-height:1.5}',
        '.top,.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:18px;margin-bottom:18px}',
        '.cand{border-top:1px solid #eee;padding-top:14px;margin-top:14px}.meta{color:#666;font-size:13px}',
        '.badge{display:inline-block;background:#eef3ff;padding:3px 9px;border-radius:12px;font-size:12px;margin-left:6px}',
        '.age{background:#e8f5e9}.thai{font-size:16px;margin:8px 0}.ref{background:#fff8e1;padding:10px;border-radius:8px;margin-top:10px}',
        'audio{width:100%;max-width:850px;margin-top:8px}h1{margin-top:0}h2{margin-bottom:4px}</style></head><body>',
        '<div class="top"><h1>Chapter 2 — Thai Voice Candidates</h1>',
        '<p>10 ตัวละคร × 3 เสียงทดลอง ใช้บทไทยเดียวกันในแต่ละตัวละครเพื่อฟังเทียบ timbre/วัย/pitch อย่างแฟร์</p>',
        '<p>ยังไม่มีเสียงใดถูกเลือกเป็น production voice target</p></div>',
    ]
    for code in VOICE_SPECS:
        cand = sorted(by_code.get(code, []), key=lambda r: r["candidate"])
        if not cand:
            continue
        first = cand[0]
        parts.append('<div class="card">')
        parts.append(f'<h2>{html.escape(first["character_name"])} <span class="badge">{code}</span><span class="badge age">{html.escape(first["age_note"])}</span></h2>')
        parts.append(f'<div class="thai"><b>ข้อความทดสอบ:</b> {html.escape(first["thai_text"])}</div>')
        for row in cand:
            rel = Path(row["output_wav"]).name
            parts.append('<div class="cand">')
            parts.append(f'<h3>Candidate {html.escape(row["candidate"])}</h3>')
            parts.append(f'<div class="meta">{html.escape(row["instruction"])} · speed={html.escape(row["speed"])} · seed={html.escape(row["seed"])}</div>')
            parts.append(f'<audio controls preload="none" src="{html.escape(rel)}"></audio>')
            parts.append('</div>')
        parts.append('</div>')
    parts.append('</body></html>')
    HTML.write_text("".join(parts), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", default=",".join(VOICE_SPECS), help="comma-separated character codes")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="backslashreplace")

    approved_rows = read_csv(APPROVED)
    approved_by_code = {row["speaker_code"]: row for row in approved_rows}
    missing = [code for code in VOICE_SPECS if code not in approved_by_code]
    if missing:
        raise RuntimeError(f"Missing approved reference rows: {missing}")

    requested = [c.strip().upper() for c in args.codes.split(",") if c.strip()]
    unknown = [c for c in requested if c not in VOICE_SPECS]
    if unknown:
        raise RuntimeError(f"Unknown codes: {unknown}")

    OUT.mkdir(parents=True, exist_ok=True)
    existing = []
    if MANIFEST.exists():
        existing = read_csv(MANIFEST)
    keep = [r for r in existing if r.get("speaker_code") not in requested]

    adapter = StudioEngineAdapter()
    rows = list(keep)
    for code in requested:
        spec = VOICE_SPECS[code]
        approved = approved_by_code[code]
        thai_text = clean_text(approved.get("thai_text", ""))
        if not thai_text:
            raise RuntimeError(f"Blank Thai text for {code}")
        for label, instruction, speed, seed in spec["variants"]:
            output = OUT / f"{code}_{label}.wav"
            result = adapter.generate(
                thai_text,
                "narrator",
                speed,
                32,
                output,
                force=args.force,
                seed=seed,
                instruct_override=instruction,
                generation_mode="voice_design",
            )
            rows.append({
                "speaker_code": code,
                "character_name": spec["name"],
                "age_note": spec["age_note"],
                "candidate": label,
                "instruction": instruction,
                "speed": f"{speed:.2f}",
                "seed": str(seed),
                "thai_text": thai_text,
                "source_reference_wav": approved.get("candidate_wav", approved.get("approved_reference", "")),
                "source_reference_self_id": approved.get("self_id", ""),
                "output_wav": str(output),
                "cache_hit": str(bool(result.get("cache_hit"))).upper(),
                "inference_seconds": f"{float(result.get('inference_seconds', 0.0)):.3f}",
                "selected": "",
            })
            print(f"DONE {code}_{label} cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f}")

    fields = [
        "speaker_code", "character_name", "age_note", "candidate", "instruction", "speed", "seed",
        "thai_text", "source_reference_wav", "source_reference_self_id", "output_wav", "cache_hit",
        "inference_seconds", "selected",
    ]
    rows.sort(key=lambda r: (list(VOICE_SPECS).index(r["speaker_code"]), r["candidate"]))
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    build_html(rows)
    print(json.dumps({
        "requested_codes": requested,
        "total_manifest_rows": len(rows),
        "output_dir": str(OUT),
        "manifest": str(MANIFEST),
        "html": str(HTML),
        "model_load_count": adapter.session.model_load_count,
        "reference_audio_used_as_model_input": False,
        "production_voice_targets_modified": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

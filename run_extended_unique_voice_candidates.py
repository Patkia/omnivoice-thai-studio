from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

from studio_engine_adapter import StudioEngineAdapter

ROOT = Path(__file__).resolve().parent
TRIANGLE = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice")
PLAN = TRIANGLE / "work/extended_voice_candidates/character_generation_plan.csv"
OUT = TRIANGLE / "work/extended_voice_candidates/thai_candidates"
MANIFEST = OUT / "extended_voice_candidates.csv"
HTML = OUT / "extended_voice_candidates.html"
INVALID_PALETTE = TRIANGLE / "work/extended_voice_candidates/thai_palette_candidates"
OMNI_ASSETS = ROOT / "assets"
OMNI_OUTPUTS = ROOT / "outputs"

FIELDS = [
    "user_code", "speaker_code", "character_name_th", "character_name_en", "gender", "vibe",
    "candidate", "instruction", "speed", "seed", "self_id", "english_text", "thai_text",
    "generation_mode", "english_clone_used", "output_wav", "sha256", "cache_hit", "inference_seconds", "selected",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_manifest(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["user_code"], r["candidate"]))
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def build_html(rows: list[dict]) -> None:
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r["user_code"], []).append(r)
    plan_codes: list[str] = []
    for r in read_csv(PLAN):
        if r["user_code"] not in plan_codes:
            plan_codes.append(r["user_code"])
    parts = [
        '<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Unique Thai Voice Candidates</title><style>',
        'body{font-family:Segoe UI,Tahoma,Arial,sans-serif;background:#f6f7f9;color:#222;margin:24px;line-height:1.5}',
        '.top,.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:18px;margin-bottom:18px}',
        '.cand{border-top:1px solid #eee;margin-top:14px;padding-top:14px}.badge{display:inline-block;background:#eef3ff;border-radius:12px;padding:3px 9px;font-size:12px;margin-left:6px}',
        '.meta{color:#666;font-size:13px}.thai{margin:8px 0}audio{width:100%;max-width:900px;margin-top:8px}h1{margin-top:0}',
        '</style></head><body><div class="top"><h1>Unique Thai Voice Candidates</h1>',
        '<p>Thai-first voice design. Every accepted WAV is SHA256-unique against prior project/OmniVoice WAVs and against this candidate set. English cloning is not used.</p>',
        f'<p>Accepted: <b>{len(rows)}</b> / 93 files</p></div>'
    ]
    for code in plan_codes:
        cand = sorted(by_code.get(code, []), key=lambda r: r["candidate"])
        if not cand:
            continue
        first = cand[0]
        parts.append('<div class="card">')
        parts.append(f'<h2>{html.escape(first["character_name_th"])} / {html.escape(first["character_name_en"])} <span class="badge">{html.escape(code)}</span></h2>')
        parts.append(f'<div class="meta">{html.escape(first["vibe"])}</div>')
        parts.append(f'<div class="thai"><b>ข้อความทดสอบ:</b> {html.escape(first["thai_text"])}</div>')
        for r in cand:
            wav = Path(r["output_wav"]).name
            parts.append('<div class="cand">')
            parts.append(f'<h3>Candidate {html.escape(r["candidate"])}</h3>')
            parts.append(f'<div class="meta">{html.escape(r["instruction"])} · speed={html.escape(r["speed"])} · seed={html.escape(r["seed"])} · sha256={html.escape(r.get("sha256", ""))[:12]}</div>')
            parts.append(f'<audio controls preload="none" src="{html.escape(wav)}"></audio>')
            parts.append('</div>')
        parts.append('</div>')
    parts.append('</body></html>')
    HTML.write_text("".join(parts), encoding="utf-8")


def collect_forbidden_hashes() -> set[str]:
    hashes: set[str] = set()
    roots = [TRIANGLE, OMNI_ASSETS, OMNI_OUTPUTS]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.wav"):
            try:
                rp = p.resolve()
                if OUT.resolve() in rp.parents:
                    continue
                # Invalid palette is deliberately forbidden too, because it is made of old reused voices.
                hashes.add(sha256_file(p))
            except OSError:
                continue
    return hashes


def collect_reserved_seeds() -> set[int]:
    seeds: set[int] = set()
    for root in [TRIANGLE / "work", ROOT]:
        if not root.exists():
            continue
        for p in root.rglob("*.csv"):
            try:
                with p.open("r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames or "seed" not in reader.fieldnames:
                        continue
                    for r in reader:
                        try:
                            seeds.add(int(r.get("seed", "")))
                        except (TypeError, ValueError):
                            pass
            except (OSError, UnicodeError, csv.Error):
                continue
    return seeds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", default="")
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan = read_csv(PLAN)
    if len(plan) != 93:
        raise RuntimeError(f"Expected 93 plan rows, got {len(plan)}")
    requested = {x.strip().upper() for x in args.codes.split(",") if x.strip()}
    if requested:
        unknown = sorted(requested - {r["user_code"] for r in plan})
        if unknown:
            raise RuntimeError(f"Unknown codes: {unknown}")
        plan = [r for r in plan if r["user_code"] in requested]

    OUT.mkdir(parents=True, exist_ok=True)
    existing = read_csv(MANIFEST) if MANIFEST.exists() else []
    manifest_by_key = {(r["user_code"], r["candidate"]): r for r in existing}
    forbidden = collect_forbidden_hashes()
    reserved_seeds = collect_reserved_seeds()

    accepted_hashes: set[str] = set()
    for key, r in list(manifest_by_key.items()):
        p = Path(r.get("output_wav", ""))
        if not p.is_file():
            manifest_by_key.pop(key, None)
            continue
        h = sha256_file(p)
        # Existing custom-generated files may predate the sha256 column. Accept only if unique vs historical WAVs and this set.
        if h in forbidden or h in accepted_hashes:
            print(f"REJECT_EXISTING {key[0]}_{key[1]} duplicate hash={h}")
            manifest_by_key.pop(key, None)
            continue
        r["sha256"] = h
        accepted_hashes.add(h)
        try:
            reserved_seeds.add(int(r.get("seed", "")))
        except ValueError:
            pass

    write_manifest(list(manifest_by_key.values()))
    build_html(list(manifest_by_key.values()))
    adapter = StudioEngineAdapter()

    global_index = {(r["user_code"], r["candidate"]): i for i, r in enumerate(read_csv(PLAN), start=1)}
    for i, row in enumerate(plan, start=1):
        key = (row["user_code"], row["candidate"])
        output = OUT / f'{row["user_code"]}_{row["candidate"]}.wav'
        old = manifest_by_key.get(key)
        if old and output.is_file() and not args.force:
            print(f"SKIP {row['user_code']}_{row['candidate']} verified_unique")
            continue

        base_seed = 60000 + global_index[key] * 20
        attempt = 0
        while True:
            seed = base_seed + attempt
            while seed in reserved_seeds:
                seed += 1
            result = adapter.generate(
                row["thai_text"], "narrator", float(row["speed"]), args.steps, output,
                force=True, seed=seed, instruct_override=row["instruction"], generation_mode="voice_design",
            )
            h = sha256_file(output)
            if h not in forbidden and h not in accepted_hashes:
                break
            print(f"COLLISION {row['user_code']}_{row['candidate']} seed={seed} hash={h}; retry")
            attempt += 1
            if attempt >= 8:
                raise RuntimeError(f"Unable to create unique candidate for {key} after {attempt} attempts")

        reserved_seeds.add(seed)
        accepted_hashes.add(h)
        saved = dict(row)
        saved["seed"] = str(seed)
        saved.update({
            "output_wav": str(output), "sha256": h,
            "cache_hit": str(bool(result.get("cache_hit"))).upper(),
            "inference_seconds": f"{float(result.get('inference_seconds', 0.0)):.3f}", "selected": "",
        })
        manifest_by_key[key] = saved
        rows = list(manifest_by_key.values())
        write_manifest(rows); build_html(rows)
        print(f"DONE {i}/{len(plan)} {row['user_code']}_{row['candidate']} seed={seed} sha={h[:12]} sec={float(result.get('inference_seconds',0.0)):.3f}")

    rows = list(manifest_by_key.values())
    hashes = [r.get("sha256", "") for r in rows]
    if len(rows) == 93 and len(set(hashes)) != 93:
        raise RuntimeError("Final manifest contains duplicate hashes")
    write_manifest(rows); build_html(rows)
    print(json.dumps({
        "accepted_rows": len(rows), "unique_hashes": len(set(hashes)), "manifest": str(MANIFEST),
        "html": str(HTML), "output_dir": str(OUT), "english_clone_used": False,
        "steps": args.steps, "production_targets_modified": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

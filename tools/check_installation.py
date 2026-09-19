"""Read-only-ish second-PC health check; never loads a model or runs inference."""
from __future__ import annotations

import csv
import hashlib
import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "projects" / "triangle-strategy" / "voice_target_map.json"
CSV_PATH = ROOT / "imports" / "chapter1_serenoa_regen.csv"
REFERENCE_SHA256 = "0b54c5e1bd6746e9845080c02c4282664a944683c760285204cbf637e4ccfa6a"


def check_import(name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - environment-dependent
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 10), sys.version.split()[0]))

    for name in ("omnivoice", "numpy", "soundfile", "PySide6", "torch", "torchaudio"):
        ok, detail = check_import(name)
        checks.append((f"import:{name}", ok, detail))

    checks.append(("project_map", MAP_PATH.is_file(), str(MAP_PATH)))
    checks.append(("serenoa_csv", CSV_PATH.is_file(), str(CSV_PATH)))

    reference_audio = None
    reference_sha = None
    if MAP_PATH.is_file():
        try:
            mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
            reference_audio = mapping["targets"]["serenoa"]["reference_conditioning"]["reference_audio"]
            reference_sha = mapping["targets"]["serenoa"]["reference_conditioning"]["reference_sha256"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            checks.append(("project_map_schema", False, f"{type(exc).__name__}: {exc}"))

    if reference_audio:
        reference_path = ROOT / reference_audio
        exists = reference_path.is_file()
        actual = hashlib.sha256(reference_path.read_bytes()).hexdigest() if exists else None
        checks.append(("serenoa_reference_exists", exists, str(reference_path)))
        checks.append(("serenoa_reference_sha256", actual == REFERENCE_SHA256 and reference_sha == REFERENCE_SHA256,
                       actual or "missing"))

    if CSV_PATH.is_file():
        try:
            with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            valid = bool(rows) and all(row.get("voice_project") == "triangle-strategy" and
                                       row.get("voice_target") == "serenoa" for row in rows)
            checks.append(("serenoa_csv_rows", valid, str(len(rows))))
        except (OSError, UnicodeError, csv.Error) as exc:
            checks.append(("serenoa_csv_rows", False, f"{type(exc).__name__}: {exc}"))

    output_dir = ROOT / "output" / "studio" / "triangle-strategy"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".healthcheck-", dir=output_dir, delete=True):
            pass
        checks.append(("output_writable", True, str(output_dir)))
    except OSError as exc:
        checks.append(("output_writable", False, f"{type(exc).__name__}: {exc}"))

    checks.append(("ffmpeg_optional", shutil.which("ffmpeg") is not None, "optional"))
    try:
        import torch
        checks.append(("cuda_optional", True, f"available={torch.cuda.is_available()}"))
    except Exception as exc:  # pragma: no cover - environment-dependent
        checks.append(("cuda_optional", False, f"{type(exc).__name__}: {exc}"))

    for name, ok, detail in checks:
        label = "PASS" if ok else ("INFO" if name.endswith("_optional") else "FAIL")
        print(f"{label} {name}: {detail}")
    required = [ok for name, ok, _ in checks if not name.endswith("_optional") and name != "python"]
    return 0 if all(required) and checks[0][1] else 1


if __name__ == "__main__":
    raise SystemExit(main())

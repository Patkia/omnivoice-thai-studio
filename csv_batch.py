"""CSV import and validation helpers for the generic Studio batch workflow.

This module never invokes TTS.  It keeps CSV metadata available for human review
while allowing only an explicit text field to become a future generation request.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

import tts
from long_text_batch import is_long
from studio_engine_adapter import (preview_single_input_text, preview_text,
                                   validate_reference_audio, validate_reference_text)


REQUIRED_COLUMNS = ("file_name", "thai_text")
DISPLAY_COLUMNS = (
    "character_name", "gender", "role", "voice_target",
    "pronunciation_note", "prosody_note",
)
PENDING = "PENDING"
GENERATING = "GENERATING"
DONE = "DONE"
ERROR = "ERROR"
SKIPPED = "SKIPPED"
ROOT = Path(__file__).resolve().parent
PROJECTS_ROOT = ROOT / "projects"
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
VOICE_DESIGN = "voice_design"
REFERENCE_FIRST = "reference_first"
GENERATION_MODES = frozenset((VOICE_DESIGN, REFERENCE_FIRST))


@dataclass(frozen=True)
class ResolvedGenerationConfig:
    """The complete non-text generation request for one CSV row."""

    voice_project: str
    voice_target: str
    profile_alias: str
    generation_mode: str
    instruction: str | None
    instruction_override: str | None
    speed: float
    steps: int
    seed: int | None
    reference_conditioning: bool
    reference_audio: str | None
    reference_sha256: str | None
    reference_text: str | None
    reference_text_sha256: str | None
    language: str | None
    denoise: bool | None
    postprocess_output: bool | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "voice_project": self.voice_project,
            "voice_target": self.voice_target,
            "profile_alias": self.profile_alias,
            "generation_mode": self.generation_mode,
            "instruction": self.instruction,
            "instruction_override": self.instruction_override,
            "speed": self.speed,
            "steps": self.steps,
            "seed": self.seed,
            "reference_conditioning": self.reference_conditioning,
            "reference_audio": self.reference_audio,
            "reference_sha256": self.reference_sha256,
            "reference_text": self.reference_text,
            "reference_text_sha256": self.reference_text_sha256,
            "language": self.language,
            "denoise": self.denoise,
            "postprocess_output": self.postprocess_output,
            "source": self.source,
        }


class CsvBatchError(ValueError):
    """A CSV shape or batch-safety validation failure."""


class VoiceTargetResolutionError(CsvBatchError):
    """A CSV voice_target cannot be resolved safely before launch."""


@dataclass
class CsvBatchRow:
    csv_row_number: int
    values: dict[str, str]
    selected: bool = True
    status: str = PENDING
    error: str | None = None
    error_stage: str | None = None
    resolved_config: ResolvedGenerationConfig | None = None

    @property
    def file_name(self) -> str:
        return self.values.get("file_name", "").strip()

    @property
    def thai_text(self) -> str:
        return self.values.get("thai_text", "").strip()

    @property
    def tts_text(self) -> str:
        """Optional human-authored pronunciation/prosody representation."""
        return self.values.get("tts_text", "").strip()

    @property
    def spoken_text(self) -> str:
        """The sole text value eligible for the TTS pipeline."""
        return self.tts_text or self.thai_text

    def metadata(self, name: str) -> str:
        return self.values.get(name, "").strip()


def validate_voice_project_id(project_id: str) -> str:
    """Return a filesystem-safe project id or fail before path construction."""
    project_id = str(project_id or "").strip()
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise VoiceTargetResolutionError(
            "voice_project ต้องตรงรูปแบบ [a-z0-9][a-z0-9._-]* และห้ามมี path traversal"
        )
    return project_id


def voice_project_map_path(project_id: str, *, projects_root: Path = PROJECTS_ROOT) -> Path:
    project_id = validate_voice_project_id(project_id)
    root = projects_root.resolve()
    path = (root / project_id / "voice_target_map.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise VoiceTargetResolutionError("voice_project path อยู่นอก projects root") from exc
    return path


def load_voice_target_map(
    project_id: str | None = None,
    *,
    path: Path | None = None,
    projects_root: Path = PROJECTS_ROOT,
) -> dict[str, Any]:
    """Load one project-owned casting map; legacy paths must be explicit."""
    if path is None:
        if project_id is None:
            raise VoiceTargetResolutionError("ต้องระบุ voice_project เพื่อเลือก voice target map")
        path = voice_project_map_path(project_id, projects_root=projects_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VoiceTargetResolutionError(f"ไม่พบ voice target map: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceTargetResolutionError(f"อ่าน voice target map ไม่ได้: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("targets"), dict):
        raise VoiceTargetResolutionError("voice target map schema ไม่ถูกต้อง")
    return data


def resolve_generation_config(
    row: CsvBatchRow,
    voice_alias: str,
    speed: float | None = None,
    steps: int | None = None,
    *,
    map_path: Path | None = None,
    projects_root: Path = PROJECTS_ROOT,
) -> ResolvedGenerationConfig:
    """Resolve a CSV ``voice_target`` or retain the V1 one-profile UI fallback.

    This only resolves configuration; it never appends metadata to spoken text.
    """
    registry = tts.load_json(tts.REGISTRY_PATH)
    project = row.metadata("voice_project")
    if project:
        project = validate_voice_project_id(project)
    target = row.metadata("voice_target")
    if not target:
        voice = tts.resolve_voice(voice_alias, registry)
        return ResolvedGenerationConfig(
            voice_project=project, voice_target="", profile_alias=voice_alias,
            generation_mode=VOICE_DESIGN,
            instruction=voice["voice_instruction"], instruction_override=None,
            speed=float(voice["speed"] if speed is None else speed),
            steps=int(32 if steps is None else steps), seed=voice.get("seed"),
            reference_conditioning=False, reference_audio=None, reference_sha256=None,
            reference_text=None, reference_text_sha256=None,
            language=None, denoise=None, postprocess_output=None,
            source="studio_ui_fallback",
        )

    if map_path is None and not project:
        raise VoiceTargetResolutionError(
            f"voice_target '{target}' ต้องมี voice_project; ไม่เดา project จาก root map แบบ silent"
        )
    mapping = load_voice_target_map(project or None, path=map_path, projects_root=projects_root)
    target_data = mapping["targets"].get(target)
    if not isinstance(target_data, dict):
        raise VoiceTargetResolutionError(f"ไม่พบ mapping สำหรับ voice_target '{target}'")
    profile_alias = target_data.get("profile_alias")
    generation_mode = target_data.get("generation_mode", VOICE_DESIGN)
    instruction_override = target_data.get("instruction_override")
    if not isinstance(profile_alias, str) or not profile_alias.strip():
        raise VoiceTargetResolutionError(f"voice_target '{target}' ไม่มี profile_alias")
    if generation_mode not in GENERATION_MODES:
        raise VoiceTargetResolutionError(
            f"voice_target '{target}' มี generation_mode ที่ไม่รองรับ: {generation_mode!r}"
        )
    if (generation_mode == VOICE_DESIGN
            and (not isinstance(instruction_override, str) or not instruction_override.strip())):
        raise VoiceTargetResolutionError(f"voice_target '{target}' ไม่มี instruction_override")
    if generation_mode == REFERENCE_FIRST:
        instruction_override = None
    try:
        mapped_speed = float(target_data["speed"])
        mapped_steps = int(target_data["steps"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VoiceTargetResolutionError(f"voice_target '{target}' มี speed/steps ไม่ถูกต้อง") from exc
    if mapped_speed <= 0 or mapped_steps < 1:
        raise VoiceTargetResolutionError(f"voice_target '{target}' มี speed/steps นอกช่วงที่ใช้ได้")
    voice = tts.resolve_voice(profile_alias, registry)
    try:
        mapped_seed = int(target_data["seed"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VoiceTargetResolutionError(f"voice_target '{target}' ไม่มี effective seed ที่ถูกต้อง") from exc
    reference_data = target_data.get("reference_conditioning") or {}
    reference_enabled = reference_data.get("enabled") is True
    reference_audio = reference_sha256 = reference_text = reference_text_sha256 = None
    if reference_enabled:
        reference_audio = reference_data.get("reference_audio")
        reference_sha256 = reference_data.get("reference_sha256")
        reference_text = reference_data.get("reference_text")
        reference_text_sha256 = reference_data.get("reference_text_sha256")
        if not all(isinstance(value, str) and value for value in (
                reference_audio, reference_sha256, reference_text, reference_text_sha256)):
            raise VoiceTargetResolutionError(
                f"voice_target '{target}' มี reference conditioning config ไม่ครบ"
            )
        try:
            validate_reference_audio(reference_audio, reference_sha256)
            validate_reference_text(reference_text, reference_text_sha256)
        except (OSError, ValueError) as exc:
            raise VoiceTargetResolutionError(f"voice_target '{target}' reference ไม่ผ่าน: {exc}") from exc
    if generation_mode == REFERENCE_FIRST and not reference_enabled:
        raise VoiceTargetResolutionError(
            f"voice_target '{target}' ใช้ reference_first แต่ไม่มี reference conditioning ที่พร้อมใช้งาน"
        )
    language = target_data.get("language")
    denoise = target_data.get("denoise")
    postprocess_output = target_data.get("postprocess_output")
    if language is not None and (not isinstance(language, str) or not language.strip()):
        raise VoiceTargetResolutionError(f"voice_target '{target}' มี language ไม่ถูกต้อง")
    if denoise is not None and not isinstance(denoise, bool):
        raise VoiceTargetResolutionError(f"voice_target '{target}' มี denoise ไม่ถูกต้อง")
    if postprocess_output is not None and not isinstance(postprocess_output, bool):
        raise VoiceTargetResolutionError(f"voice_target '{target}' มี postprocess_output ไม่ถูกต้อง")
    return ResolvedGenerationConfig(
        voice_project=project, voice_target=target, profile_alias=profile_alias,
        generation_mode=generation_mode,
        instruction=instruction_override, instruction_override=instruction_override,
        speed=mapped_speed, steps=mapped_steps, seed=mapped_seed,
        reference_conditioning=reference_enabled,
        reference_audio=reference_audio, reference_sha256=reference_sha256,
        reference_text=reference_text, reference_text_sha256=reference_text_sha256,
        language=language, denoise=denoise, postprocess_output=postprocess_output,
        source="voice_project_map" if map_path is None else "explicit_legacy_map_path",
    )


def row_diagnostic(row: CsvBatchRow) -> dict[str, Any]:
    """Serialize reviewable CSV state without turning metadata into TTS input."""
    return {
        "csv_row_number": row.csv_row_number,
        "file_name": row.file_name,
        "voice_project": row.metadata("voice_project"),
        "voice_target": row.metadata("voice_target"),
        "selected": row.selected,
        "status": row.status,
        "error_stage": row.error_stage,
        "error": row.error,
        "thai_text": row.thai_text,
        "tts_text": row.tts_text,
        "resolved_spoken_text": row.spoken_text,
        "resolved_generation_config": row.resolved_config.to_dict() if row.resolved_config else None,
    }


def write_launch_diagnostic(path: Path, diagnostic: dict[str, Any]) -> None:
    """Atomically persist every CSV launch attempt, including pre-Popen failures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_csv(path: Path) -> list[CsvBatchRow]:
    """Read UTF-8 or UTF-8-with-BOM CSV, including quoted comma fields."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = [header.strip() for header in (reader.fieldnames or []) if header is not None]
            missing = [name for name in REQUIRED_COLUMNS if name not in headers]
            if missing:
                raise CsvBatchError("CSV ไม่มี required column: " + ", ".join(missing))
            if len(set(headers)) != len(headers):
                raise CsvBatchError("CSV มีชื่อ column ซ้ำ")
            rows = []
            for number, values in enumerate(reader, start=2):
                normalized = {str(key).strip(): (value or "") for key, value in values.items() if key is not None}
                rows.append(CsvBatchRow(number, normalized))
    except UnicodeDecodeError as exc:
        raise CsvBatchError("CSV ต้องเป็น UTF-8 หรือ UTF-8 with BOM") from exc
    except OSError as exc:
        raise CsvBatchError(f"อ่าน CSV ไม่ได้: {exc}") from exc
    if not rows:
        raise CsvBatchError("CSV ไม่มีข้อมูล row")
    return rows


def _validate_file_name(name: str) -> str | None:
    if not name:
        return "file_name ว่าง"
    if "\x00" in name:
        return "file_name มีอักขระต้องห้าม"
    windows = PureWindowsPath(name)
    posix = PurePosixPath(name)
    if (windows.is_absolute() or posix.is_absolute() or windows.drive
            or "/" in name or "\\" in name or ".." in windows.parts or ".." in posix.parts):
        return "file_name ต้องเป็นชื่อไฟล์ WAV เดี่ยว ห้ามมี path หรือ .."
    if Path(name).suffix.lower() != ".wav":
        return "file_name ต้องลงท้าย .wav"
    if Path(name).name != name:
        return "file_name ไม่ถูกต้อง"
    return None


def validate_rows(
    rows: Iterable[CsvBatchRow],
    output_dir: Path,
    voice_alias: str,
    *,
    speed: float | None = None,
    steps: int | None = None,
    map_path: Path | None = None,
    projects_root: Path = PROJECTS_ROOT,
    skip_existing: bool = True,
) -> list[CsvBatchRow]:
    """Validate safely and annotate rows; no model loading or TTS generation."""
    rows = list(rows)
    seen: dict[str, CsvBatchRow] = {}
    for row in rows:
        row.status, row.error, row.error_stage, row.resolved_config = PENDING, None, None, None
        error = _validate_file_name(row.file_name)
        error_stage = "VALIDATION"
        if error is None and not row.thai_text:
            error = "thai_text ว่าง"
        key = row.file_name.casefold()
        if error is None and key in seen:
            error = f"file_name ซ้ำกับ CSV row {seen[key].csv_row_number}"
        if error is None:
            seen[key] = row
            try:
                row.resolved_config = resolve_generation_config(
                    row, voice_alias, speed, steps, map_path=map_path,
                    projects_root=projects_root,
                )
                resolved_alias = row.resolved_config.profile_alias
                prepared = (preview_text(row.spoken_text, resolved_alias) if is_long(row.spoken_text)
                            else preview_single_input_text(row.spoken_text, resolved_alias))
                tts.validate_gate(prepared["prepared"])
            except VoiceTargetResolutionError as exc:
                error, error_stage = str(exc), "VOICE_TARGET_RESOLUTION"
            except Exception as exc:
                error = str(exc)
        if error:
            row.status, row.error, row.error_stage, row.selected = ERROR, error, error_stage, False
        elif skip_existing and (output_dir / row.file_name).exists():
            row.status, row.error, row.selected = SKIPPED, "มี output อยู่แล้ว", False
    return rows


def new_mission_id(rows: Iterable[CsvBatchRow]) -> str:
    rows = list(rows)
    payload = [{"row": row.csv_row_number, "file_name": row.file_name,
                "voice_project": row.metadata("voice_project"),
                "thai_text": row.thai_text, "tts_text": row.tts_text}
               for row in rows]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    projects = sorted({row.metadata("voice_project") for row in rows if row.metadata("voice_project")})
    project_prefix = projects[0] if len(projects) == 1 else "mixed-project"
    return f"studio-csv-{project_prefix}-{datetime.now():%Y%m%d-%H%M%S}-{digest}"


def batch_voice_project(rows: Iterable[CsvBatchRow]) -> str:
    """Return the one project represented by a batch, rejecting ambiguity."""
    values = [row.metadata("voice_project") for row in rows]
    projects = {value for value in values if value}
    if not projects:
        return ""
    if any(not value for value in values):
        raise CsvBatchError("CSV Batch ห้ามผสม row ที่มีและไม่มี voice_project")
    if len(projects) != 1:
        raise CsvBatchError("CSV Batch หนึ่งชุดต้องมี voice_project เดียว")
    return validate_voice_project_id(next(iter(projects)))


def default_project_output_dir(project_id: str) -> Path:
    project_id = validate_voice_project_id(project_id)
    return ROOT / "output" / "studio" / project_id


def build_job(
    rows: Iterable[CsvBatchRow],
    output_dir: Path,
    voice_alias: str,
    speed: float,
    steps: int,
    *,
    mission_id: str | None = None,
    overwrite_selected: bool = False,
    map_path: Path | None = None,
    projects_root: Path = PROJECTS_ROOT,
) -> dict:
    """Build a runner job using only selected, valid CSV rows.

    Optional metadata deliberately remains outside ``lines`` so it cannot become
    an implicit TTS prompt.
    """
    rows = list(rows)
    project = batch_voice_project(rows)
    selected = [row for row in rows if row.selected]
    if not selected:
        raise CsvBatchError("ยังไม่ได้เลือก row สำหรับสร้างเสียง")
    invalid = [row for row in selected if row.status == ERROR]
    if invalid:
        raise CsvBatchError("มี row ที่ไม่ผ่าน validation")
    lines = []
    for row in selected:
        if row.status == SKIPPED and not overwrite_selected:
            continue
        resolved = resolve_generation_config(
            row, voice_alias, speed, steps, map_path=map_path, projects_root=projects_root,
        )
        row.resolved_config = resolved
        lines.append({
            "id": f"csv-{row.csv_row_number:05d}",
            "text": row.spoken_text,
            "output": row.file_name,
            "force": bool(overwrite_selected),
            "voice": resolved.profile_alias,
            "speed": resolved.speed,
            "steps": resolved.steps,
            "seed": resolved.seed,
            "generation_mode": resolved.generation_mode,
            "instruction_override": resolved.instruction_override,
            "voice_project": resolved.voice_project,
            "voice_target": resolved.voice_target,
            "reference_conditioning": resolved.reference_conditioning,
            "reference_audio": resolved.reference_audio,
            "reference_sha256": resolved.reference_sha256,
            "reference_text": resolved.reference_text,
            "reference_text_sha256": resolved.reference_text_sha256,
            "language": resolved.language,
            "denoise": resolved.denoise,
            "postprocess_output": resolved.postprocess_output,
            "canonical_text": row.thai_text,
            "tts_text": row.tts_text,
            "resolved_spoken_text": row.spoken_text,
        })
    if not lines:
        raise CsvBatchError("ไม่มี row ที่พร้อมสร้างเสียง")
    return {
        "mission_id": mission_id or new_mission_id(selected),
        "voice_project": project,
        "output_dir": str(output_dir),
        "defaults": {"voice": voice_alias, "speed": float(speed), "steps": int(steps), "force": False},
        "lines": lines,
    }


def write_job(path: Path, job: dict) -> None:
    """Persist a launchable job atomically without making it a CSV input."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)

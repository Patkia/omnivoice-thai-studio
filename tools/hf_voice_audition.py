from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import requests
import soundfile as sf
from huggingface_hub import HfApi
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "assets" / "hf_voice_candidates"
MANIFEST_PATH = ROOT / "hf_voice_reference_manifest.csv"
STATE_PATH = ROOT / "hf_audition_state.json"
ENGINE_CONFIG_PATH = ROOT / "engine_config.json"
VIEWER = "https://datasets-server.huggingface.co"

PREFERRED_REPOS = (
    "mythicinfinity/libritts_r",
    "parler-tts/libritts-r-filtered-speaker-descriptions",
)
LIBRITTS_AUDIO_REPO = "mythicinfinity/libritts_r"
LIBRITTS_META_REPO = "parler-tts/libritts-r-filtered-speaker-descriptions"

DEFAULT_LINES = (
    "ข้าคิดว่าเรื่องนี้ยังมีบางอย่างที่พวกเรามองข้ามไป",
    "หากเราตรวจสอบให้รอบคอบกว่านี้ อาจพบคำตอบที่ตามหาก็เป็นได้",
)

MANIFEST_FIELDS = [
    "voice_name", "character", "candidate_id", "dataset", "repo", "speaker_id",
    "source_file", "source_url", "license", "license_status", "transcript",
    "duration", "sample_rate", "channels", "bit_depth", "sha256", "cleanliness",
    "transcript_accuracy", "speaker_isolation", "duration_score", "natural_speech",
    "no_clipping", "license_clarity", "character_fit", "distinctness",
    "rpg_character_presence", "dramatic_dialogue_suitability", "vocal_distinctiveness",
    "acting_performance_quality", "human_status", "notes",
]


@dataclass
class Candidate:
    repo: str
    config: str
    split: str
    row_idx: int
    speaker_id: str
    source_id: str
    source_url: str
    source_file: str
    transcript: str
    license: str
    license_status: str
    license_source: str
    row: dict[str, Any] = field(default_factory=dict)
    enrichment: dict[str, Any] = field(default_factory=dict)
    candidate_id: str = ""
    duration: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    sha256: str = ""
    clipping: bool | None = None
    validation: str = "PENDING"
    reject_reason: str = ""
    scores: dict[str, int] = field(default_factory=dict)
    human_status: str = "PENDING_HUMAN_REVIEW"
    master_path: str = ""
    runtime_path: str = ""
    audition_status: str = "NOT_RUN"
    notes: list[str] = field(default_factory=list)


class PipelineError(RuntimeError):
    pass


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return value.strip("_").lower() or "voice"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_get(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def narrator_b_fingerprint() -> dict[str, str]:
    """Capture every file/path occurrence that can identify narrator_B before/after a run."""
    result: dict[str, str] = {}
    for base in (ROOT / "assets", ROOT / "projects"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if "narrator_b" in rel.lower():
                result[rel] = sha256_file(path)
    for path in (ROOT / "approved_voice_profiles.json", ROOT / "voice_profiles.json"):
        if path.exists() and "narrator_B" in path.read_text(encoding="utf-8", errors="ignore"):
            result[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    return result


def license_from_info(info: Any) -> tuple[str, str, str]:
    tags = list(getattr(info, "tags", None) or [])
    tagged = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
    card = getattr(info, "card_data", None)
    card_license = ""
    if card is not None:
        try:
            card_license = str(card.get("license") or "")
        except Exception:
            card_license = str(getattr(card, "license", "") or "")
    value = tagged or card_license
    if not value or value.lower() in {"unknown", "other", "none"}:
        return value or "UNKNOWN", "LICENSE_UNCLEAR", "dataset card/tags"
    return value, "LICENSE_OK", "dataset card/tags"


def get_splits(repo: str, timeout: int = 30) -> list[dict[str, str]]:
    response = requests.get(f"{VIEWER}/splits", params={"dataset": repo}, timeout=timeout)
    if response.status_code != 200:
        return []
    payload = response.json()
    return list(payload.get("splits") or [])


def get_rows(repo: str, config: str, split: str, *, offset: int = 0, length: int = 100,
             timeout: int = 30) -> dict[str, Any]:
    response = requests.get(
        f"{VIEWER}/rows",
        params={"dataset": repo, "config": config, "split": split, "offset": offset, "length": min(length, 100)},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def feature_names(payload: dict[str, Any]) -> set[str]:
    return {str(item.get("name")) for item in payload.get("features") or []}


def extract_audio_src(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("src") or "")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("src"):
                return str(item["src"])
    return ""


def choose_text(row: dict[str, Any]) -> str:
    for key in ("text_original", "text", "sentence", "transcript", "normalized_text", "text_normalized"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def choose_speaker(row: dict[str, Any]) -> str:
    for key in ("speaker_id", "speaker", "client_id", "voice", "reader_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "UNKNOWN"


def choose_id(row: dict[str, Any], row_idx: int) -> str:
    for key in ("id", "utterance_id", "file_id", "path", "audio_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return f"row_{row_idx}"


def repo_search_terms(character: str, role: str, notes: str, hints: str) -> list[str]:
    base = [hints.strip()] if hints.strip() else []
    base.extend(["LibriTTS R", "clean speech TTS", "audiobook speech"])
    if any(word in f"{role} {notes}".lower() for word in ("dramatic", "actor", "rpg", "noble", "villain")):
        base.append("expressive speech")
    # Character is deliberately not sent as a search term: it is game metadata, not a dataset identity.
    return list(dict.fromkeys(term for term in base if term))


def discover_repos(api: HfApi, terms: Iterable[str], max_repos: int = 10) -> list[str]:
    repos: list[str] = []
    for preferred in PREFERRED_REPOS:
        if preferred not in repos:
            repos.append(preferred)
    for term in terms:
        try:
            for info in api.list_datasets(search=term, limit=max_repos):
                if info.id not in repos:
                    repos.append(info.id)
                if len(repos) >= max_repos:
                    return repos
        except Exception:
            continue
    return repos[:max_repos]


def metadata_enrichment_for_libritts(config: str, split: str, id_to_row: dict[str, int]) -> dict[str, dict[str, Any]]:
    if not id_to_row:
        return {}
    # LibriTTS-R metadata mirrors the source ordering. Fetch only the 100-row pages
    # containing candidate rows instead of scanning the dataset from the beginning.
    found: dict[str, dict[str, Any]] = {}
    page_offsets = sorted({(max(0, row_idx) // 100) * 100 for row_idx in id_to_row.values()})
    for offset in page_offsets:
        try:
            payload = get_rows(LIBRITTS_META_REPO, config, split, offset=offset, length=100)
        except Exception:
            continue
        for wrapper in payload.get("rows") or []:
            row = wrapper.get("row") or {}
            row_id = str(row.get("id") or "")
            if row_id in id_to_row:
                found[row_id] = row
    return found


def metadata_match_score(candidate: Candidate, gender: str, role: str, notes: str) -> int:
    score = 0
    row = candidate.enrichment or candidate.row
    requested_gender = gender.lower().strip()
    actual_gender = str(row.get("gender") or "").lower()
    if requested_gender in {"male", "female"}:
        if actual_gender == requested_gender:
            score += 10
        elif actual_gender and actual_gender != requested_gender:
            score -= 30
    duration = float(row.get("speech_duration") or 0.0)
    if 8 <= duration <= 15:
        score += 8
    elif 5 <= duration <= 20:
        score += 5
    elif duration:
        score -= 10
    desc = " ".join(str(row.get(k) or "") for k in ("text_description", "speech_monotony", "noise", "reverberation", "pitch")).lower()
    if any(token in desc for token in ("expressive", "animated", "dynamic")):
        score += 8
    if "monotone" in desc:
        score -= 7
    if any(token in desc for token in ("very clear", "great speech quality", "wonderful speech quality", "excellent", "close-sounding")):
        score += 4
    if any(token in desc for token in ("very noisy", "reverberant", "heavy reverb")):
        score -= 8
    elif "slightly noisy" in desc:
        score -= 3
    requested = f"{role} {notes}".lower()
    if "young" in requested and "very low-pitch" in desc:
        score -= 3
    if any(token in requested for token in ("old", "mature", "commander")) and "very high-pitch" in desc:
        score -= 3
    return score


def discover_rows(api: HfApi, repos: Iterable[str], *, gender: str, role: str, notes: str,
                  max_rows_per_repo: int = 100) -> tuple[list[Candidate], list[str]]:
    discovered: list[Candidate] = []
    searched: list[str] = []
    page_len = min(max_rows_per_repo, 100)
    for repo in repos:
        try:
            info = api.dataset_info(repo)
        except Exception:
            continue
        license_name, license_status, license_source = license_from_info(info)
        searched.append(repo)
        if license_status != "LICENSE_OK":
            continue
        splits = get_splits(repo)
        # Prefer clean/dev/test subsets, avoiding huge training scans.
        splits.sort(key=lambda s: ("clean" not in s.get("config", "").lower(), "dev" not in s.get("split", "").lower(), "test" not in s.get("split", "").lower()))
        for spec in splits[:4]:
            config, split = spec["config"], spec["split"]
            try:
                first = get_rows(repo, config, split, offset=0, length=page_len)
            except Exception:
                continue
            names = feature_names(first)
            if "audio" not in names:
                continue
            total = int(first.get("num_rows_total") or len(first.get("rows") or []))
            max_offset = max(0, total - page_len)
            offsets = [0]
            if max_offset:
                offsets.extend([max_offset // 4, max_offset // 2, (max_offset * 3) // 4, max_offset])
            # Snap to page-sized boundaries, preserve order, and cap at 5 bounded pages.
            offsets = list(dict.fromkeys((max(0, min(max_offset, off)) // page_len) * page_len for off in offsets))[:5]
            payloads = [first]
            for offset in offsets[1:]:
                try:
                    payloads.append(get_rows(repo, config, split, offset=offset, length=page_len))
                except Exception:
                    continue

            local: list[Candidate] = []
            for payload in payloads:
                for wrapper in payload.get("rows") or []:
                    row = wrapper.get("row") or {}
                    row_idx = int(wrapper.get("row_idx", 0))
                    src = extract_audio_src(row.get("audio"))
                    transcript = choose_text(row)
                    if not src or not transcript:
                        continue
                    source_id = choose_id(row, row_idx)
                    local.append(Candidate(
                        repo=repo,
                        config=config,
                        split=split,
                        row_idx=row_idx,
                        speaker_id=choose_speaker(row),
                        source_id=source_id,
                        source_url=src,
                        source_file=str(row.get("path") or source_id),
                        transcript=transcript,
                        license=license_name,
                        license_status=license_status,
                        license_source=license_source,
                        row=row,
                    ))
            if repo == LIBRITTS_AUDIO_REPO and local:
                enrich = metadata_enrichment_for_libritts(config, split, {c.source_id: c.row_idx for c in local})
                for c in local:
                    c.enrichment = enrich.get(c.source_id, {})
            local.sort(key=lambda c: metadata_match_score(c, gender, role, notes), reverse=True)
            discovered.extend(local[:40])
            if local:
                break
    return discovered, searched


def download(url: str, dest: Path, timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 256):
                if chunk:
                    handle.write(chunk)
    tmp.replace(dest)


def wav_properties(path: Path) -> dict[str, Any]:
    info = sf.info(path)
    data, sr = sf.read(path, always_2d=True, dtype="float64")
    if data.size == 0 or not np.isfinite(data).all():
        raise PipelineError("silent/corrupt audio")
    peak = float(np.max(np.abs(data)))
    rms = float(np.sqrt(np.mean(np.square(data))))
    if rms <= 1e-7:
        raise PipelineError("silent audio")
    subtype = str(info.subtype or "")
    bit_depth = 16 if subtype == "PCM_16" else 24 if subtype == "PCM_24" else 32 if subtype == "PCM_32" else 0
    return {
        "duration": float(info.duration),
        "sample_rate": int(sr),
        "channels": int(info.channels),
        "bit_depth": bit_depth,
        "subtype": subtype,
        "peak": peak,
        "rms": rms,
        "clipping": bool(peak >= 0.999999),
    }


def create_runtime_24k(master: Path, runtime: Path) -> dict[str, Any]:
    data, sr = sf.read(master, always_2d=True, dtype="float64")
    if data.shape[1] > 1:
        data = np.mean(data, axis=1, keepdims=True)
    if sr != 24000:
        gcd = math.gcd(int(sr), 24000)
        data = resample_poly(data[:, 0], 24000 // gcd, int(sr) // gcd)[:, None]
    runtime.parent.mkdir(parents=True, exist_ok=True)
    sf.write(runtime, data[:, 0], 24000, subtype="PCM_16")
    return wav_properties(runtime)


def score_candidate(candidate: Candidate, *, gender: str, role: str, notes: str) -> dict[str, int]:
    meta = candidate.enrichment or candidate.row
    desc = " ".join(str(meta.get(k) or "") for k in ("text_description", "speech_monotony", "noise", "reverberation", "pitch")).lower()
    expressive = any(token in desc for token in ("expressive", "animated", "dynamic"))
    noisy = any(token in desc for token in ("slightly noisy", "very noisy", "reverberant", "heavy reverb"))
    clean = 5 if not noisy else 3
    duration = candidate.duration or 0.0
    duration_score = 5 if 8 <= duration <= 15 else 4 if 5 <= duration <= 20 else 1
    requested_gender = gender.lower().strip()
    actual_gender = str(meta.get("gender") or "").lower()
    fit = 3
    if requested_gender in {"male", "female"} and actual_gender:
        fit = 4 if actual_gender == requested_gender else 0
    rpg = 4 if expressive else 3
    acting = 4 if expressive else 3
    if "monotone" in desc:
        rpg = min(rpg, 2)
        acting = min(acting, 2)
    scores = {
        "cleanliness": clean,
        "transcript_accuracy": 5,
        "speaker_isolation": 4,  # clean single-speaker corpus provenance; human listening remains required
        "duration_score": duration_score,
        "natural_speech": 4 if not "monotone" in desc else 3,
        "no_clipping": 5 if not candidate.clipping else 0,
        "license_clarity": 5 if candidate.license_status == "LICENSE_OK" else 0,
        "character_fit": fit,
        "distinctness": 2,  # intentionally conservative: no fake acoustic distinctness metric
        "rpg_character_presence": rpg,
        "dramatic_dialogue_suitability": 4 if expressive else 3,
        "vocal_distinctiveness": 3,
        "acting_performance_quality": acting,
    }
    if scores["rpg_character_presence"] <= 2 and scores["vocal_distinctiveness"] <= 2:
        candidate.notes.append("GENERIC_VOICE_WARNING")
    candidate.notes.append("RPG/character scores are metadata heuristics; Human Listening is authoritative.")
    candidate.notes.append("distinctness_check=HUMAN_REQUIRED")
    return scores


def hard_reject(candidate: Candidate) -> str:
    if candidate.license_status != "LICENSE_OK":
        return "LICENSE_UNCLEAR"
    if not candidate.transcript.strip():
        return "TRANSCRIPT_UNRELIABLE"
    if candidate.validation != "PASS":
        return candidate.reject_reason or "AUDIO_VALIDATION_FAILED"
    if candidate.clipping:
        return "CLIPPING"
    if candidate.duration is None or not 5 <= candidate.duration <= 20:
        return "DURATION_OUT_OF_RANGE"
    meta = candidate.enrichment or candidate.row
    requested_gender = str(meta.get("_requested_gender") or "")
    actual_gender = str(meta.get("gender") or "").lower()
    if requested_gender in {"male", "female"} and actual_gender and actual_gender != requested_gender:
        return "GENDER_MISMATCH"
    return ""


def total_score(candidate: Candidate) -> int:
    return sum(candidate.scores.values())


def prepare_candidate(candidate: Candidate, character: str, requested_gender: str, index: int) -> Candidate:
    base = ASSET_ROOT / slug(character)
    source_suffix = hashlib.sha1(candidate.source_id.encode("utf-8")).hexdigest()[:8]
    candidate.candidate_id = f"candidate_{index:02d}_{source_suffix}"
    source_ext = Path(candidate.source_file).suffix.lower()
    if source_ext not in {".wav", ".flac", ".mp3", ".ogg", ".m4a"}:
        source_ext = ".wav"
    master = base / "master" / f"{candidate.candidate_id}{source_ext}"
    runtime = base / "runtime_24k" / f"{candidate.candidate_id}.wav"

    if not master.exists():
        download(candidate.source_url, master)
    props = wav_properties(master)
    candidate.duration = props["duration"]
    candidate.sample_rate = props["sample_rate"]
    candidate.channels = props["channels"]
    candidate.bit_depth = props["bit_depth"]
    candidate.clipping = props["clipping"]
    candidate.sha256 = sha256_file(master)
    candidate.master_path = master.relative_to(ROOT).as_posix()
    candidate.enrichment["_requested_gender"] = requested_gender.lower().strip()

    candidate.validation = "PASS"
    if candidate.clipping:
        candidate.validation = "REJECT"
        candidate.reject_reason = "CLIPPING"
    elif not 5 <= candidate.duration <= 20:
        candidate.validation = "REJECT"
        candidate.reject_reason = "DURATION_OUT_OF_RANGE"

    if candidate.validation == "PASS":
        runtime_props = create_runtime_24k(master, runtime)
        if runtime_props["sample_rate"] != 24000 or runtime_props["channels"] != 1 or runtime_props["bit_depth"] != 16:
            candidate.validation = "REJECT"
            candidate.reject_reason = "RUNTIME_FORMAT_INVALID"
        else:
            candidate.runtime_path = runtime.relative_to(ROOT).as_posix()
            if abs(runtime_props["duration"] - candidate.duration) > 0.05:
                candidate.validation = "REJECT"
                candidate.reject_reason = "RUNTIME_DURATION_DELTA"
    return candidate


def instruction_for(gender: str, age: str, role: str, notes: str, variant: int) -> str:
    """Build only OmniVoice-supported instruct tokens; RPG identity stays in the reference."""
    valid_age = {
        "child": "child",
        "teen": "teenager",
        "teenager": "teenager",
        "young": "young adult",
        "young_adult": "young adult",
        "young adult": "young adult",
        "adult": "young adult",
        "middle_aged": "middle-aged",
        "middle-aged": "middle-aged",
        "mature": "middle-aged",
        "old": "elderly",
        "elderly": "elderly",
    }
    parts: list[str] = []
    if gender in {"male", "female"}:
        parts.append(gender)
    mapped_age = valid_age.get(age.strip().lower(), "")
    if mapped_age:
        parts.append(mapped_age)
    # Keep pitch deliberately modest. Variant identity comes from reference + seed/speed,
    # not unsupported free-form style text or extreme pitch tricks.
    parts.append("moderate pitch")
    return ", ".join(parts)


def run_audition(candidate: Candidate, *, character: str, gender: str, age: str, role: str, notes: str,
                 variants: int, lines: tuple[str, str]) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tts_runtime import PersistentTtsSession

    if not candidate.runtime_path:
        candidate.audition_status = "SKIPPED_INVALID_REFERENCE"
        return
    engine = _json_get(ENGINE_CONFIG_PATH, {})
    session = PersistentTtsSession(engine["model"], engine["revision"])
    reference_path = ROOT / candidate.runtime_path
    prompt_key = f"hf:{candidate.sha256}:{hashlib.sha256(candidate.transcript.encode('utf-8')).hexdigest()}"
    try:
        prompt, prompt_meta = session.prepare_voice_clone_prompt(
            str(reference_path), candidate.transcript, prompt_key=prompt_key,
        )
    except Exception as exc:
        candidate.audition_status = "FAIL_CLONE_PROMPT"
        candidate.notes.append(f"clone prompt failed: {type(exc).__name__}: {exc}")
        return

    out_dir = ASSET_ROOT / slug(character) / "audition" / candidate.candidate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    audition = {
        "character": character,
        "candidate_id": candidate.candidate_id,
        "reference_sha256": candidate.sha256,
        "reference_transcript": candidate.transcript,
        "reference_file": candidate.master_path,
        "runtime_reference": candidate.runtime_path,
        "voice_clone_prompt": {"status": "PREPARED", **prompt_meta},
        "audition_lines": {"A": lines[0], "B": lines[1]},
        "generation_mode": "reference_first",
        "outputs": [],
        "errors": [],
    }
    seeds = [15016, 26003, 26013]
    for variant in range(1, variants + 1):
        instruct = instruction_for(gender, age, role, notes, variant)
        speed = 1.0 if variant == 1 else 0.98 if variant == 2 else 1.02
        seed = seeds[variant - 1]
        for label, text in zip(("A", "B"), lines):
            output = out_dir / f"line_{label}_v{variant}.wav"
            if output.exists():
                audition["outputs"].append({"file": output.name, "status": "REUSED"})
                continue
            try:
                audio, generation_meta = session.generate(
                    text,
                    instruct=instruct,
                    speed=speed,
                    steps=int(engine.get("default_steps", 32)),
                    seed=seed,
                    voice_clone_prompt=prompt,
                    generation_mode="reference_first",
                    language="th",
                )
                sf.write(output, audio, int(engine.get("sample_rate", 24000)), subtype="PCM_16")
                props = wav_properties(output)
                audition["outputs"].append({
                    "file": output.name, "status": "COMPLETE", "instruction": instruct,
                    "speed": speed, "steps": int(engine.get("default_steps", 32)), "seed": seed,
                    "generation": generation_meta, "audio": props,
                })
            except Exception as exc:
                audition["errors"].append(f"{output.name}: {type(exc).__name__}: {exc}")
    candidate.audition_status = "COMPLETE" if not audition["errors"] else "PARTIAL_FAILURE"
    _json_atomic(out_dir / "audition.json", audition)


def write_manifest(candidates: list[Candidate], character: str) -> None:
    existing: list[dict[str, str]] = []
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    index = {(r.get("character", ""), r.get("candidate_id", ""), r.get("sha256", "")): r for r in existing}
    for c in candidates:
        scores = c.scores
        key = (character, c.candidate_id, c.sha256)
        index[key] = {
            "voice_name": f"AUDITION_{slug(character)}_{c.candidate_id}",
            "character": character,
            "candidate_id": c.candidate_id,
            "dataset": c.repo,
            "repo": c.repo,
            "speaker_id": c.speaker_id,
            "source_file": c.source_file,
            "source_url": c.source_url,
            "license": c.license,
            "license_status": c.license_status,
            "transcript": c.transcript,
            "duration": f"{c.duration:.3f}" if c.duration is not None else "",
            "sample_rate": str(c.sample_rate or ""),
            "channels": str(c.channels or ""),
            "bit_depth": str(c.bit_depth or ""),
            "sha256": c.sha256,
            "cleanliness": str(scores.get("cleanliness", "")),
            "transcript_accuracy": str(scores.get("transcript_accuracy", "")),
            "speaker_isolation": str(scores.get("speaker_isolation", "")),
            "duration_score": str(scores.get("duration_score", "")),
            "natural_speech": str(scores.get("natural_speech", "")),
            "no_clipping": str(scores.get("no_clipping", "")),
            "license_clarity": str(scores.get("license_clarity", "")),
            "character_fit": str(scores.get("character_fit", "")),
            "distinctness": str(scores.get("distinctness", "")),
            "rpg_character_presence": str(scores.get("rpg_character_presence", "")),
            "dramatic_dialogue_suitability": str(scores.get("dramatic_dialogue_suitability", "")),
            "vocal_distinctiveness": str(scores.get("vocal_distinctiveness", "")),
            "acting_performance_quality": str(scores.get("acting_performance_quality", "")),
            "human_status": c.human_status,
            "notes": " | ".join(c.notes + ([c.reject_reason] if c.reject_reason else [])),
        }
    rows = list(index.values())
    tmp = MANIFEST_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(MANIFEST_PATH)


def write_review_html(candidates: list[Candidate], character: str) -> Path:
    base = ASSET_ROOT / slug(character)
    path = base / "audition_review.html"
    cards: list[str] = []
    for c in candidates:
        ref = Path(c.master_path).relative_to(Path("assets") / "hf_voice_candidates" / slug(character)).as_posix() if c.master_path else ""
        audition_dir = Path("audition") / c.candidate_id
        audio_tags = []
        full_audition_dir = base / audition_dir
        if full_audition_dir.exists():
            for wav in sorted(full_audition_dir.glob("*.wav")):
                audio_tags.append(f"<div><b>{html.escape(wav.name)}</b><br><audio controls src='{html.escape((audition_dir / wav.name).as_posix())}'></audio></div>")
        score_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in c.scores.items())
        cards.append(f"""
        <section>
          <h2>{html.escape(c.candidate_id)} — speaker {html.escape(c.speaker_id)}</h2>
          <p><b>Dataset:</b> {html.escape(c.repo)} | <b>License:</b> {html.escape(c.license)} | <b>Status:</b> {html.escape(c.human_status)}</p>
          <p><b>Transcript:</b> {html.escape(c.transcript)}</p>
          <p><b>Duration:</b> {c.duration or 0:.3f}s | <b>Format:</b> {c.sample_rate} Hz / {c.channels} ch / {c.bit_depth}-bit | <b>Validation:</b> {html.escape(c.validation)}</p>
          <p><b>Source:</b> <a href='{html.escape(c.source_url)}'>Hugging Face cached audio/source</a></p>
          {f"<audio controls src='{html.escape(ref)}'></audio>" if ref else ""}
          <table><tbody>{score_rows}</tbody></table>
          <p><b>Notes:</b> {html.escape(' | '.join(c.notes))}</p>
          {''.join(audio_tags)}
        </section>""")
    document = f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(character)} HF Voice Audition</title>
<style>body{{font-family:Segoe UI,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem}}section{{border:1px solid #ccc;border-radius:12px;padding:1rem;margin:1rem 0}}table{{border-collapse:collapse}}td{{border:1px solid #ddd;padding:.3rem .6rem}}audio{{width:100%;max-width:620px}}</style></head>
<body><h1>{html.escape(character)} — Hugging Face RPG Voice Audition</h1><p>Human status defaults to PENDING_HUMAN_REVIEW. No production registration is performed.</p>{''.join(cards)}</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


def update_state(character: str, searched: list[str], candidates: list[Candidate], review_path: Path) -> None:
    state = _json_get(STATE_PATH, {})
    state[character] = {
        "updated": date.today().isoformat(),
        "searched_datasets": searched,
        "candidates": [asdict(c) for c in candidates],
        "review_path": review_path.relative_to(ROOT).as_posix(),
    }
    _json_atomic(STATE_PATH, state)


def existing_candidate_from_state(character: str) -> list[Candidate]:
    state = _json_get(STATE_PATH, {})
    rows = (state.get(character) or {}).get("candidates") or []
    return [Candidate(**row) for row in rows]


def run(args: argparse.Namespace) -> int:
    before_narrator = narrator_b_fingerprint()
    character = args.character.strip()
    state_candidates = existing_candidate_from_state(character) if args.resume else []
    searched: list[str] = []
    prepared: list[Candidate] = []

    if state_candidates:
        for c in state_candidates:
            master = ROOT / c.master_path if c.master_path else None
            runtime = ROOT / c.runtime_path if c.runtime_path else None
            if master and runtime and master.exists() and runtime.exists() and sha256_file(master) == c.sha256:
                prepared.append(c)
        if len(prepared) >= args.max_candidates:
            prepared = prepared[: args.max_candidates]
        else:
            prepared = []

    if not prepared:
        api = HfApi()
        terms = repo_search_terms(character, args.role, args.notes, args.search_hints)
        repos = [args.repo] if args.repo else discover_repos(api, terms, max_repos=args.max_repos)
        discovered, searched = discover_rows(
            api, repos, gender=args.gender, role=args.role, notes=args.notes,
            max_rows_per_repo=args.max_search_rows,
        )
        if not discovered:
            raise PipelineError("No Hugging Face candidates with clear license + audio + reliable transcript metadata were discovered")

        # Download a bounded pool, validate duration/audio, then retain the best candidates.
        pool_size = min(len(discovered), max(args.max_candidates * 5, 10))
        evaluated: list[Candidate] = []
        for idx, candidate in enumerate(discovered[:pool_size], 1):
            try:
                candidate = prepare_candidate(candidate, character, args.gender, idx)
                candidate.scores = score_candidate(candidate, gender=args.gender, role=args.role, notes=args.notes)
                meta_path = ASSET_ROOT / slug(character) / "metadata" / f"{candidate.candidate_id}.json"
                _json_atomic(meta_path, asdict(candidate))
                reason = hard_reject(candidate)
                if reason:
                    candidate.validation = "REJECT"
                    candidate.reject_reason = reason
                    candidate.human_status = "REJECT_AUTO"
                _json_atomic(meta_path, asdict(candidate))
                evaluated.append(candidate)
            except Exception as exc:
                candidate.validation = "REJECT"
                candidate.reject_reason = f"{type(exc).__name__}: {exc}"
                candidate.human_status = "REJECT_AUTO"
                candidate.candidate_id = candidate.candidate_id or f"candidate_{idx:02d}"
                evaluated.append(candidate)
        valid = [c for c in evaluated if c.validation == "PASS"]
        valid.sort(key=total_score, reverse=True)
        prepared = valid[: args.max_candidates]
        # Keep rejected metadata in manifest as audit evidence, but audition only valid candidates.
        write_manifest(evaluated, character)
        if not prepared:
            review = write_review_html(evaluated, character)
            update_state(character, searched, evaluated, review)
            raise PipelineError("Candidates were discovered, but all were rejected by validation/policy")

    if not args.discover_only:
        for candidate in prepared:
            if candidate.audition_status == "COMPLETE" and args.resume:
                continue
            run_audition(
                candidate,
                character=character,
                gender=args.gender,
                age=args.age,
                role=args.role,
                notes=args.notes,
                variants=args.variants,
                lines=(args.line_a, args.line_b),
            )
            meta_path = ASSET_ROOT / slug(character) / "metadata" / f"{candidate.candidate_id}.json"
            _json_atomic(meta_path, asdict(candidate))

    write_manifest(prepared, character)
    review = write_review_html(prepared, character)
    update_state(character, searched, prepared, review)

    after_narrator = narrator_b_fingerprint()
    if before_narrator != after_narrator:
        raise PipelineError("narrator_B protection failed: fingerprint changed")

    rejected = sum(1 for c in prepared if c.validation != "PASS")
    print(f"CHARACTER={character}")
    print(f"SEARCHED_DATASETS={len(searched)}")
    print(f"CANDIDATES_DISCOVERED={len(prepared)}")
    print(f"CANDIDATES_LICENSE_OK={sum(c.license_status == 'LICENSE_OK' for c in prepared)}")
    print(f"CANDIDATES_DOWNLOADED={sum(bool(c.master_path) for c in prepared)}")
    print(f"CANDIDATES_VALIDATED={sum(c.validation == 'PASS' for c in prepared)}")
    print(f"CANDIDATES_AUDITIONED={sum(c.audition_status == 'COMPLETE' for c in prepared)}")
    print(f"CANDIDATES_REJECTED={rejected}")
    print(f"AUDITION_REVIEW_PATH={review}")
    print(f"MANIFEST_PATH={MANIFEST_PATH}")
    print(f"STATE_PATH={STATE_PATH}")
    for c in prepared:
        print("\t".join([
            c.candidate_id, c.repo, c.speaker_id, f"{c.duration or 0:.3f}s", c.license,
            c.validation, c.audition_status, c.human_status, c.reject_reason or "-",
        ]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hugging Face -> validated OmniVoice Thai RPG audition pipeline")
    parser.add_argument("--character", required=True)
    parser.add_argument("--gender", required=True, choices=("male", "female", "unknown"))
    parser.add_argument("--age", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--search-hints", default="")
    parser.add_argument("--repo", default="", help="Optional explicit Hugging Face dataset repo")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--max-repos", type=int, default=8)
    parser.add_argument("--max-search-rows", type=int, default=100)
    parser.add_argument("--variants", type=int, default=2, choices=(2, 3))
    parser.add_argument("--line-a", default=DEFAULT_LINES[0])
    parser.add_argument("--line-b", default=DEFAULT_LINES[1])
    parser.add_argument("--discover-only", action="store_true", help="Search/download/validate/build review pack without model inference")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except (PipelineError, requests.RequestException, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

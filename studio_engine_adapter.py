"""In-process Studio adapter using frozen Engine v1 helpers and a persistent runtime."""
from __future__ import annotations

import json
import hashlib
import platform
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import soundfile as sf
from audio_validation import validate_audible_audio
import torch

import tts
from novel_chunker import LEADING_CONNECTIVE_PHRASES
from tts_runtime import PersistentTtsSession

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "approved_voice_profiles.json"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "studio"
PARAGRAPH_PAUSE_MARK = "…"
PARAGRAPH_TERMINATORS = frozenset(".!?…。！？")


def resolve_project_reference_path(value: str | Path) -> Path:
    """Resolve only project-controlled reference files."""
    supplied = Path(value)
    candidate = supplied.resolve() if supplied.is_absolute() else (ROOT / supplied).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError("reference_audio ต้องอยู่ภายใน OmniVoice workspace") from exc
    return candidate


def validate_reference_audio(value: str | Path, expected_sha256: str) -> dict:
    """Fail closed for a missing, changed, or incompatible approved reference."""
    path = resolve_project_reference_path(value)
    if not path.is_file():
        raise FileNotFoundError(f"ไม่พบ approved reference_audio: {path}")
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if not expected_sha256 or actual_sha256.casefold() != expected_sha256.casefold():
        raise ValueError(f"reference_audio SHA256 ไม่ตรง: {path}")
    try:
        with wave.open(str(path), "rb") as audio:
            metadata = {
                "sample_rate": audio.getframerate(),
                "channels": audio.getnchannels(),
                "sample_width": audio.getsampwidth(),
                "frames": audio.getnframes(),
                "compression": audio.getcomptype(),
            }
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"reference_audio ไม่ใช่ WAV ที่ใช้ได้: {path}") from exc
    if (metadata["sample_rate"], metadata["channels"], metadata["sample_width"], metadata["compression"]) != (24000, 1, 2, "NONE"):
        raise ValueError("reference_audio ต้องเป็น PCM16 / 24000 Hz / mono")
    return {
        "path": path,
        "sha256": actual_sha256,
        "duration_seconds": metadata["frames"] / metadata["sample_rate"],
        **metadata,
    }


def validate_reference_text(reference_text: str, expected_sha256: str) -> str:
    if not reference_text:
        raise ValueError("reference_text ว่าง; reference-first target ห้าม fallback ไป ASR")
    actual = hashlib.sha256(reference_text.encode("utf-8")).hexdigest()
    if not expected_sha256 or actual.casefold() != expected_sha256.casefold():
        raise ValueError("reference_text SHA256 ไม่ตรง")
    return actual


def load_voice_aliases() -> dict:
    return tts.load_json(REGISTRY_PATH).get("aliases", {})


def default_output_path(now: datetime | None = None) -> Path:
    now = now or datetime.now()
    return DEFAULT_OUTPUT_DIR / f"tts_{now:%Y%m%d_%H%M%S}.wav"


def preview_text(text: str, alias: str, *, spoken_override: str | None = None) -> dict:
    registry = tts.load_json(REGISTRY_PATH)
    voice = tts.resolve_voice(alias, registry)
    engine = tts.load_json(tts.ENGINE_PATH)
    prepared = tts.prepare_text(text, ROOT / engine["normalization"]["pronunciation_dictionary_path"], spoken_override=spoken_override)
    return {"voice": voice, "prepared": prepared}


def add_paragraph_pause_cues(text: str) -> tuple[str, int]:
    """Add a light cue before a connective-led paragraph in the spoken copy."""
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    insertions = 0
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        ending = line[len(content):]
        if not ending:
            output.append(line)
            continue
        next_text = next((item.strip() for item in lines[index + 1:] if item.strip()), "")
        trimmed = content.rstrip()
        if (trimmed and next_text
                and next_text.startswith(LEADING_CONNECTIVE_PHRASES)
                and trimmed[-1] not in PARAGRAPH_TERMINATORS):
            content = f"{trimmed}{PARAGRAPH_PAUSE_MARK}{content[len(trimmed):]}"
            insertions += 1
        output.append(content + ending)
    return "".join(output), insertions


def preview_single_input_text(text: str, alias: str, *, spoken_override: str | None = None) -> dict:
    """Prepare one Studio request while retaining canonical source fields."""
    data = preview_text(text, alias, spoken_override=spoken_override)
    prepared = dict(data["prepared"])
    spoken, insertions = add_paragraph_pause_cues(prepared["spoken"])
    prepared["spoken"] = spoken
    prepared["gate"] = tts.normalize_text(spoken, enabled=False)
    prepared["paragraph_pause_preparation"] = {
        "enabled": True,
        "mark": PARAGRAPH_PAUSE_MARK,
        "insertions": insertions,
    }
    return {"voice": data["voice"], "prepared": prepared}


def generation_cache_keys(payload: dict, seed: int | None) -> tuple[str, str | None]:
    """Keep seed=None on its established key, with one compatibility lookup."""
    key = tts.cache_key({**payload, "seed": seed}) if seed is not None else tts.cache_key(payload)
    return key, tts.cache_key({**payload, "seed": None}) if seed is None else None


def resolve_generation_seed(voice: dict, supplied_seed: int | None) -> int | None:
    """An explicit continuity seed wins; profiles without a seed retain legacy None."""
    return supplied_seed if supplied_seed is not None else voice.get("seed")


class StudioEngineAdapter:
    def __init__(self):
        self.engine = tts.load_json(tts.ENGINE_PATH)
        self.session = PersistentTtsSession(self.engine["model"], self.engine["revision"])

    @property
    def model_status(self) -> str:
        return self.session.state

    def ensure_engine_loaded(self, status: Callable[[str], None] | None = None) -> dict:
        """Warm the persistent Engine v1 session without generating audio."""
        return self.session.ensure_loaded(status=status)

    def prepare_reference_conditioning(
        self, reference_audio: str, reference_sha256: str,
        reference_text: str, reference_text_sha256: str,
        status: Callable[[str], None] | None = None,
        *, voice_project: str = "",
    ) -> dict:
        audio = validate_reference_audio(reference_audio, reference_sha256)
        text_sha256 = validate_reference_text(reference_text, reference_text_sha256)
        prompt_key = f"{voice_project}:{audio['sha256']}:{text_sha256}"
        _prompt, metadata = self.session.prepare_voice_clone_prompt(
            str(audio["path"]), reference_text, prompt_key=prompt_key, status=status,
        )
        return {
            **metadata,
            "reference_audio": str(audio["path"]),
            "reference_sha256": audio["sha256"],
            "reference_text_sha256": text_sha256,
            "reference_conditioning_enabled": True,
            "reference_prompt_key": prompt_key,
        }

    def generate(self, text, alias, speed, steps, output, force,
                 status: Callable[[str], None] | None = None, seed: int | None = None,
                 instruct_override: str | None = None, single_input: bool = False,
                 reference_conditioning: bool = False, reference_audio: str | None = None,
                 reference_sha256: str | None = None, reference_text: str | None = None,
                 reference_text_sha256: str | None = None,
                 spoken_override: str | None = None,
                 generation_mode: str = "voice_design", language: str | None = None,
                 denoise: bool | None = None, postprocess_output: bool | None = None,
                 voice_project: str = "") -> dict:
        if status:
            status("กำลังตรวจ Cache...")
        data = (preview_single_input_text(text, alias, spoken_override=spoken_override)
                if single_input else preview_text(text, alias, spoken_override=spoken_override))
        prepared, voice = data["prepared"], data["voice"]
        tts.validate_gate(prepared)
        # Optional POC-only descriptive prompt. Default calls retain the approved
        # registry instruction exactly, so Engine v1/Studio semantics are unchanged.
        if generation_mode not in {"voice_design", "reference_first"}:
            raise ValueError(f"unsupported generation_mode: {generation_mode}")
        instruction = None if generation_mode == "reference_first" else (instruct_override or voice["voice_instruction"])
        effective_seed = resolve_generation_seed(voice, seed)
        reference = None
        if reference_conditioning:
            if not all((reference_audio, reference_sha256, reference_text, reference_text_sha256)):
                raise ValueError("reference conditioning config ไม่ครบ; ห้าม fallback ไป instruct-only")
            reference = {
                "audio": validate_reference_audio(reference_audio, reference_sha256),
                "text_sha256": validate_reference_text(reference_text, reference_text_sha256),
            }
        if generation_mode == "reference_first" and reference is None:
            raise ValueError("reference_first requires validated reference conditioning")
        payload = {
            "text": prepared["spoken"], "model": self.engine["model"], "revision": self.engine["revision"],
            "voice_instruction": instruction, "speed": speed, "steps": steps,
            "sample_rate": self.engine["sample_rate"], "audio_normalization": tts.AUDIO_NORMALIZATION,
            "generation_mode": generation_mode,
            "reference_conditioning": reference_conditioning,
            "reference_sha256": reference["audio"]["sha256"] if reference else None,
            "reference_text_sha256": reference["text_sha256"] if reference else None,
        }
        if voice_project:
            payload["voice_project"] = voice_project
        # Direct-clone controls are part of reference_first identity.  Legacy
        # voice_design outputs still receive a compatibility lookup below.
        if generation_mode != "voice_design":
            payload.update(
                language=language,
                denoise=denoise,
                postprocess_output=postprocess_output,
            )
        key, seed_none_key = generation_cache_keys(payload, effective_seed)
        cache_keys = {key, seed_none_key}
        if generation_mode == "voice_design":
            legacy_payload = dict(payload)
            legacy_payload.pop("generation_mode")
            legacy_key, legacy_seed_none_key = generation_cache_keys(legacy_payload, effective_seed)
            cache_keys.update((legacy_key, legacy_seed_none_key))
        cache_keys.discard(None)
        report = tts.load_report()
        output_text = str(output)
        cached = next((row for row in report.get("runs", [])
                       if row.get("output") == output_text and row.get("cache_key") in cache_keys), None)
        if output.exists() and cached and not force:
            cached_audio, _cached_rate = sf.read(output, dtype="float32")
            validate_audible_audio(cached_audio)
            cached["cache_status"] = "hit"
            cached["cache_checked_at"] = datetime.now(timezone.utc).isoformat()
            tts.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            tts.REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"cache_hit": True, "output": output, "model_load_count": self.session.model_load_count,
                    "model_reused": False, "model_load_seconds": 0.0, "inference_seconds": 0.0}

        prompt = None
        prompt_meta = {"reference_prompt_prep_count": self.session.reference_prompt_prep_count}
        if reference is not None:
            prompt_key = f"{voice_project}:{reference['audio']['sha256']}:{reference['text_sha256']}"
            prompt, prompt_meta = self.session.prepare_voice_clone_prompt(
                str(reference["audio"]["path"]), reference_text,
                prompt_key=prompt_key, status=status,
            )
        started = time.perf_counter()
        audio, meta = self.session.generate(
            prepared["spoken"], instruction, speed, steps, status,
            seed=effective_seed, voice_clone_prompt=prompt,
            generation_mode=generation_mode, language=language,
            denoise=denoise, postprocess_output=postprocess_output,
        )
        if status:
            status("กำลังบันทึก WAV...")
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, self.engine["sample_rate"], subtype="PCM_16")
        entry = {
            "cache_key": key, "created_at": datetime.now(timezone.utc).isoformat(), "source_type": "text",
            "original_text": text, "normalized_text": prepared["normalized"], "final_spoken_text": prepared["spoken"],
            "normalization_transformations": prepared["normalization"], "pronunciation_substitutions": prepared["substitutions"],
            "thai_only_gate": {"passed": True, "latin_remaining": False, "arabic_digits_remaining": False},
            "voice_alias": alias, "resolved_voice_instruction": instruction, "speed": speed, "steps": steps, "seed": effective_seed,
            "generation_mode": generation_mode, "language": language,
            "denoise": denoise, "postprocess_output": postprocess_output,
            "voice_project": voice_project,
            "reference_conditioning_enabled": reference_conditioning,
            "reference_audio": str(reference["audio"]["path"]) if reference else None,
            "reference_sha256": reference["audio"]["sha256"] if reference else None,
            "reference_text_sha256": reference["text_sha256"] if reference else None,
            "single_input": single_input,
            "paragraph_pause_preparation": prepared.get("paragraph_pause_preparation", {"enabled": False, "insertions": 0}),
            "model": self.engine["model"], "revision": self.engine["revision"], "sample_rate": self.engine["sample_rate"],
            "audio_normalization": tts.AUDIO_NORMALIZATION, "output": output_text,
            "duration_seconds": tts.wav_duration(output), "generation_seconds": round(time.perf_counter() - started, 3),
            "device": meta["device"], "torch": torch.__version__, "cuda_version": torch.version.cuda,
            "platform": platform.platform(), "cache_status": "generated",
            "warnings": ["ไม่พบ CUDA GPU; สร้างเสียงด้วย CPU ซึ่งใช้เวลานานกว่า"] if meta["device"] == "cpu" else [],
            "errors": [], "invocation_source": "studio", "persistent_session": True,
            **prompt_meta, **meta,
        }
        report["runs"] = [row for row in report.get("runs", [])
                          if not (row.get("cache_key") == key and row.get("output") == output_text)] + [entry]
        tts.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tts.REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"cache_hit": False, "output": output, **meta, "total_generation_seconds": entry["generation_seconds"]}

"""Shared, non-UI Studio generation routing for Engine v1."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from long_text_batch import generate as generate_long, is_long


def generate_studio_request(
    adapter: Any,
    text: str,
    alias: str,
    speed: float,
    steps: int,
    output: Path,
    force: bool,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int, str], None] = lambda current, total, status: None,
    seed: int | None = None,
    instruction_override: str | None = None,
    reference_conditioning: bool = False,
    reference_audio: str | None = None,
    reference_sha256: str | None = None,
    reference_text: str | None = None,
    reference_text_sha256: str | None = None,
    spoken_override: str | None = None,
    generation_mode: str = "voice_design",
    language: str | None = None,
    denoise: bool | None = None,
    postprocess_output: bool | None = None,
    voice_project: str = "",
) -> dict:
    """Use the approved single-first Studio policy for one text request."""
    from pronunciation_policy import apply_pronunciation_policy

    effective_spoken = spoken_override if spoken_override is not None else text
    if generation_mode == "reference_first":
        if not reference_conditioning:
            raise ValueError("reference_first requires validated reference conditioning")
        effective_reference = True
        policy_id = "reference_first_preserve_reference"
    else:
        policy = apply_pronunciation_policy(
            effective_spoken, reference_conditioning=reference_conditioning
        )
        effective_reference = policy.reference_conditioning
        policy_id = policy.policy_id

    if is_long(text):
        result = generate_long(
            adapter, text, alias, speed, steps, output, force,
            cancelled=cancelled, progress=progress, seed=seed,
            instruction_override=instruction_override,
            reference_conditioning=effective_reference,
            reference_audio=reference_audio, reference_sha256=reference_sha256,
            reference_text=reference_text, reference_text_sha256=reference_text_sha256,
            generation_mode=generation_mode, language=language, denoise=denoise,
            postprocess_output=postprocess_output,
            voice_project=voice_project,
        )
        result.update(
            cache_hit=False, output=output,
            total_generation_seconds=result.get("inference_seconds", 0),
            long_text=True, input_chars=len(text),
            pronunciation_policy=policy_id,
        )
        return result

    options = {"seed": seed, "single_input": True}
    if generation_mode != "voice_design":
        options["generation_mode"] = generation_mode
    if language is not None:
        options["language"] = language
    if denoise is not None:
        options["denoise"] = denoise
    if postprocess_output is not None:
        options["postprocess_output"] = postprocess_output
    if voice_project:
        options["voice_project"] = voice_project
    if instruction_override is not None:
        options["instruct_override"] = instruction_override
    if spoken_override is not None:
        options["spoken_override"] = spoken_override
    if effective_reference:
        options.update(
            reference_conditioning=True,
            reference_audio=reference_audio,
            reference_sha256=reference_sha256,
            reference_text=reference_text,
            reference_text_sha256=reference_text_sha256,
        )
    result = adapter.generate(text, alias, speed, steps, output, force, **options)
    result.update(
        long_text=False, input_chars=len(text), application_generation_count=1,
        pronunciation_policy=policy_id,
    )
    return result

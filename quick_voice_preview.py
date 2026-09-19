"""Pure helpers for the Studio's independent short voice-preview action."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from novel_chunker import _CLOSE_QUOTES, _SENTENCE, semantic_chunks


PREVIEW_TARGET_CHARACTERS = 100
PREVIEW_HARD_MAX = 120
PREVIEW_OUTPUT_DIR = Path("output") / "studio" / "preview"


class PreviewTextError(ValueError):
    pass


def select_preview_text(text: str) -> str:
    """Return the first sentence-like semantic unit, never longer than 120 chars."""
    source = text.strip()
    if not source:
        raise PreviewTextError("กรุณากรอกข้อความก่อนทดลองเสียง")
    # Preserve the first complete sentence whenever it fits. Quote and
    # paragraph endings are also meaningful first-unit boundaries in Thai prose.
    for index, char in enumerate(source):
        if char in _SENTENCE or char == "\n" or char in _CLOSE_QUOTES:
            end = index + 1
            while end < len(source) and source[end].isspace():
                end += 1
            if end <= PREVIEW_HARD_MAX:
                return source[:end]
            break
    # semantic_chunks already preserves combining marks and supplies the safe
    # <= hard_max fallback when the first sentence/unit is long.
    return semantic_chunks(source, PREVIEW_TARGET_CHARACTERS, PREVIEW_HARD_MAX)[0].text


def preview_output_path(text: str, voice: str, speed: float, steps: int,
                        root: Path = Path(".")) -> Path:
    """Stable preview path; separate from user-selected final Studio output."""
    payload = {"text": text, "voice": voice, "speed": speed, "steps": steps}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return root / PREVIEW_OUTPUT_DIR / f"preview_{digest}.wav"

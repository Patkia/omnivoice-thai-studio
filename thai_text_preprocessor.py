"""Optional data-driven Thai pronunciation substitutions for TTS input."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


def load_replacements(dictionary_path: str | Path) -> dict[str, str]:
    """Load only non-empty string substitutions from a dictionary data file."""
    payload = json.loads(Path(dictionary_path).read_text(encoding="utf-8"))
    replacements = payload.get("replacements", payload)
    if not isinstance(replacements, Mapping):
        raise ValueError("pronunciation dictionary replacements must be an object")
    return {
        source: target for source, target in replacements.items()
        if isinstance(source, str) and isinstance(target, str) and source and target
    }


def preprocess_text(
    text: str,
    dictionary_path: str | Path = "pronunciation_dictionary.json",
    *,
    enabled: bool = False,
) -> str:
    """Return original text when disabled, otherwise apply data-file substitutions."""
    return preprocess_with_details(text, dictionary_path, enabled=enabled)[0]


def preprocess_with_details(
    text: str,
    dictionary_path: str | Path = "pronunciation_dictionary.json",
    *,
    enabled: bool = False,
) -> tuple[str, list[dict[str, str | int]]]:
    """Return transformed text and the data-file substitutions actually applied."""
    if not enabled:
        return text, []
    result = text
    replacements = load_replacements(dictionary_path)
    applied: list[dict[str, str | int]] = []
    # Longest source first prevents a shorter entry consuming a longer one.
    for source in sorted(replacements, key=len, reverse=True):
        count = result.count(source)
        if count:
            result = result.replace(source, replacements[source])
            applied.append({"source": source, "replacement": replacements[source], "count": count})
    return result, applied

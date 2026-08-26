"""Deterministic, auditable Thai-script normalization before pronunciation lookup."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CANDIDATES = ROOT / "thai_normalization_candidates.json"
_LATIN = re.compile(r"[A-Za-z]")
_DIGITS = re.compile(r"[0-9]")


@dataclass(frozen=True)
class NormalizationResult:
    text: str
    transformations: list[dict[str, str]]
    latin_remaining: bool
    arabic_digits_remaining: bool
    thai_only_gate_passed: bool

    def as_dict(self) -> dict:
        return asdict(self)


def load_candidates(path: str | Path = DEFAULT_CANDIDATES) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


_ONES = ("ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า")


def thai_integer(value: int) -> str:
    """Baseline cardinal reading for non-negative integers up to 9,999,999."""
    if not 0 <= value <= 9_999_999:
        raise ValueError("POC numeric normalizer supports integers from 0 through 9,999,999")
    if value == 0:
        return _ONES[0]
    units = ((1_000_000, "ล้าน"), (100_000, "แสน"), (10_000, "หมื่น"), (1_000, "พัน"), (100, "ร้อย"), (10, "สิบ"), (1, ""))
    result: list[str] = []
    remaining = value
    for divisor, label in units:
        digit, remaining = divmod(remaining, divisor)
        if not digit:
            continue
        if divisor == 10 and digit == 2:
            word = "ยี่"
        elif divisor == 1 and digit == 1 and value > 10:
            word = "เอ็ด"
        elif divisor == 10 and digit == 1:
            word = ""
        else:
            word = _ONES[digit]
        result.append(word + label)
    return "".join(result)


def _replace(text: str, source: str, replacement: str, kind: str, log: list[dict[str, str]]) -> str:
    if source not in text:
        return text
    log.append({"kind": kind, "source": source, "replacement": replacement})
    return text.replace(source, replacement)


def normalize_text(
    text: str,
    *,
    enabled: bool = True,
    candidate_path: str | Path = DEFAULT_CANDIDATES,
    time_style: str = "natural",
) -> NormalizationResult:
    """Normalize only known POC patterns and record every visible transformation."""
    if not enabled:
        return _result(text, [])
    candidates = load_candidates(candidate_path)
    result = text
    log: list[dict[str, str]] = []
    if time_style not in candidates["time_0217"]:
        raise ValueError(f"Unknown time style: {time_style}")
    result = _replace(result, "02:17", candidates["time_0217"][time_style], "time", log)
    for source, options in {**candidates["names"], **candidates["game_terms"]}.items():
        result = _replace(result, source, options[0], "candidate_transliteration", log)
    # Decimal and comma-grouped values must be handled before standalone integer tokens.
    def decimal(match: re.Match[str]) -> str:
        source = match.group(0)
        whole, fraction = source.split(".")
        replacement = thai_integer(int(whole.replace(",", ""))) + "จุด" + "".join(_ONES[int(d)] for d in fraction)
        log.append({"kind": "decimal", "source": source, "replacement": replacement})
        return replacement
    result = re.sub(r"\b\d{1,3}(?:,\d{3})+\.\d+\b|\b\d+\.\d+\b", decimal, result)
    def integer(match: re.Match[str]) -> str:
        source = match.group(0)
        replacement = thai_integer(int(source.replace(",", "")))
        log.append({"kind": "integer", "source": source, "replacement": replacement})
        return replacement
    result = re.sub(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", integer, result)
    return _result(result, log)


def _result(text: str, transformations: list[dict[str, str]]) -> NormalizationResult:
    latin_remaining = bool(_LATIN.search(text))
    arabic_digits_remaining = bool(_DIGITS.search(text))
    return NormalizationResult(text, transformations, latin_remaining, arabic_digits_remaining, not latin_remaining and not arabic_digits_remaining)

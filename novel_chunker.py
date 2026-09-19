"""Deterministic, narrative-aware Thai prose chunking (no model calls)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import unicodedata

CONTINUATION_PAUSE_MS = 220
SENTENCE_PAUSE_MS = 320
DIALOGUE_PAUSE_MS = 350
PARAGRAPH_PAUSE_MS = 650
EMOTIONAL_BEAT_PAUSE_MS = 750

BOUNDARY_PAUSES_MS = {"continuation": CONTINUATION_PAUSE_MS, "weak_clause": CONTINUATION_PAUSE_MS,
    "strong_clause": SENTENCE_PAUSE_MS, "sentence": SENTENCE_PAUSE_MS, "dialogue": DIALOGUE_PAUSE_MS,
    "paragraph": PARAGRAPH_PAUSE_MS, "emotional_beat": EMOTIONAL_BEAT_PAUSE_MS, "hard_cut": CONTINUATION_PAUSE_MS}
_OPEN_QUOTES = frozenset('“‘「『')
_CLOSE_QUOTES = frozenset('”’」』')
_SENTENCE = frozenset('.?!…。！？ฯ')
_STRONG_CLAUSE = frozenset(';:；：')
_WEAK_CLAUSE = frozenset(',，、')

# These phrases introduce the clause that follows. A chunk must not end with
# one of them alone; doing so creates an unnatural pause before its payload.
# Keep this short, explicit and testable rather than trying to infer grammar.
LEADING_CONNECTIVE_PHRASES = (
    "ทันใดนั้น", "หลังจากนั้น", "ต่อมา", "จากนั้น", "ในที่สุด",
    "อย่างไรก็ตาม", "เพราะฉะนั้น", "ดังนั้น", "แต่แล้ว",
)

# A narrow, explicit continuation set for a second pass over an otherwise
# valid whitespace boundary.  It prevents an action tail such as "แล้วก็ห่อ"
# from becoming a fresh chunk when the preceding contrast/action clause can
# safely move with it.  This is boundary choice only; it does not alter pause
# policy or try to parse Thai grammar generally.
ACTION_CHAIN_NEXT_PHRASES = ("แล้วก็", "และก็", "แล้วเขาก็", "จากนั้นเขา", "ก่อนจะ")
ACTION_CHAIN_CLAUSE_PHRASES = ("แต่เขาก็", "แล้วเขาก็", "จากนั้นเขา", "ก่อนจะ")

# Used only when an otherwise-final chunk can be split safely. These phrases
# signal that the remainder is a closing narrative unit.
CONCLUDING_LEADING_PHRASES = ("หลังจาก", "ในที่สุด")

@dataclass(frozen=True)
class ChunkResult:
    index: int
    text: str
    char_count: int
    boundary_type: str
    pause_after_ms: int
    paragraph_index: int
    dialogue: bool
    def to_dict(self) -> dict: return asdict(self)

def _paragraph_at(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1

def _is_emotional_beat(text: str) -> bool:
    """Narrow, explainable rule; intentionally no model or sentiment service."""
    core = text.strip().strip('“”"')
    return len(core) <= 48 and (core.startswith("กลายเป็นว่า") or core.startswith("นั่นเอง") or core.endswith("นั่นเอง"))

def _ends_with_leading_connective(text: str) -> bool:
    return text.rstrip().endswith(LEADING_CONNECTIVE_PHRASES)

def _closing_split(text: str, start: int, end: int) -> int | None:
    """Return a safe split before a final closing phrase, if one is present."""
    if end != len(text):
        return None
    for phrase in CONCLUDING_LEADING_PHRASES:
        pos = text.rfind(phrase, start + 1, end)
        if pos <= start or not text[pos - 1].isspace():
            continue
        if pos - start >= 16:
            return pos
    return None

def _boundary_candidates(text: str, start: int, end: int) -> list[tuple[int, str, int, bool]]:
    candidates = []
    quote_depth = 0
    for char in text[:start]:
        if char in _OPEN_QUOTES: quote_depth += 1
        elif char in _CLOSE_QUOTES and quote_depth: quote_depth -= 1
    i = start
    while i < end:
        char, pos = text[i], i + 1
        if char in _OPEN_QUOTES: quote_depth += 1
        elif char in _CLOSE_QUOTES and quote_depth:
            quote_depth -= 1
            if quote_depth == 0:
                while pos < end and text[pos].isspace(): pos += 1
                candidates.append((pos, "dialogue", 6, True))
        if char == "\n":
            while pos < end and text[pos].isspace(): pos += 1
            candidates.append((pos, "paragraph", 7, False))
        elif quote_depth and (char in _SENTENCE or char in _STRONG_CLAUSE or char in _WEAK_CLAUSE or char.isspace()):
            while pos < end and text[pos].isspace(): pos += 1
            # An overlong quotation may split only at a deterministic phrase boundary.
            candidates.append((pos, "dialogue", 6, True))
        elif quote_depth == 0 and char in _SENTENCE:
            while pos < end and text[pos].isspace(): pos += 1
            candidates.append((pos, "sentence", 5, False))
        elif quote_depth == 0 and char in _STRONG_CLAUSE:
            while pos < end and text[pos].isspace(): pos += 1
            candidates.append((pos, "strong_clause", 4, False))
        elif quote_depth == 0 and char in _WEAK_CLAUSE:
            while pos < end and text[pos].isspace(): pos += 1
            candidates.append((pos, "weak_clause", 3, False))
        elif quote_depth == 0 and char.isspace():
            while pos < end and text[pos].isspace(): pos += 1
            candidates.append((pos, "continuation", 2, False))
        i += 1
    return [item for item in candidates if start < item[0] <= end]

def _hard_cut(text: str, start: int, limit: int) -> int:
    for pos in range(limit, start, -1):
        if text[pos - 1].isspace(): return pos
    cut = limit
    while cut > start and cut < len(text) and unicodedata.combining(text[cut]): cut -= 1
    return cut if cut > start else limit

def _safe_hard_cut(text: str, start: int, limit: int) -> int:
    """Use the normal fallback, but never leave a connective as the tail."""
    cut = _hard_cut(text, start, limit)
    piece = text[start:cut]
    if not _ends_with_leading_connective(piece):
        return cut
    for phrase in LEADING_CONNECTIVE_PHRASES:
        if piece.rstrip().endswith(phrase):
            phrase_start = text.rfind(phrase, start, cut)
            if phrase_start > start:
                return phrase_start
    return cut

def _rebalance_action_chain(text: str, start: int, candidate: tuple[int, str, int, bool],
                            candidates: list[tuple[int, str, int, bool]]) -> tuple[int, str, int, bool] | None:
    """Move a split before the clause that owns an upcoming action tail."""
    cut = candidate[0]
    if not text[cut:].lstrip().startswith(ACTION_CHAIN_NEXT_PHRASES):
        return None
    earlier = [item for item in candidates if start < item[0] < cut]
    for item in reversed(earlier):
        if text[item[0]:cut].lstrip().startswith(ACTION_CHAIN_CLAUSE_PHRASES):
            return item
    return None

def semantic_chunks(text: str, target: int = 100, hard_max: int = 120) -> list[ChunkResult]:
    """Preserve every source character; hard_max is a safety limit, not a target."""
    if target < 1 or hard_max < target: raise ValueError("invalid chunk limits")
    rows, start = [], 0
    while start < len(text):
        end = min(len(text), start + hard_max)
        closing_split = _closing_split(text, start, end)
        if closing_split is not None:
            cut, kind, dialogue = closing_split, "sentence", False
        elif end == len(text):
            # End of a paragraph/passage is a real narrative boundary, never a
            # continuation even if the source omitted terminal punctuation.
            cut, kind, dialogue = end, "sentence", False
        else:
            candidates = _boundary_candidates(text, start, end)
            candidates = [item for item in candidates if not _ends_with_leading_connective(text[start:item[0]])]
            if candidates:
                chosen = max(candidates, key=lambda item: (item[2], item[0]))
                chosen = _rebalance_action_chain(text, start, chosen, candidates) or chosen
                cut, kind, _priority, dialogue = chosen
            else: cut, kind, dialogue = _safe_hard_cut(text, start, end), "hard_cut", False
        piece = text[start:cut]
        if _is_emotional_beat(piece): kind = "emotional_beat"
        rows.append(ChunkResult(len(rows)+1, piece, len(piece), kind, BOUNDARY_PAUSES_MS[kind],
            _paragraph_at(text, start), dialogue or any(c in _OPEN_QUOTES or c in _CLOSE_QUOTES for c in piece)))
        start = cut
    assert "".join(row.text for row in rows) == text
    assert all(row.char_count <= hard_max for row in rows)
    return rows

def chunk_text(text: str, target: int = 300, hard_max: int = 360) -> list[str]:
    """Legacy API returning only text chunks."""
    return [row.text for row in semantic_chunks(text, target, hard_max)]

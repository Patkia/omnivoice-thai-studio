"""Conservative, evidence-based pronunciation generation preferences.

Policies here may adjust generation conditioning, never canonical/spoken text.
They are best-effort preferences, not pronunciation guarantees.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PronunciationPolicyDecision:
    reference_conditioning: bool
    policy_id: str | None = None
    reason: str | None = None


def apply_pronunciation_policy(spoken_text: str, *, reference_conditioning: bool) -> PronunciationPolicyDecision:
    """Apply conservative preferences supported by human listening evidence."""
    if "เซเรโนอา" in spoken_text and reference_conditioning:
        return PronunciationPolicyDecision(
            reference_conditioning=False,
            policy_id="serenoa_prefer_no_reference_v1",
            reason="human-approved 0070 pronunciation; context-dependent best effort",
        )
    return PronunciationPolicyDecision(reference_conditioning=reference_conditioning)

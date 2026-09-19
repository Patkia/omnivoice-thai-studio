"""Generic guards for rejecting empty or non-audible generated waveforms."""
from __future__ import annotations

import numpy as np


def validate_audible_audio(audio: np.ndarray) -> dict[str, float]:
    """Raise ``RuntimeError`` when a waveform is empty, silent, or DC-dominated.

    The DC/zero-crossing guard catches malformed outputs which have a non-zero
    PCM peak but no speech-like alternating signal. Thresholds are conservative
    and intentionally independent of any particular word, voice, or filename.
    """
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0 or not np.isfinite(samples).all():
        raise RuntimeError("model ส่งกลับเสียงว่างหรือไม่ใช่ตัวเลข")
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples * samples)))
    if peak < 1e-4 or rms < 1e-5:
        raise RuntimeError("model ส่งกลับเสียงเงียบ")
    mean = float(np.mean(samples))
    centered = samples - mean
    centered_rms = float(np.sqrt(np.mean(centered * centered)))
    crossings = float(np.mean(samples[:-1] * samples[1:] < 0)) if samples.size > 1 else 0.0
    dc_ratio = abs(mean) / max(rms, 1e-12)
    # A speech waveform normally crosses zero repeatedly.  Require both a
    # dominant DC component and near-zero crossings before rejecting, avoiding
    # false positives for quiet/low-pitch speech.
    if dc_ratio >= 0.80 and crossings < 0.005:
        raise RuntimeError("model ส่งกลับสัญญาณ DC-dominated ที่ไม่ audible")
    return {"peak": peak, "rms": rms, "mean": mean,
            "centered_rms": centered_rms, "zero_crossing_rate": crossings,
            "dc_ratio": dc_ratio}

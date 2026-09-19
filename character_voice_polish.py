"""Small deterministic, conservative DSP used only by Mission 21's Deku listening POC."""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

OUTPUT_PEAK = 10 ** (-1.0 / 20.0)
LOW_MID_CUTOFF_HZ = 250.0
LOW_MID_MIX = 0.12
REVERB_PRE_DELAY_MS = 17.0
REVERB_TAPS_MS = (29.0, 53.0, 87.0, 131.0, 191.0)
REVERB_TAP_GAINS = (0.085, 0.060, 0.040, 0.025, 0.015)
REVERB_WET = 0.12


def wav_metadata(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        result = {
            "sample_rate": handle.getframerate(), "channels": handle.getnchannels(),
            "sample_width": handle.getsampwidth(), "frames": handle.getnframes(),
        }
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    if rate != result["sample_rate"]:
        raise RuntimeError("soundfile and WAV sample rates disagree")
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    return {
        **result,
        "duration_seconds": round(len(audio) / rate, 3),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 3),
        "clipping_detected": bool(peak >= 1.0),
    }


def render_resonance_variant(source: Path, destination: Path, *, body_mix: float,
                             pre_delay_ms: float, decay_ms: float, wet: float) -> dict:
    """Render deterministic low-mid/room resonance without changing pitch, speed, or dynamics."""
    before = wav_metadata(source)
    if before["channels"] != 1 or before["sample_width"] != 2:
        raise RuntimeError("Mission 21 resonant POC expects mono PCM_16 source WAV")
    if not (0.0 <= body_mix <= 0.30 and 0.0 <= wet <= 0.30 and decay_ms > 0.0 and pre_delay_ms >= 0.0):
        raise ValueError("resonance parameters fall outside conservative bounds")
    audio, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    mono = audio[:, 0]
    sos = butter(2, LOW_MID_CUTOFF_HZ, btype="lowpass", fs=sample_rate, output="sos")
    body = sosfilt(sos, mono).astype(np.float32)
    equalized = mono + body_mix * body

    pre_delay = round(sample_rate * pre_delay_ms / 1000)
    tap_delays_ms = tuple(round(decay_ms * portion, 3) for portion in (0.13, 0.28, 0.47, 0.70, 1.0))
    tap_samples = [pre_delay + round(sample_rate * ms / 1000) for ms in tap_delays_ms]
    tail = np.zeros(len(equalized) + max(tap_samples), dtype=np.float32)
    for offset, gain in zip(tap_samples, REVERB_TAP_GAINS):
        tail[offset:offset + len(equalized)] += equalized * gain
    mixed = np.concatenate((equalized, np.zeros(len(tail) - len(equalized), dtype=np.float32))) + wet * tail
    peak_before_guard = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    gain = min(1.0, OUTPUT_PEAK / peak_before_guard) if peak_before_guard else 1.0
    rendered = (mixed * gain).reshape(-1, 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, rendered, sample_rate, subtype="PCM_16")
    after = wav_metadata(destination)
    if after["clipping_detected"]:
        raise RuntimeError("resonant processing produced clipping")
    return {
        "source": str(source), "output": str(destination), "before": before, "after": after,
        "processing": {
            "pitch_shift": "none", "time_stretch": "none", "compression": "none",
            "eq": {"type": "low-mid body shelf approximation", "cutoff_hz": LOW_MID_CUTOFF_HZ, "mix": body_mix},
            "reverb": {"type": "deterministic early-reflection room", "pre_delay_ms": pre_delay_ms,
                       "tap_delays_ms": list(tap_delays_ms), "tap_gains": list(REVERB_TAP_GAINS),
                       "decay_ms": decay_ms, "wet": wet, "dry": 1.0},
            "peak_guard": {"target_peak_dbfs": -1.0, "gain_linear": round(gain, 8),
                           "input_peak_before_guard_dbfs": round(20 * math.log10(max(peak_before_guard, 1e-12)), 3)},
        },
    }


def render_subtle_resonance(source: Path, destination: Path) -> dict:
    """Retain Mission 21's exact conservative POC settings."""
    return render_resonance_variant(source, destination, body_mix=LOW_MID_MIX,
                                    pre_delay_ms=REVERB_PRE_DELAY_MS,
                                    decay_ms=max(REVERB_TAPS_MS), wet=REVERB_WET)

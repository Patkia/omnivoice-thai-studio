"""Conservative, file-only loudness matching for a limited listening POC."""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

ACTIVE_THRESHOLD_DBFS = -45.0
MAX_ATTENUATION_DB = 2.0


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _metrics(audio: np.ndarray) -> dict:
    samples = np.asarray(audio, dtype=np.float32)
    magnitude = np.max(np.abs(samples), axis=1) if samples.ndim == 2 else np.abs(samples)
    active = samples[magnitude > 10 ** (ACTIVE_THRESHOLD_DBFS / 20.0)]
    active_rms = float(np.sqrt(np.mean(active * active))) if len(active) else 0.0
    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
    return {"rms_dbfs": round(_dbfs(rms), 3), "active_rms_dbfs": round(_dbfs(active_rms), 3),
            "peak_dbfs": round(_dbfs(float(np.max(np.abs(samples)))), 3),
            "active_sample_percent": round(100.0 * len(active) / len(samples), 3) if len(samples) else 0.0,
            "integrated_loudness_lufs": None}


def inspect_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as source:
        fmt = {"sample_rate": source.getframerate(), "channels": source.getnchannels(),
               "sample_width": source.getsampwidth(), "frames": source.getnframes()}
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    if rate != fmt["sample_rate"]:
        raise RuntimeError("soundfile and WAV sample rates disagree")
    return {**fmt, **_metrics(audio)}


def conservative_gains(paths: list[Path]) -> list[float]:
    """Match active-speech RMS down to the quietest source, never amplifying."""
    levels = [inspect_wav(path)["active_rms_dbfs"] for path in paths]
    target = min(levels)
    return [round(max(-MAX_ATTENUATION_DB, min(0.0, target - level)), 3) for level in levels]


def normalize_chunks(paths: list[Path], output_dir: Path) -> list[dict]:
    if not paths:
        raise ValueError("at least one chunk is required")
    source_metadata = [inspect_wav(path) for path in paths]
    baseline = (source_metadata[0]["sample_rate"], source_metadata[0]["channels"], source_metadata[0]["sample_width"])
    if any((item["sample_rate"], item["channels"], item["sample_width"]) != baseline for item in source_metadata[1:]):
        raise RuntimeError("chunk WAV has mismatched sample rate/channel/sample width")
    gains = conservative_gains(paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for source, before, gain_db in zip(paths, source_metadata, gains):
        audio, rate = sf.read(source, dtype="float32", always_2d=True)
        adjusted = audio * (10 ** (gain_db / 20.0))
        if float(np.max(np.abs(adjusted))) > 1.0:
            raise RuntimeError("normalization would clip")
        destination = output_dir / source.name
        sf.write(destination, adjusted, rate, subtype="PCM_16")
        after = inspect_wav(destination)
        rows.append({"source": str(source), "normalized": str(destination), "gain_db": gain_db,
                     "before": before, "after": after, "clipping": False})
    return rows

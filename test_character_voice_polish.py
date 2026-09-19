from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from character_voice_polish import render_resonance_variant, render_subtle_resonance


def metadata(*, channels: int = 1, sample_width: int = 2, clipping: bool = False) -> dict:
    return {
        "sample_rate": 24000, "channels": channels, "sample_width": sample_width,
        "frames": 2400, "duration_seconds": 0.1, "peak_dbfs": -1.0,
        "clipping_detected": clipping,
    }


class CharacterVoicePolishTests(unittest.TestCase):
    def test_resonance_is_deterministic_pcm16_and_clipping_safe(self):
        source, first, second = Path("source.wav"), Path("first.wav"), Path("second.wav")
        audio = (0.45 * np.sin(2 * np.pi * 180 * np.arange(2400) / 24000)).astype("float32")[:, None]
        written: list[np.ndarray] = []

        def capture_write(_path, samples, _rate, **_kwargs):
            written.append(np.array(samples, copy=True))

        with patch("character_voice_polish.wav_metadata", side_effect=[metadata(), metadata(), metadata(), metadata()]), \
             patch("character_voice_polish.sf.read", return_value=(audio, 24000)), \
             patch("character_voice_polish.sf.write", side_effect=capture_write):
            first_result = render_subtle_resonance(source, first)
            second_result = render_subtle_resonance(source, second)
        self.assertEqual(len(written), 2)
        self.assertTrue(np.array_equal(written[0], written[1]))
        self.assertFalse(first_result["after"]["clipping_detected"])
        self.assertEqual(first_result["processing"]["pitch_shift"], "none")
        self.assertEqual(first_result["processing"]["time_stretch"], "none")
        self.assertEqual(first_result["processing"]["compression"], "none")

    def test_rejects_non_pcm16_or_stereo_source(self):
        with patch("character_voice_polish.wav_metadata", return_value=metadata(sample_width=4)):
            with self.assertRaises(RuntimeError):
                render_subtle_resonance(Path("float.wav"), Path("out.wav"))
        with patch("character_voice_polish.wav_metadata", return_value=metadata(channels=2)):
            with self.assertRaises(RuntimeError):
                render_subtle_resonance(Path("stereo.wav"), Path("out.wav"))

    def test_parameter_bounds_prevent_aggressive_settings(self):
        with patch("character_voice_polish.wav_metadata", return_value=metadata()):
            with self.assertRaises(ValueError):
                render_resonance_variant(Path("source.wav"), Path("out.wav"), body_mix=0.31,
                                         pre_delay_ms=20.0, decay_ms=400.0, wet=0.20)


if __name__ == "__main__":
    unittest.main()

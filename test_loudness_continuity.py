from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from loudness_continuity import normalize_chunks


def meta(level: float, *, channels: int = 1) -> dict:
    return {"sample_rate": 24000, "channels": channels, "sample_width": 2, "frames": 2400,
            "rms_dbfs": level, "active_rms_dbfs": level, "peak_dbfs": -1.0,
            "active_sample_percent": 100.0, "integrated_loudness_lufs": None}


class LoudnessContinuityTests(unittest.TestCase):
    def test_attenuation_only_preserves_format_and_prevents_clipping(self):
        loud, quiet = Path("loud.wav"), Path("quiet.wav")
        after_loud, after_quiet = meta(-10.0), meta(-20.0)
        with patch("loudness_continuity.inspect_wav", side_effect=[meta(-10.0), meta(-20.0),
                                                                     meta(-10.0), meta(-20.0),
                                                                     after_loud, after_quiet]), \
             patch("loudness_continuity.sf.read", side_effect=[
                 (np.full((2400, 1), 0.7, dtype="float32"), 24000),
                 (np.full((2400, 1), 0.3, dtype="float32"), 24000),
             ]), patch("loudness_continuity.sf.write") as write, \
             patch("loudness_continuity.Path.mkdir"):
            rows = normalize_chunks([loud, quiet], Path("normalized"))
        self.assertLess(rows[0]["gain_db"], 0.0)
        self.assertEqual(rows[1]["gain_db"], 0.0)
        self.assertEqual(rows[0]["after"]["sample_rate"], 24000)
        self.assertEqual(write.call_count, 2)

    def test_format_mismatch_is_rejected(self):
        with patch("loudness_continuity.inspect_wav", side_effect=[meta(-10.0), meta(-10.0, channels=2)]):
            with self.assertRaises(RuntimeError):
                normalize_chunks([Path("mono.wav"), Path("stereo.wav")], Path("normalized"))


if __name__ == "__main__":
    unittest.main()

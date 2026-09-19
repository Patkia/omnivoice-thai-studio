import unittest

import numpy as np

from audio_validation import validate_audible_audio


class AudibleWaveformValidationTests(unittest.TestCase):
    def test_accepts_speech_like_signal(self):
        t = np.arange(24000, dtype=np.float32) / 24000
        stats = validate_audible_audio(0.2 * np.sin(2 * np.pi * 220 * t))
        self.assertGreater(stats["zero_crossing_rate"], 0.005)

    def test_rejects_digital_silence(self):
        with self.assertRaisesRegex(RuntimeError, "เงียบ"):
            validate_audible_audio(np.zeros(2400, dtype=np.float32))

    def test_rejects_nonzero_dc_dominated_artifact(self):
        # Mirrors the observed malformed artifact: large DC offset with only
        # a very slow, non-audible drift and almost no zero crossings.
        x = -0.8 + np.linspace(0.0, 0.04, 24000, dtype=np.float32)
        with self.assertRaisesRegex(RuntimeError, "DC-dominated"):
            validate_audible_audio(x)


if __name__ == "__main__":
    unittest.main()

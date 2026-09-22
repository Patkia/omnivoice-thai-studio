from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from tools.hf_voice_audition import (
    Candidate,
    create_runtime_24k,
    extract_audio_src,
    hard_reject,
    instruction_for,
    license_from_info,
    score_candidate,
    wav_properties,
)


class _Info:
    def __init__(self, tags=None, card_data=None):
        self.tags = tags or []
        self.card_data = card_data or {}


class HfVoiceAuditionTests(unittest.TestCase):
    def test_extract_audio_src_supports_viewer_list_shape(self):
        value = [{"src": "https://example.test/a.wav", "type": "audio/wav"}]
        self.assertEqual(extract_audio_src(value), "https://example.test/a.wav")

    def test_license_requires_clear_license(self):
        self.assertEqual(license_from_info(_Info(tags=["license:cc-by-4.0"]))[1], "LICENSE_OK")
        self.assertEqual(license_from_info(_Info(tags=[]))[1], "LICENSE_UNCLEAR")
        self.assertEqual(license_from_info(_Info(tags=["license:other"]))[1], "LICENSE_UNCLEAR")

    def test_runtime_derivative_is_pcm16_24k_mono_without_gain_normalization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master = root / "master.wav"
            runtime = root / "runtime.wav"
            sr = 48000
            t = np.arange(sr * 6, dtype=np.float64) / sr
            tone = 0.2 * np.sin(2 * np.pi * 220 * t)
            stereo = np.column_stack((tone, tone * 0.8))
            sf.write(master, stereo, sr, subtype="PCM_16")
            before = wav_properties(master)
            after = create_runtime_24k(master, runtime)
            self.assertEqual(after["sample_rate"], 24000)
            self.assertEqual(after["channels"], 1)
            self.assertEqual(after["bit_depth"], 16)
            self.assertAlmostEqual(before["duration"], after["duration"], places=2)
            self.assertLess(after["peak"], 0.25)

    def test_rpg_scoring_rewards_expressive_metadata_and_marks_distinctness_human(self):
        c = Candidate(
            repo="repo", config="clean", split="dev", row_idx=0, speaker_id="1",
            source_id="id", source_url="https://example.test/a.wav", source_file="a.wav",
            transcript="A natural sentence for reference.", license="cc-by-4.0",
            license_status="LICENSE_OK", license_source="tags",
            enrichment={
                "gender": "male",
                "speech_monotony": "expressive and animated",
                "noise": "very clear",
                "reverberation": "very close-sounding",
            },
            duration=9.0, clipping=False, validation="PASS",
        )
        c.scores = score_candidate(c, gender="male", role="young noble scholar", notes="clear RPG voice")
        self.assertGreaterEqual(c.scores["rpg_character_presence"], 3)
        self.assertGreaterEqual(c.scores["dramatic_dialogue_suitability"], 3)
        self.assertIn("distinctness_check=HUMAN_REQUIRED", c.notes)
        self.assertEqual(hard_reject(c), "")

    def test_instruction_uses_only_supported_tokens(self):
        self.assertEqual(
            instruction_for("male", "young_adult", "scholar noble", "RPG voice", 2),
            "male, young adult, moderate pitch",
        )

    def test_hard_rejects_wrong_duration_and_clipping(self):
        c = Candidate(
            repo="repo", config="clean", split="dev", row_idx=0, speaker_id="1",
            source_id="id", source_url="u", source_file="a.wav", transcript="text",
            license="cc-by-4.0", license_status="LICENSE_OK", license_source="tags",
            duration=2.0, clipping=False, validation="PASS",
        )
        self.assertEqual(hard_reject(c), "DURATION_OUT_OF_RANGE")
        c.duration = 8.0
        c.clipping = True
        self.assertEqual(hard_reject(c), "CLIPPING")


if __name__ == "__main__":
    unittest.main()

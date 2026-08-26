import json
import unittest
from pathlib import Path

from run_female_voice_palette import cases
from thai_speech_normalizer import normalize_text


class FemaleVoicePaletteTests(unittest.TestCase):
    def test_candidate_count_and_thai_only_text(self):
        config = json.loads(Path("female_voice_candidates.json").read_text(encoding="utf-8"))
        test = json.loads(Path("female_voice_palette_test.json").read_text(encoding="utf-8"))
        result = cases(config, test)
        self.assertEqual(len(result), 12)
        self.assertEqual({x["archetype"] for x in result}, {"bright_young_female", "warm_young_female", "cute_teen_female"})
        self.assertTrue(all(normalize_text(x["source_text"]).thai_only_gate_passed for x in result))

    def test_human_approved_baseline_is_not_an_output_target(self):
        baseline = Path("output/engine_candidate/voices/young_female_dialogue_1_0.wav")
        self.assertTrue(baseline.exists())
        result = cases(json.loads(Path("female_voice_candidates.json").read_text(encoding="utf-8")), json.loads(Path("female_voice_palette_test.json").read_text(encoding="utf-8")))
        self.assertNotIn("output/engine_candidate/voices/young_female_dialogue_1_0.wav", {x["output"] for x in result})


if __name__ == "__main__":
    unittest.main()

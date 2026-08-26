import json
import unittest
from pathlib import Path

from run_final_validation import profile_index
from thai_speech_normalizer import normalize_text


class FinalValidationTests(unittest.TestCase):
    def test_registry_and_scene_are_complete(self):
        registry = json.loads(Path("approved_voice_profiles.json").read_text(encoding="utf-8"))
        scene = json.loads(Path("mock_game_scene.json").read_text(encoding="utf-8"))
        profiles = profile_index(registry)
        self.assertEqual(len(scene["lines"]), 10)
        self.assertTrue(all(line["profile_key"] in profiles for line in scene["lines"]))
        self.assertTrue(all(normalize_text(line["text"]).thai_only_gate_passed for line in scene["lines"]))

    def test_narrator_is_not_marked_approved(self):
        registry = json.loads(Path("approved_voice_profiles.json").read_text(encoding="utf-8"))
        self.assertNotIn("narrator", registry["approved"])
        self.assertEqual(registry["usable"]["narrator"]["status"], "pending final human speed selection")


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import unittest
from pathlib import Path

from tts import TtsInputError, cache_key, list_voices, prepare_text, resolve_voice, validate_gate


class TtsCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.registry = json.loads((self.root / "approved_voice_profiles.json").read_text(encoding="utf-8"))

    def test_required_aliases_resolve_from_registry(self):
        aliases = ["narrator", "young_male", "deep_male", "bright_female", "young_female", "cute_teen_soft", "cute_teen_bright", "warm_female_1", "warm_female_2"]
        resolved = {alias: resolve_voice(alias, self.registry) for alias in aliases}
        self.assertEqual(resolved["bright_female"]["source_candidate"], "bright_02")
        self.assertEqual(resolved["narrator"]["speed"], 0.94)

    def test_pipeline_applies_dictionary_and_gate(self):
        prepared = prepare_text("ผมกำลังหั่นแอปเปิลอยู่ในครัว", self.root / "pronunciation_dictionary.json")
        self.assertEqual(prepared["spoken"], "ผมกำลังหั่นแอ๊ปเปิ้ลอยู่ในครัว")
        self.assertTrue(prepared["gate"].thai_only_gate_passed)

    def test_promoted_profiles_have_exact_human_selected_settings(self):
        expected = {
            "mipha_style": ("female, young adult, high pitch", 0.92, 19102),
            "cute_young_female": ("female, young adult, high pitch", 1.00, 19102),
            "ancient_deep_male": ("male, middle-aged, very low pitch", 0.68, 20105),
        }
        for alias, (instruction, speed, seed) in expected.items():
            voice = resolve_voice(alias, self.registry)
            self.assertEqual((voice["voice_instruction"], voice["speed"], voice["seed"]), (instruction, speed, seed))
        self.assertEqual(resolve_voice("narrator", self.registry)["seed"], 15015)

    def test_list_voices_includes_promoted_profiles_and_seed_changes_cache_identity(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            list_voices(self.registry)
        self.assertTrue(all(alias in output.getvalue() for alias in ("mipha_style", "cute_young_female", "ancient_deep_male")))
        payload = {"text": "ข้อความ", "voice_instruction": "female, young adult, high pitch", "speed": 0.92}
        self.assertNotEqual(cache_key(payload), cache_key({**payload, "seed": 19102}))

    def test_gate_explains_unresolved_latin_text(self):
        prepared = prepare_text("ข้อความ Zebra", self.root / "pronunciation_dictionary.json")
        with self.assertRaisesRegex(TtsInputError, "normalization rule หรือ pronunciation dictionary"):
            validate_gate(prepared)

if __name__ == "__main__":
    unittest.main()

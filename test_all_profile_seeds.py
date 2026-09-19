import unittest

from studio_engine_adapter import load_voice_aliases, preview_text, resolve_generation_seed


class AllProfileSeedTests(unittest.TestCase):
    def test_every_alias_resolves_to_a_fixed_integer_seed(self):
        aliases = load_voice_aliases()
        self.assertTrue(aliases)
        for alias in aliases:
            voice = preview_text("ข้อความทดสอบ", alias)["voice"]
            self.assertIsInstance(voice.get("seed"), int, alias)
            self.assertEqual(resolve_generation_seed(voice, None), voice["seed"])


if __name__ == "__main__":
    unittest.main()

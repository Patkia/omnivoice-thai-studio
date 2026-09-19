import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from tts_runtime import PersistentTtsSession


class PersistentSessionSeedTests(unittest.TestCase):
    def test_reference_prompt_is_prepared_once_and_reused(self):
        session = PersistentTtsSession("test-model", "test-revision")
        session.model = MagicMock()
        prompt = object()
        session.model.create_voice_clone_prompt.return_value = prompt
        first, first_meta = session.prepare_voice_clone_prompt(
            "reference.wav", "ข้อความอ้างอิง", prompt_key="same-reference",
        )
        second, second_meta = session.prepare_voice_clone_prompt(
            "reference.wav", "ข้อความอ้างอิง", prompt_key="same-reference",
        )
        self.assertIs(first, prompt)
        self.assertIs(second, prompt)
        session.model.create_voice_clone_prompt.assert_called_once_with(
            "reference.wav", ref_text="ข้อความอ้างอิง", preprocess_prompt=True,
        )
        self.assertFalse(first_meta["reference_prompt_cache_hit"])
        self.assertTrue(second_meta["reference_prompt_cache_hit"])
        self.assertEqual(session.reference_prompt_prep_count, 1)

    def test_reference_prompt_and_instruction_are_used_together(self):
        session = PersistentTtsSession("test-model", "test-revision")
        session.model = MagicMock()
        session.model.generate.return_value = [np.array([0.25, -0.25], dtype=np.float32)]
        prompt = object()
        session.generate(
            "ข้อความ", "female, young adult, moderate pitch", 1.0, 32,
            seed=15016, voice_clone_prompt=prompt,
        )
        session.model.generate.assert_called_once_with(
            "ข้อความ", instruct="female, young adult, moderate pitch",
            speed=1.0, num_step=32, voice_clone_prompt=prompt,
        )

    def test_reference_first_uses_prompt_without_descriptive_instruction(self):
        session = PersistentTtsSession("test-model", "test-revision")
        session.model = MagicMock()
        session.model.generate.return_value = [np.array([0.25, -0.25], dtype=np.float32)]
        prompt = object()
        session.generate(
            "ข้อความ", None, 1.0, 32, seed=15032, voice_clone_prompt=prompt,
            generation_mode="reference_first", language="Thai",
            denoise=True, postprocess_output=True,
        )
        session.model.generate.assert_called_once_with(
            "ข้อความ", speed=1.0, num_step=32, voice_clone_prompt=prompt,
            language="Thai", denoise=True, postprocess_output=True,
        )
        self.assertNotIn("instruct", session.model.generate.call_args.kwargs)

    def test_reference_first_fails_closed_without_prompt(self):
        session = PersistentTtsSession("test-model", "test-revision")
        session.model = MagicMock()
        with self.assertRaisesRegex(ValueError, "requires voice_clone_prompt"):
            session.generate("ข้อความ", None, 1.0, 32, generation_mode="reference_first")
        session.model.generate.assert_not_called()

    def test_optional_seed_is_applied_inside_generate(self):
        session = PersistentTtsSession("test-model", "test-revision")
        session.model = MagicMock()
        session.model.generate.return_value = [np.array([0.25, -0.25], dtype=np.float32)]
        with patch("tts_runtime.fix_random_seed") as seed_fn:
            _audio, metadata = session.generate("ข้อความ", "male", 1.0, 32, seed=15015)
        seed_fn.assert_called_once_with(15015)
        self.assertEqual(metadata["seed"], 15015)

    def test_default_path_does_not_set_a_seed(self):
        session = PersistentTtsSession("test-model", "test-revision")
        session.model = MagicMock()
        session.model.generate.return_value = [np.array([0.25, -0.25], dtype=np.float32)]
        with patch("tts_runtime.fix_random_seed") as seed_fn:
            _audio, metadata = session.generate("ข้อความ", "male", 1.0, 32)
        seed_fn.assert_not_called()
        self.assertIsNone(metadata["seed"])


if __name__ == "__main__":
    unittest.main()

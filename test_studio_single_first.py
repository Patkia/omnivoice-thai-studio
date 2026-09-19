"""No-model tests for the Studio single-first routing policy."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from studio_generation import generate_studio_request


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def generate(self, text, alias, speed, steps, output, force, **kwargs):
        self.calls.append({"text": text, "alias": alias, "speed": speed,
                           "steps": steps, "output": output, "force": force,
                           **kwargs})
        return {"cache_hit": False, "output": output, "inference_seconds": 0.0}


class StudioSingleFirstTests(unittest.TestCase):
    def test_up_to_500_characters_use_exactly_one_application_request(self):
        for length in (120, 121, 247, 500):
            with self.subTest(length=length):
                adapter = FakeAdapter()
                with patch("studio_generation.generate_long") as long_path, \
                     patch("long_text_batch.semantic_chunks") as chunker, \
                     patch("long_text_batch.merge") as merger:
                    result = generate_studio_request(
                        adapter, "ก" * length, "bright_female", 1.0, 32,
                        Path("single.wav"), False)
                self.assertFalse(result["long_text"])
                self.assertEqual(result["application_generation_count"], 1)
                self.assertEqual(len(adapter.calls), 1)
                self.assertTrue(adapter.calls[0]["single_input"])
                long_path.assert_not_called()
                chunker.assert_not_called()
                merger.assert_not_called()

    def test_501_characters_use_existing_long_text_fallback(self):
        adapter = FakeAdapter()
        expected = {"cancelled": False, "inference_seconds": 1.0}
        with patch("studio_generation.generate_long", return_value=expected.copy()) as long_path:
            result = generate_studio_request(
                adapter, "ก" * 501, "bright_female", 1.0, 32,
                Path("long.wav"), False)
        self.assertTrue(result["long_text"])
        self.assertEqual(adapter.calls, [])
        long_path.assert_called_once()

    def test_single_first_is_profile_independent(self):
        for alias, speed in (("bright_female", 1.0), ("ancient_deep_male", 0.68)):
            with self.subTest(alias=alias):
                adapter = FakeAdapter()
                result = generate_studio_request(
                    adapter, "ข้อความทดสอบ", alias, speed, 32,
                    Path(f"{alias}.wav"), False)
                self.assertFalse(result["long_text"])
                self.assertEqual(adapter.calls[0]["alias"], alias)
                self.assertEqual(adapter.calls[0]["speed"], speed)
                self.assertTrue(adapter.calls[0]["single_input"])

    def test_instruction_override_is_forwarded_without_changing_routing(self):
        adapter = FakeAdapter()
        generate_studio_request(
            adapter, "ข้อความทดสอบ", "bright_female", 1.0, 32,
            Path("override.wav"), False,
            instruction_override="female, young adult, moderate pitch",
        )
        self.assertEqual(len(adapter.calls), 1)
        self.assertTrue(adapter.calls[0]["single_input"])
        self.assertEqual(adapter.calls[0]["instruct_override"], "female, young adult, moderate pitch")

    def test_reference_conditioning_is_forwarded_without_instruct_fallback(self):
        adapter = FakeAdapter()
        generate_studio_request(
            adapter, "ข้อความทดสอบ", "bright_female", 1.0, 32,
            Path("reference.wav"), False,
            seed=15016,
            instruction_override="female, young adult, moderate pitch",
            reference_conditioning=True,
            reference_audio="assets/triangle-strategy/approved_voice_references/narrator_B.wav",
            reference_sha256="a" * 64,
            reference_text="ข้อความอ้างอิง",
            reference_text_sha256="b" * 64,
        )
        call = adapter.calls[0]
        self.assertTrue(call["reference_conditioning"])
        self.assertEqual(call["reference_audio"], "assets/triangle-strategy/approved_voice_references/narrator_B.wav")
        self.assertEqual(call["seed"], 15016)
        self.assertEqual(call["instruct_override"], "female, young adult, moderate pitch")


    def test_serenoa_policy_prefers_no_reference_without_changing_text(self):
        adapter = FakeAdapter()
        text = "นำทัพโดยเซเรโนอา ผู้สืบทอดตำแหน่ง"
        result = generate_studio_request(
            adapter, text, "bright_female", 1.0, 32,
            Path("serenoa.wav"), False,
            seed=15016,
            instruction_override="female, young adult, moderate pitch",
            reference_conditioning=True,
            reference_audio="assets/triangle-strategy/approved_voice_references/narrator_B.wav",
            reference_sha256="a" * 64,
            reference_text="ข้อความอ้างอิง",
            reference_text_sha256="b" * 64,
        )
        call = adapter.calls[0]
        self.assertEqual(call["text"], text)
        self.assertNotIn("reference_conditioning", call)
        self.assertEqual(result["pronunciation_policy"], "serenoa_prefer_no_reference_v1")

    def test_serenoa_policy_does_not_affect_other_text(self):
        adapter = FakeAdapter()
        generate_studio_request(
            adapter, "ข้อความทั่วไป", "bright_female", 1.0, 32,
            Path("normal.wav"), False,
            reference_conditioning=True,
            reference_audio="ref.wav", reference_sha256="a" * 64,
            reference_text="อ้างอิง", reference_text_sha256="b" * 64,
        )
        self.assertTrue(adapter.calls[0]["reference_conditioning"])

    def test_reference_first_preserves_reference_for_serenoa_and_omits_instruction(self):
        adapter = FakeAdapter()
        result = generate_studio_request(
            adapter, "นำทัพโดยเซเรโนอา ผู้สืบทอดตำแหน่ง", "narrator", 1.0, 32,
            Path("reference-first.wav"), False,
            seed=15032, generation_mode="reference_first", language="Thai",
            denoise=True, postprocess_output=True,
            reference_conditioning=True, reference_audio="ref.wav",
            reference_sha256="a" * 64, reference_text="ข้อความอ้างอิง",
            reference_text_sha256="b" * 64,
        )
        call = adapter.calls[0]
        self.assertTrue(call["reference_conditioning"])
        self.assertEqual(call["generation_mode"], "reference_first")
        self.assertNotIn("instruct_override", call)
        self.assertEqual(result["pronunciation_policy"], "reference_first_preserve_reference")


if __name__ == "__main__":
    unittest.main()

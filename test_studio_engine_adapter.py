import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from studio_engine_adapter import (StudioEngineAdapter, default_output_path, generation_cache_keys,
                                   add_paragraph_pause_cues, load_voice_aliases,
                                   preview_single_input_text, preview_text, resolve_generation_seed,
                                   validate_reference_audio)


class StudioAdapterTests(unittest.TestCase):
    def test_approved_narrator_reference_hash_and_format(self):
        metadata = validate_reference_audio(
            "assets/triangle-strategy/approved_voice_references/narrator_B.wav",
            "902230792ec5b4f0bf64510281f41e0618c3c3fb9b95de98a349d66a11924dd3",
        )
        self.assertEqual(metadata["sample_rate"], 24000)
        self.assertEqual(metadata["channels"], 1)
        self.assertEqual(metadata["sample_width"], 2)

    def test_reference_missing_and_hash_mismatch_fail_closed(self):
        with self.assertRaises(FileNotFoundError):
            validate_reference_audio(
                "assets/triangle-strategy/approved_voice_references/missing.wav", "0" * 64,
            )
        with self.assertRaisesRegex(ValueError, "SHA256"):
            validate_reference_audio(
                "assets/triangle-strategy/approved_voice_references/narrator_B.wav", "0" * 64,
            )

    def test_registry_and_preview(self):
        aliases = load_voice_aliases()
        self.assertIn("bright_female", aliases)
        result = preview_text("ผมกำลังหั่นแอปเปิลอยู่ในครัว", "bright_female")
        self.assertTrue(result["prepared"]["gate"].thai_only_gate_passed)
        self.assertIn("แอ๊ปเปิ้ล", result["prepared"]["spoken"])

    def test_filename_and_session_starts_lazy(self):
        output = default_output_path(datetime(2026, 8, 29, 12, 34, 56))
        self.assertEqual(output.name, "tts_20260829_123456.wav")
        adapter = StudioEngineAdapter()
        self.assertEqual(adapter.model_status, "MODEL_NOT_LOADED")

    def test_instruct_override_has_a_distinct_cache_identity(self):
        default, _ = generation_cache_keys({"text": "ข้อความ", "voice_instruction": "female, young adult"}, 19101)
        override, _ = generation_cache_keys({"text": "ข้อความ", "voice_instruction": "female, soft, warm"}, 19101)
        self.assertNotEqual(default, override)

    def test_reference_first_mode_has_distinct_cache_identity(self):
        legacy_payload = {
            "text": "ข้อความ", "voice_instruction": None,
            "reference_conditioning": True, "reference_sha256": "a" * 64,
        }
        reference_first_payload = {
            **legacy_payload, "generation_mode": "reference_first",
            "language": "Thai", "denoise": True, "postprocess_output": True,
        }
        legacy, _ = generation_cache_keys(legacy_payload, 15032)
        direct, _ = generation_cache_keys(reference_first_payload, 15032)
        self.assertNotEqual(legacy, direct)

    def test_voice_project_has_distinct_cache_identity(self):
        base = {"text": "ข้อความ", "voice_instruction": None,
                "generation_mode": "reference_first", "voice_project": "project-a"}
        other = {**base, "voice_project": "project-b"}
        self.assertNotEqual(generation_cache_keys(base, 15032)[0],
                            generation_cache_keys(other, 15032)[0])

    def test_reference_prompt_cache_key_is_project_namespaced(self):
        adapter = StudioEngineAdapter.__new__(StudioEngineAdapter)
        adapter.session = MagicMock()
        adapter.session.prepare_voice_clone_prompt.return_value = (object(), {})
        audio = {"sha256": "a" * 64, "path": Path("reference.wav")}
        with patch("studio_engine_adapter.validate_reference_audio", return_value=audio), \
             patch("studio_engine_adapter.validate_reference_text", return_value="b" * 64):
            adapter.prepare_reference_conditioning(
                "reference.wav", "a" * 64, "ข้อความ", "b" * 64,
                voice_project="project-a",
            )
            adapter.prepare_reference_conditioning(
                "reference.wav", "a" * 64, "ข้อความ", "b" * 64,
                voice_project="project-b",
            )
        keys = [call.kwargs["prompt_key"]
                for call in adapter.session.prepare_voice_clone_prompt.call_args_list]
        self.assertEqual(keys, [f"project-a:{'a' * 64}:{'b' * 64}",
                                f"project-b:{'a' * 64}:{'b' * 64}"])

    def test_all_profiles_have_fixed_seed_and_explicit_seed_remains_an_override(self):
        aliases = load_voice_aliases()
        for alias in aliases:
            voice = preview_text("ข้อความทดสอบ", alias)["voice"]
            self.assertIsInstance(resolve_generation_seed(voice, None), int, alias)
        promoted = preview_text("ข้อความทดสอบ", "mipha_style")["voice"]
        self.assertEqual(resolve_generation_seed(promoted, None), 19102)
        self.assertEqual(resolve_generation_seed(promoted, 15015), 15015)

    def test_single_input_pause_preparation_retains_source(self):
        source = "ข้อความย่อหน้าแรก\nข้อความก่อนสรุปอย่างยุติธรรม\nในที่สุดเรื่องราวก็จบลง"
        data = preview_single_input_text(source, "bright_female")
        prepared = data["prepared"]
        self.assertEqual(prepared["original"], source)
        self.assertEqual(prepared["normalized"], source)
        self.assertIn("ยุติธรรม…\nในที่สุด", prepared["spoken"])
        self.assertIn("ย่อหน้าแรก\nข้อความก่อน", prepared["spoken"])
        self.assertEqual(prepared["paragraph_pause_preparation"]["insertions"], 1)

    def test_paragraph_pause_rule_is_generic_and_deterministic(self):
        source = "เหตุการณ์สงบลง\nจากนั้นทุกคนจึงเดินทางกลับ"
        first = add_paragraph_pause_cues(source)
        second = add_paragraph_pause_cues(source)
        self.assertEqual(first, second)
        self.assertEqual(first, ("เหตุการณ์สงบลง…\nจากนั้นทุกคนจึงเดินทางกลับ", 1))

    def test_promoted_bright_female_values_and_second_profile_seed(self):
        bright = preview_text("ข้อความทดสอบ", "bright_female")["voice"]
        narrator = preview_text("ข้อความทดสอบ", "narrator")["voice"]
        self.assertEqual(bright["voice_instruction"], "female, young adult, high pitch")
        self.assertEqual(bright["speed"], 1.0)
        self.assertEqual(resolve_generation_seed(bright, None), 15016)
        self.assertEqual(resolve_generation_seed(narrator, None), 15015)

    def test_explicit_spoken_override_preserves_boundary_and_canonical_text(self):
        canonical = "แต่เซเรโนอากับทัพของเขา"
        spoken = "แต่เซเรโนอา กับทัพของเขา"
        prepared = preview_single_input_text(canonical, "bright_female", spoken_override=spoken)["prepared"]
        self.assertEqual(prepared["original"], canonical)
        self.assertEqual(prepared["normalized"], canonical)
        self.assertEqual(prepared["spoken"], spoken)
        start = spoken.index("เซเรโนอา") + len("เซเรโนอา") - 1
        self.assertEqual([ord(x) for x in spoken[start:start + 3]], [0x0E32, 0x20, 0x0E01])

    def test_spoken_override_cache_identity_differs(self):
        base = {"text": "เซเรโนอากับทัพ", "voice_instruction": "female, young adult, high pitch", "speed": 1.0, "steps": 32, "sample_rate": 24000, "audio_normalization": "peak -1 dBFS"}
        separated = {**base, "text": "เซเรโนอา กับทัพ"}
        self.assertNotEqual(generation_cache_keys(base, 15016)[0], generation_cache_keys(separated, 15016)[0])


if __name__ == "__main__": unittest.main()

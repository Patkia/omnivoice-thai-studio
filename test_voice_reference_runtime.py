import hashlib
import csv
import json
import unittest
import wave
from pathlib import Path

from csv_batch import CsvBatchRow, resolve_generation_config


ROOT = Path(__file__).resolve().parent
MASTER_DIR = ROOT / "assets" / "triangle-strategy" / "approved_voice_references"
RUNTIME_DIR = MASTER_DIR / "runtime_24k"
MAP_PATH = ROOT / "projects" / "triangle-strategy" / "voice_target_map.json"

MASTER_SHA256 = {
    "female_support_A.wav": "aa03f1eb023451b35f2f21360ab2ec448f507a189e1fce92b63b07d78d03dd10",
    "heroine_A.wav": "2b973234ab4d0c7d210e05130ee6b26d81f3a796ded4cf85cb91c755fcbb91cd",
    "female_alt_A.wav": "68493c8cb6cfb8a4a3507a0e44677dd4274b4177f04670687f779bdfa31649a3",
    "female_alt_B.wav": "d86c8f4bd2b95924db121213d023b784c80456f0f68fde8c60a1902f0489e7db",
    "female_alt_C.wav": "2c903622a1b3e8dc72f100a750409d150f4e966b4e08ba99dfdfc6b6870845f9",
}

RUNTIME_SHA256 = {
    "female_support_A.wav": "ecc0d8545e344c3d162658042f20d9692fd631e9a26f1a449ef79393cf6909c6",
    "heroine_A.wav": "91fbe764f48bead3d7b22928ffadb09c4b595c9d9d7b06dd2704b0a69ccbc395",
    "female_alt_A.wav": "3a0aa116fda38854e67e6932b73d8f6624e62f9093dc334cc65812ec2a9803b2",
    "female_alt_B.wav": "65a9ee00f44bb93199a3e658661dfa575ec2fc795cf2d34d2171975d979b9f65",
    "female_alt_C.wav": "f725a63d77fc5056f258ee15b3e7db2d4ddb3dc680ebda9d116c26bfb6a887dd",
}

NARRATOR_C_TEXT = (
    "ความขัดแย้งที่เกิดขึ้นนำไปสู่ชนวนสงคราม และในไม่ช้า\n"
    "ก็เกิดเป็นสงครามนองเลือดที่ยืดเยื้อกันเป็นเวลากว่าหลายปี\n"
    "ทุกชีวิตที่ถูกสังเวยไปในสงครามครั้งนี้ถูกกล่าวขานและรู้จักกันในชื่อของสงครามซอลไอรอน"
)


class ApprovedVoiceReferenceRuntimeTests(unittest.TestCase):
    def test_master_references_are_unchanged_pcm16_48k_mono(self):
        for name, expected_hash in MASTER_SHA256.items():
            path = MASTER_DIR / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 48000)
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getcomptype(), "NONE")

    def test_runtime_references_are_pcm16_24k_mono_and_preserve_duration(self):
        for name, expected_hash in RUNTIME_SHA256.items():
            master = MASTER_DIR / name
            runtime = RUNTIME_DIR / name
            self.assertEqual(hashlib.sha256(runtime.read_bytes()).hexdigest(), expected_hash)
            with wave.open(str(master), "rb") as src, wave.open(str(runtime), "rb") as dst:
                self.assertEqual(dst.getsampwidth(), 2)
                self.assertEqual(dst.getframerate(), 24000)
                self.assertEqual(dst.getnchannels(), 1)
                self.assertEqual(dst.getcomptype(), "NONE")
                self.assertGreater(dst.getnframes(), 0)
                self.assertAlmostEqual(
                    src.getnframes() / src.getframerate(),
                    dst.getnframes() / dst.getframerate(),
                    places=6,
                )

    def test_all_new_targets_resolve_with_runtime_references(self):
        expected = {
            "female_support_A": "female_support_A.wav",
            "heroine_A": "heroine_A.wav",
            "female_alt_A": "female_alt_A.wav",
            "female_alt_B": "female_alt_B.wav",
            "female_alt_C": "female_alt_C.wav",
            "narrator_C": "female_alt_A.wav",
        }
        for target, filename in expected.items():
            row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย", "voice_target": target})
            config = resolve_generation_config(row, "narrator", map_path=MAP_PATH)
            self.assertTrue(config.reference_conditioning)
            self.assertEqual(config.reference_audio, f"assets/triangle-strategy/approved_voice_references/runtime_24k/{filename}")

    def test_serenoa_target_uses_canonical_male14_reference(self):
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย", "voice_target": "serenoa"})
        config = resolve_generation_config(row, "narrator", map_path=MAP_PATH)
        self.assertTrue(config.reference_conditioning)
        self.assertEqual(
            config.reference_audio,
            "assets/triangle-strategy/approved_voice_references/runtime_24k/serenoa_male14.wav",
        )
        self.assertEqual(
            config.reference_sha256,
            "0b54c5e1bd6746e9845080c02c4282664a944683c760285204cbf637e4ccfa6a",
        )
        self.assertEqual(config.generation_mode, "reference_first")
        self.assertIsNone(config.instruction)
        self.assertIsNone(config.instruction_override)
        self.assertEqual(config.language, "Thai")
        self.assertTrue(config.denoise)
        self.assertTrue(config.postprocess_output)
        self.assertEqual(config.reference_text_sha256,
                         hashlib.sha256(config.reference_text.encode("utf-8")).hexdigest())
        self.assertEqual(config.speed, 1.0)
        self.assertEqual(config.steps, 32)
        self.assertEqual(config.seed, 15032)

    def test_narrator_c_matches_narrator_b_generation_config_except_reference(self):
        mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]
        narrator_b = mapping["narrator_B"]
        narrator_c = mapping["narrator_C"]
        for key in ("profile_alias", "instruction_override", "speed", "steps", "seed"):
            self.assertEqual(narrator_c[key], narrator_b[key])
        self.assertEqual(narrator_c["reference_conditioning"]["reference_audio"],
                         "assets/triangle-strategy/approved_voice_references/runtime_24k/female_alt_A.wav")
        self.assertEqual(narrator_c["reference_conditioning"]["reference_text"], NARRATOR_C_TEXT)
        self.assertEqual(
            narrator_c["reference_conditioning"]["reference_text_sha256"],
            hashlib.sha256(NARRATOR_C_TEXT.encode("utf-8")).hexdigest(),
        )

    def test_narrator_b_reference_first_config_preserves_controls(self):
        narrator_b = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]["narrator_B"]
        self.assertEqual(narrator_b["profile_alias"], "bright_female")
        self.assertEqual(narrator_b["instruction_override"], "female, young adult, moderate pitch")
        self.assertEqual(narrator_b["speed"], 1.0)
        self.assertEqual(narrator_b["steps"], 32)
        self.assertEqual(narrator_b["seed"], 15016)
        self.assertEqual(narrator_b["generation_mode"], "reference_first")
        self.assertEqual(narrator_b["reference_conditioning"]["reference_audio"],
                         "assets/triangle-strategy/approved_voice_references/narrator_B.wav")
        self.assertEqual(narrator_b["reference_conditioning"]["reference_sha256"],
                         "902230792ec5b4f0bf64510281f41e0618c3c3fb9b95de98a349d66a11924dd3")

    def test_restored_triangle_strategy_targets_are_reference_first_and_exact(self):
        expected = {
            "roland": {
                "profile": "young_male",
                "instruction": "male, teenager, moderate pitch",
                "speed": 0.94,
                "steps": 32,
                "seed": 26003,
                "audio": "assets/triangle-strategy/approved_voice_references/roland.wav",
                "sha": "ef9db5fcd4d5632e9233e0fc2518b147e0b36a6e5eac982f43b1e6bdafa23b25",
                "text_sha": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            },
            "benedict": {
                "profile": "young_male",
                "instruction": "male, middle-aged, high pitch",
                "speed": 0.9,
                "steps": 32,
                "seed": 26013,
                "audio": "assets/triangle-strategy/approved_voice_references/benedict.wav",
                "sha": "cae049474de5027e77042d1ac76a50d288708197813f8d4b3f95f47bc24d2efe",
                "text_sha": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            },
            "frederica": {
                "profile": "bright_female",
                "instruction": "female, young adult, moderate pitch",
                "speed": 1.06,
                "steps": 32,
                "seed": 15016,
                "audio": "assets/triangle-strategy/approved_voice_references/frederica.wav",
                "sha": "0a042044f296166618e075b6f4e6b7a736c04f1ac6af6d49d695fcb03a34171c",
                "text_sha": "ba6adf9e7b320941d21091e6e66889fa40db978164b88fea1ea82096ae9c6552",
            },
        }
        stale = "work/chapter1_voice_mapping/chapter1_voice_references/candidates/stale.wav"
        for target, values in expected.items():
            row = CsvBatchRow(2, {
                "file_name": "001.wav",
                "thai_text": "text",
                "voice_project": "triangle-strategy",
                "voice_target": target,
                "reference_audio": stale,
            })
            config = resolve_generation_config(row, "narrator")
            self.assertEqual(config.profile_alias, values["profile"])
            self.assertEqual(config.generation_mode, "reference_first")
            self.assertIsNone(config.instruction)
            self.assertIsNone(config.instruction_override)
            self.assertEqual(config.speed, values["speed"])
            self.assertEqual(config.steps, values["steps"])
            self.assertEqual(config.seed, values["seed"])
            self.assertTrue(config.reference_conditioning)
            self.assertEqual(config.reference_audio, values["audio"])
            self.assertEqual(config.reference_sha256, values["sha"])
            self.assertEqual(config.reference_text_sha256, values["text_sha"])
            self.assertNotEqual(config.reference_audio, stale)

    def test_main_triangle_strategy_csv_rows_resolve_from_project_map(self):
        csv_path = ROOT / "imports" / "chapter1_omnivoice_studio.csv"
        counts = {"roland": 0, "benedict": 0, "frederica": 0}
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for values in csv.DictReader(handle):
                target = values.get("voice_target", "")
                if target not in counts:
                    continue
                counts[target] += 1
                row = CsvBatchRow(int(values["line_no"]) + 1, values)
                config = resolve_generation_config(row, "narrator")
                self.assertEqual(config.voice_project, "triangle-strategy")
                self.assertEqual(config.generation_mode, "reference_first")
                self.assertTrue(config.reference_conditioning)
        self.assertEqual(counts, {"roland": 22, "benedict": 40, "frederica": 49})


if __name__ == "__main__":
    unittest.main()

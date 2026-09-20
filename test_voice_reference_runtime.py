import hashlib
import csv
import json
import unittest
import wave
from pathlib import Path

from csv_batch import CsvBatchRow, resolve_generation_config


ROOT = Path(__file__).resolve().parent
MASTER_DIR = ROOT / "assets" / "triangle-strategy" / "approved_voice_references"
MAP_PATH = ROOT / "projects" / "triangle-strategy" / "voice_target_map.json"

EXPECTED = {
    "serenoa": ("narrator", 1.0, 32, 15032, "serenoa.wav", "0b54c5e1bd6746e9845080c02c4282664a944683c760285204cbf637e4ccfa6a", "male_10_young_very_bright.wav"),
    "roland": ("young_male", 0.94, 32, 26003, "roland.wav", "ef9db5fcd4d5632e9233e0fc2518b147e0b36a6e5eac982f43b1e6bdafa23b25", "male_02.wav"),
    "benedict": ("young_male", 0.9, 32, 26013, "benedict.wav", "cae049474de5027e77042d1ac76a50d288708197813f8d4b3f95f47bc24d2efe", "male_13_slow_0.88_wsola.wav"),
    "frederica": ("bright_female", 1.06, 32, 15016, "frederica.wav", "0a042044f296166618e075b6f4e6b7a736c04f1ac6af6d49d695fcb03a34171c", "cute_teen_01_dialogue_02_bright.wav"),
    "hughette": ("warm_female_1", 0.96, 32, 15022, "hughette.wav", "6cbc64d9ec236d93b2c91de4b8adf5b0bff8f5eaa644845326a6aff788af800b", "warm_01_dialogue_01_friendly.wav"),
    "geela": ("bright_female", 1.0, 32, 15016, "geela.wav", "e42d8f756dd48ee6a069823c5f7a41de6ed33fef22c5bb41ea5b140c7f6a738c", "05_NNN_0035.wav"),
    "anna": ("bright_female", 1.0, 32, 15016, "anna.wav", "991729c6ce4bc14bd70ebb06a3710b0ba44df8389aa368d7dc558eba6228b5f0", "09_NNN_0070.wav"),
    "erador": ("young_male", 0.96, 32, 26012, "erador.wav", "1efef52f5445dc7c43dba55fa8ffd5bf20e862bce34f22894c814c3b22a5dab9", "male_12.wav"),
    "travis": ("young_male", 1.0, 32, 26014, "travis.wav", "5f62ec1e78c43cb0e9f43b72ac0dc4b6e436a293607a01efdf1ac1d587dd2450", "male_14.wav"),
    "trish": ("bright_female", 1.0, 32, 15016, "trish.wav", "47a6dc3c618843d6ba48b36d95424bb6a006845f63a72b03601914c27cd30e8f", "03_NNN_0025.wav"),
    "symon": ("young_male", 0.9, 32, 26017, "symon.wav", "92de79801970d269fbd333ddce77af187fad566c06564e28773ff2d5d6f90949", "male_17.wav"),
    "frani": ("young_male", 1.02, 32, 26002, "frani.wav", "0c74decf60098ff40f0c530f496beee4789dca9aa4f9fe2bb6f836b5969bf6a5", "male_02.wav"),
    "narrator": ("bright_female", 1.0, 32, 15016, "narrator.wav", "902230792ec5b4f0bf64510281f41e0618c3c3fb9b95de98a349d66a11924dd3", "stream_013_selected_112kbps.wav"),
}


class ApprovedVoiceReferenceRuntimeTests(unittest.TestCase):
    def test_current_reference_assets_are_pcm16_24k_mono(self):
        for target, (_alias, _speed, _steps, _seed, filename, expected_hash, _original_voice) in EXPECTED.items():
            path = MASTER_DIR / filename
            self.assertTrue(path.is_file(), target)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)
            with wave.open(str(path), "rb") as wav:
                self.assertEqual((wav.getsampwidth(), wav.getframerate(), wav.getnchannels(), wav.getcomptype()), (2, 24000, 1, "NONE"))
                self.assertGreater(wav.getnframes(), 0)

    def test_current_targets_resolve_from_map_with_reference_first(self):
        mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]
        self.assertEqual(set(mapping), set(EXPECTED))
        for target, (alias, speed, steps, seed, filename, expected_hash, original_voice) in EXPECTED.items():
            row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย", "voice_project": "triangle-strategy", "voice_target": target})
            config = resolve_generation_config(row, "narrator", map_path=MAP_PATH)
            self.assertEqual(config.profile_alias, alias)
            self.assertEqual(config.generation_mode, "reference_first")
            self.assertIsNone(config.instruction)
            self.assertIsNone(config.instruction_override)
            self.assertEqual((config.speed, config.steps, config.seed), (speed, steps, seed))
            self.assertTrue(config.reference_conditioning)
            self.assertEqual(config.reference_audio, f"assets/triangle-strategy/approved_voice_references/{filename}")
            self.assertEqual(config.reference_sha256, expected_hash)
            self.assertEqual(mapping[target]["original_voice"], original_voice)

    def test_narrator_target_replaces_legacy_narrator_b(self):
        targets = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]
        self.assertIn("narrator", targets)
        self.assertNotIn("narrator_B", targets)
        self.assertNotIn("narrator_C", targets)

    def test_main_csv_uses_only_current_project_targets_for_available_reference_rows(self):
        csv_path = ROOT / "imports" / "triangle-strategy.csv"
        if not csv_path.exists():
            csv_path = ROOT / "imports" / "chapter1_omnivoice_studio.csv"
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        csv_targets = {row["voice_target"] for row in rows}
        self.assertTrue({"serenoa", "roland", "benedict", "frederica"} <= csv_targets)
        self.assertNotIn("narrator_B", csv_targets)
        self.assertNotIn("narrator_C", csv_targets)


if __name__ == "__main__":
    unittest.main()

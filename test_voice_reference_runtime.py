import hashlib
import csv
import json
import unittest
import wave
from pathlib import Path

import soundfile as sf

from csv_batch import CsvBatchRow, resolve_generation_config


ROOT = Path(__file__).resolve().parent
MASTER_DIR = ROOT / "assets" / "triangle-strategy" / "approved_voice_references"
MAP_PATH = ROOT / "projects" / "triangle-strategy" / "voice_target_map.json"

EXPECTED = {
    "serenoa": ("narrator", 1.0, 32, 15032, "serenoa.wav", "0b54c5e1bd6746e9845080c02c4282664a944683c760285204cbf637e4ccfa6a", "male_10_young_very_bright.wav"),
    "roland": ("young_male", 0.94, 32, 26003, "roland.wav", "ef9db5fcd4d5632e9233e0fc2518b147e0b36a6e5eac982f43b1e6bdafa23b25", "male_03.wav"),
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
    "MALE_CHILD_A": ("young_male", 0.95, 32, 27201, "MALE_CHILD_A.wav", "4d93274d4aef4bd708ef5f9eb47fa9b25c15778ddb13f94ed131bda4a871495a", "MALE_CHILD_C_01.wav"),
    "MALE_CHILD_B": ("young_male", 1.04, 32, 27103, "MALE_CHILD_B.wav", "10739fd65a1b0ec75e1e55954e463d1233a09552522ac574ebcfb244b340cd90", "MALE_CHILD_B_03.wav"),
    "MALE_CHILD_C": ("young_male", 1.05, 32, 27101, "MALE_CHILD_C.wav", "e4c33abbfbc94af561927377383a9c9a494ff2dec389952fad81abd0ec0a35e2", "MALE_CHILD_B_01.wav"),
    "MALE_YOUNG_A": ("young_male", 0.92, 32, 26009, "MALE_YOUNG_A.wav", "029d034eabc2b07715a51f61c01bf3d647be8b0394483a1583527ec04b556c80", "male_09.wav"),
    "MALE_YOUNG_B": ("young_male", 0.92, 32, 26018, "MALE_YOUNG_B.wav", "b6ba9233a4a3a993137cd6dda7a428d9ef38d6a1e1b44bf77830457dcd3412b8", "male_18.wav"),
    "MALE_YOUNG_C": ("young_male", 1.05, 32, 26005, "MALE_YOUNG_C.wav", "667f27eee09089d98df245e35ae2e444775f663cee00daf84bf492d3402bd03c", "male_05.wav"),
    "MALE_ADULT_A": ("narrator", 0.78, 32, 20105, "MALE_ADULT_A.wav", "cae049474de5027e77042d1ac76a50d288708197813f8d4b3f95f47bc24d2efe", "great_deku_tree_polished_raw.wav"),
    "MALE_ADULT_B": ("young_male", 1.08, 32, 26008, "MALE_ADULT_B.wav", "cc8ca63fa98029d8f7a836acb30e0e4da48d8da0d8cdca6079f12aa47628cc3d", "male_08_young_quick.wav"),
    "MALE_ADULT_C": ("young_male", 1.0, 32, 26014, "MALE_ADULT_C.wav", "5f62ec1e78c43cb0e9f43b72ac0dc4b6e436a293607a01efdf1ac1d587dd2450", "male_14.wav"),
    "MALE_OLD_A": ("young_male", 0.97, 32, 26006, "MALE_OLD_A.wav", "60184745003756c59fec46efd9e1c19b0559b155632a9238064be5974a4b23bb", "male_06.wav"),
    "MALE_OLD_B": ("young_male", 1.0, 32, 26007, "MALE_OLD_B.wav", "7487a613cf551235635d4a5a382a438ec1c96b9fa9d0e8a8a1d64a9479786dd7", "male_07.wav"),
    "MALE_OLD_C": ("young_male", 0.9, 32, 26011, "MALE_OLD_C.wav", "44c834c2acd5c8383641815f54fdf7600dab8d68c6105fc261028182ab96f6ab", "male_11.wav"),
    "FEMALE_CHILD_B": ("bright_female", 1.04, 32, 28202, "FEMALE_CHILD_B.wav", "b17331425315bef7a101c9854cd228dab334588ba50910070d32442ad5290553", "FEMALE_CHILD_B.wav"),
    "FEMALE_CHILD_A": ("cute_young_female", 1.0, 32, 19102, "FEMALE_CHILD_A.wav", "514c663a45df1f3982ac39025372014d9bcbf94a1572d13d55fcd094b85b00b0", "mipha_candidate_B.wav"),
    "FEMALE_CHILD_C": ("bright_female", 1.02, 32, 28203, "FEMALE_CHILD_C.wav", "4907112457ddaaa1099150a43c7156b7d23d68f44ded4a0d0283af26a8947e80", "FEMALE_CHILD_C.wav"),
    "FEMALE_YOUNG_A": ("bright_female", 1.0, 32, 15016, "FEMALE_YOUNG_A.wav", "db717dd18264774162dbb2fb1601dc6afd65ba43b96f44d0c5e999130f11c1d5", "bright_02_dialogue_01_friendly.wav"),
    "FEMALE_YOUNG_B": ("bright_female", 1.06, 32, 15016, "FEMALE_YOUNG_B.wav", "0a042044f296166618e075b6f4e6b7a736c04f1ac6af6d49d695fcb03a34171c", "bright_01_dialogue_02_bright.wav"),
    "FEMALE_YOUNG_C": ("cute_teen_bright", 1.0, 32, 15019, "FEMALE_YOUNG_C.wav", "814b5ab3e2010b6281b6f999994ee5a8fa38359aeb694be7110e7cd0ee67ee88", "cute_teen_02_dialogue_02_bright.wav"),
    "FEMALE_ADULT_A": ("bright_female", 1.0, 32, 15016, "FEMALE_ADULT_A.wav", "c9696d5e11dcb60f806c856836d2f5786403c0a561da74c8b4af2f684aa3f308", "04_NNN_0030.wav"),
    "FEMALE_ADULT_B": ("bright_female", 1.0, 32, 15016, "FEMALE_ADULT_B.wav", "d3da6d50e64cd040c807a8306b26bd6e26b0d3da9b2d31dbcc26c372e25a5f9e", "08_NNN_0060.wav"),
    "FEMALE_ADULT_C": ("bright_female", 1.0, 32, 15016, "FEMALE_ADULT_C.wav", "abdf2d8a1b41e8c598b29862e8101fa0a1816f168deae6afe72ef91c03004a55", "line_07_chunk_02.wav"),
    "FEMALE_OLD_A": ("bright_female", 1.0, 32, 15016, "FEMALE_OLD_A.wav", "9ad0829d14fe52e0a2f236fd40705ae1a1524856a1582eaca75995dc4a7575ac", "line_12_chunk_03.wav"),
    "FEMALE_OLD_B": ("warm_female_1", 0.93, 32, 28402, "FEMALE_OLD_B.wav", "550b1667829f3f4da00fe0b593b2fafa281a4ea2601cd1d5a448c89e85a52819", "FEMALE_OLD_B.wav"),
    "FEMALE_OLD_C": ("warm_female_1", 0.9, 32, 28403, "FEMALE_OLD_C.wav", "8bcaa6fbbc7e2ca83a47047bd9844987cc8f6c7653c9b54a256566de946cd902", "FEMALE_OLD_C.wav"),
    "MALE_ANGER_STRONG_01": ("young_male", 1.0, 32, 28501, "MALE_ANGER_STRONG_01.wav", "f39f63c4bf06b5c77aa69fe4c434308f4639d59951f19bf9df54d01810cbefab", "s001_con_actor001_script2_2_2b.flac"),
    "MALE_ANGER_STRONG_02": ("young_male", 1.0, 32, 28502, "MALE_ANGER_STRONG_02.wav", "ec03e32f99d1d113d06f4c5216be30d1541ef5a07c2b32141257ab7b4da1ac9a", "s002_con_actor003_script2_2_2b.flac"),
    "FEMALE_ANGER_STRONG_01": ("bright_female", 1.0, 32, 28601, "FEMALE_ANGER_STRONG_01.wav", "a19d630d46bb35120ee409e98b643f33966f892cd17f3bc056ad1be05d793fa5", "s001_con_actor002_script2_2_2b.flac"),
    "FEMALE_ANGER_STRONG_02": ("bright_female", 1.0, 32, 28602, "FEMALE_ANGER_STRONG_02.wav", "6b30556f0e39dc444a074f787cf24893f3305acb4d7a1f64006f27f8f67fadcb", "s003_con_actor005_script2_2_2b.flac"),
}


class ApprovedVoiceReferenceRuntimeTests(unittest.TestCase):
    def test_current_reference_assets_are_pcm16_24k_mono(self):
        for target, (_alias, _speed, _steps, _seed, filename, expected_hash, _original_voice) in EXPECTED.items():
            path = MASTER_DIR / filename
            self.assertTrue(path.is_file(), target)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)
            if target.startswith(("MALE_ANGER_STRONG_", "FEMALE_ANGER_STRONG_")):
                info = sf.info(path)
                self.assertEqual((info.subtype, info.samplerate, info.channels), ("PCM_16", 24000, 1))
                self.assertGreater(info.frames, 0)
                continue
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

    def test_new_male_targets_reference_text_hashes_and_reference_first(self):
        targets = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]
        expected_hashes = {
            "MALE_CHILD_A": "061a4b7e340136c2fdcf7bb834e98186a606aaa8e3ea3741d86933a8db5ffc04",
            "MALE_CHILD_B": "061a4b7e340136c2fdcf7bb834e98186a606aaa8e3ea3741d86933a8db5ffc04",
            "MALE_CHILD_C": "061a4b7e340136c2fdcf7bb834e98186a606aaa8e3ea3741d86933a8db5ffc04",
            "MALE_YOUNG_A": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "MALE_YOUNG_B": "97f97a09e4f5ba4aa720d55a2c51e04485df0bed9d41a9603c788a41734e7a3a",
            "MALE_YOUNG_C": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "MALE_ADULT_A": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "MALE_ADULT_B": "97f97a09e4f5ba4aa720d55a2c51e04485df0bed9d41a9603c788a41734e7a3a",
            "MALE_ADULT_C": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "MALE_OLD_A": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "MALE_OLD_B": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "MALE_OLD_C": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
        }
        for target, expected_hash in expected_hashes.items():
            data = targets[target]
            self.assertEqual(data["generation_mode"], "reference_first")
            self.assertNotIn("instruction_override", data)
            self.assertEqual(data["reference_conditioning"]["reference_text_sha256"], expected_hash)

    def test_new_female_targets_reference_text_hashes_and_reference_first(self):
        targets = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]
        expected_hashes = {
            "FEMALE_CHILD_A": "c2b4d60f022db29ca6d5c6022ec5f80fcbd4fd565fe2752b7587554c7256d8b2",
            "FEMALE_CHILD_B": "061a4b7e340136c2fdcf7bb834e98186a606aaa8e3ea3741d86933a8db5ffc04",
            "FEMALE_CHILD_C": "061a4b7e340136c2fdcf7bb834e98186a606aaa8e3ea3741d86933a8db5ffc04",
            "FEMALE_YOUNG_A": "9f3f11af59a72fdfd97233b0b534927b0d98d1a56e6b0dc6e68f9cdf7c1b8bb2",
            "FEMALE_YOUNG_B": "7c35bee8f6178d712f24d5d323c58a3a965decc50bb72e486b9a27215191da5c",
            "FEMALE_YOUNG_C": "7c35bee8f6178d712f24d5d323c58a3a965decc50bb72e486b9a27215191da5c",
            "FEMALE_ADULT_A": "e21a6cbe29d2d953ef935f2cdfd7155c8d3b3531fa65922fbd5087ba559645dc",
            "FEMALE_ADULT_B": "ff56f55a5a602c5dd4a54628765d90f356ab3439e8a9f312a58806f18045b175",
            "FEMALE_ADULT_C": "4d799eaea2f2c6ed8a76a57ff5984b2aa542cc214ad8dbe8e3189b708efc2827",
            "FEMALE_OLD_A": "9f3a0828ac99804f17180b18e71c1cce66926629fedb70c0b98fa033a42188f8",
            "FEMALE_OLD_B": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
            "FEMALE_OLD_C": "60b12c6bf47ddd83d3d0633a5000b8ba2cb695c69619a3bdf8170b4e3b0884c1",
        }
        for target, expected_hash in expected_hashes.items():
            data = targets[target]
            self.assertEqual(data["generation_mode"], "reference_first")
            self.assertNotIn("instruction_override", data)
            self.assertEqual(data["reference_conditioning"]["reference_text_sha256"], expected_hash)

    def test_thai_ser_anger_targets_metadata_and_reference_integrity(self):
        targets = json.loads(MAP_PATH.read_text(encoding="utf-8"))["targets"]
        manifest_path = MASTER_DIR / "candidates" / "rough_thai_ser" / "manifest.json"
        manifest = {item["id"]: item for item in json.loads(manifest_path.read_text(encoding="utf-8"))}
        expected_profiles = {
            "MALE_ANGER_STRONG_01": ("young_male", "Male", 30, 28501),
            "MALE_ANGER_STRONG_02": ("young_male", "Male", 28, 28502),
            "FEMALE_ANGER_STRONG_01": ("bright_female", "Female", 22, 28601),
            "FEMALE_ANGER_STRONG_02": ("bright_female", "Female", 30, 28602),
        }
        for target, (alias, gender, age, seed) in expected_profiles.items():
            data = targets[target]
            source = manifest[target]
            ref = data["reference_conditioning"]
            self.assertEqual(data["profile_alias"], alias)
            self.assertEqual(data["original_voice"], source["source_audio_id"])
            self.assertEqual(data["generation_mode"], "reference_first")
            self.assertNotIn("instruction_override", data)
            self.assertEqual((data["speed"], data["steps"], data["seed"]), (1.0, 32, seed))
            self.assertEqual((source["actor_gender"], source["actor_age"]), (gender, age))
            self.assertEqual((source["assigned_emo"], source["script_intensity"]), ("Angry", "High"))
            self.assertEqual(ref["reference_text"], source["reference_text"])
            self.assertEqual(ref["reference_text_sha256"], hashlib.sha256(source["reference_text"].encode("utf-8")).hexdigest())
            path = ROOT / ref["reference_audio"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ref["reference_sha256"])

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

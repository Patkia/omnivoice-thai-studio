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
    "serenoa": ("narrator", 1.26, 32, 15032, "serenoa.wav", "0b54c5e1bd6746e9845080c02c4282664a944683c760285204cbf637e4ccfa6a", "male_10_young_very_bright.wav"),
    "roland": ("young_male", 1.3, 32, 26003, "roland.wav", "ef9db5fcd4d5632e9233e0fc2518b147e0b36a6e5eac982f43b1e6bdafa23b25", "male_03.wav"),
    "benedict": ("young_male", 1.2, 32, 42010, "booker.wav", "cae049474de5027e77042d1ac76a50d288708197813f8d4b3f95f47bc24d2efe", "COR_B.wav"),
    "frederica": ("bright_female", 1.24, 32, 15016, "frederica.wav", "0a042044f296166618e075b6f4e6b7a736c04f1ac6af6d49d695fcb03a34171c", "cute_teen_01_dialogue_02_bright.wav"),
    "hughette": ("warm_female_1", 1.26, 32, 15022, "hughette.wav", "6cbc64d9ec236d93b2c91de4b8adf5b0bff8f5eaa644845326a6aff788af800b", "warm_01_dialogue_01_friendly.wav"),
    "geela": ("bright_female", 1.22, 32, 15016, "geela.wav", "e42d8f756dd48ee6a069823c5f7a41de6ed33fef22c5bb41ea5b140c7f6a738c", "05_NNN_0035.wav"),
    "anna": ("bright_female", 1.26, 32, 15016, "anna.wav", "991729c6ce4bc14bd70ebb06a3710b0ba44df8389aa368d7dc558eba6228b5f0", "09_NNN_0070.wav"),
    "erador": ("young_male", 1.22, 32, 26012, "erador.wav", "1efef52f5445dc7c43dba55fa8ffd5bf20e862bce34f22894c814c3b22a5dab9", "male_12.wav"),
    "travis": ("young_male", 1.24, 32, 26014, "travis.wav", "5f62ec1e78c43cb0e9f43b72ac0dc4b6e436a293607a01efdf1ac1d587dd2450", "male_14.wav"),
    "trish": ("bright_female", 1.3, 32, 15016, "trish.wav", "47a6dc3c618843d6ba48b36d95424bb6a006845f63a72b03601914c27cd30e8f", "03_NNN_0025.wav"),
    "symon": ("young_male", 1.18, 32, 26017, "symon.wav", "92de79801970d269fbd333ddce77af187fad566c06564e28773ff2d5d6f90949", "male_17.wav"),
    "frani": ("young_male", 1.22, 32, 26002, "frani.wav", "0c74decf60098ff40f0c530f496beee4789dca9aa4f9fe2bb6f836b5969bf6a5", "male_02.wav"),
    "dragan": ("narrator", 1.3, 32, 33301, "dragan.wav", "d8e36bd5512dd28c12290eeed1971852f62cddb0a9316233b4dd4794819c13ed", "LGN_A.wav"),
    "regna": ("narrator", 1.18, 32, 33326, "regna.wav", "49770b2c85024c9f5da391c1e2e5ba067512309b1aa7b5a95e827775523afddc", "LGN_THAI_VERY_OLD_FIX2.wav"),
    "lyla": ("bright_female", 1.22, 32, 15016, "lyla.wav", "b67c42983dd236b1a606df192bcb8d6587638516a58bffb332ad807b3944741e", "11_NNN_0090.wav"),
    "maxwell": ("narrator", 1.26, 32, 33303, "maxwell.wav", "829529b6c98aab58627370aa894321b13e278f6ff12b50d97565450837ca259c", "LGN_C.wav"),
    "exharme": ("narrator", 1.3, 32, 33302, "exharme.wav", "c16e6694dc9983e32a44f8646cc0d2b1ded502c335b95ad528e1e525cfcb95be", "LGN_B.wav"),
    "sorsley": ("narrator", 1.22, 32, 33702, "sorsley.wav", "fc4e095f2fd991e6cafef14d197a7ac003d745236e599e2324c449f5bdc134e4", "SLS_B.wav"),
    "thalas": ("narrator", 1.3, 32, 33603, "thalas.wav", "e9d33ababb65225b3d009632ca73382c8f0d0f34df2fb0bc3da3e43ecca6da77", "EGS_C.wav"),
    "avlora": ("narrator", 1.26, 32, 33403, "avlora.wav", "2cd8a411628e5aeb99424b31113bc849093a045fc807ca25bbb55ef10163149e", "LYL_C.wav"),
    "cordelia": ("narrator", 1.22, 32, 34001, "cordelia.wav", "7cae6b54365e1e5d49860316d40a5d5c082911be26a3671254c4d4f67462a95a", "CRD_A.wav"),
    "erika": ("narrator", 1.3, 32, 34002, "erika.wav", "af57149d9cf6a40490b24a8cbc81bc5f2beee62fd07f0d2532a677d388f5eb08", "CRD_B.wav"),
    "narrator": ("bright_female", 1.2, 32, 15016, "narrator.wav", "902230792ec5b4f0bf64510281f41e0618c3c3fb9b95de98a349d66a11924dd3", "stream_013_selected_112kbps.wav"),
    "orlaea": ("bright_female", 1.22, 32, 42032, "orlaea.wav", "ff6bfa666446b646b01e0e81d2e3841bc4a089860c9e71b77b5ff4c978394ff5", "cute_teen_01_dialogue_01_friendly.wav"),
    "MALE_CHILD_A": ("young_male", 1.3, 32, 27201, "MALE_CHILD_A.wav", "4d93274d4aef4bd708ef5f9eb47fa9b25c15778ddb13f94ed131bda4a871495a", "MALE_CHILD_C_01.wav"),
    "MALE_CHILD_B": ("young_male", 1.3, 32, 27103, "MALE_CHILD_B.wav", "10739fd65a1b0ec75e1e55954e463d1233a09552522ac574ebcfb244b340cd90", "MALE_CHILD_B_03.wav"),
    "MALE_CHILD_C": ("young_male", 1.3, 32, 27101, "MALE_CHILD_C.wav", "e4c33abbfbc94af561927377383a9c9a494ff2dec389952fad81abd0ec0a35e2", "MALE_CHILD_B_01.wav"),
    "MALE_YOUNG_A": ("young_male", 1.3, 32, 26009, "MALE_YOUNG_A.wav", "029d034eabc2b07715a51f61c01bf3d647be8b0394483a1583527ec04b556c80", "male_09.wav"),
    "MALE_YOUNG_B": ("young_male", 1.3, 32, 26018, "MALE_YOUNG_B.wav", "b6ba9233a4a3a993137cd6dda7a428d9ef38d6a1e1b44bf77830457dcd3412b8", "male_18.wav"),
    "MALE_YOUNG_C": ("young_male", 1.3, 32, 26005, "MALE_YOUNG_C.wav", "667f27eee09089d98df245e35ae2e444775f663cee00daf84bf492d3402bd03c", "male_05.wav"),
    "MALE_ADULT_A": ("narrator", 1.26, 32, 20105, "MALE_ADULT_A.wav", "cae049474de5027e77042d1ac76a50d288708197813f8d4b3f95f47bc24d2efe", "great_deku_tree_polished_raw.wav"),
    "MALE_ADULT_B": ("young_male", 1.26, 32, 26008, "MALE_ADULT_B.wav", "cc8ca63fa98029d8f7a836acb30e0e4da48d8da0d8cdca6079f12aa47628cc3d", "male_08_young_quick.wav"),
    "MALE_ADULT_C": ("young_male", 1.26, 32, 26014, "MALE_ADULT_C.wav", "5f62ec1e78c43cb0e9f43b72ac0dc4b6e436a293607a01efdf1ac1d587dd2450", "male_14.wav"),
    "MALE_OLD_A": ("young_male", 1.18, 32, 26006, "MALE_OLD_A.wav", "60184745003756c59fec46efd9e1c19b0559b155632a9238064be5974a4b23bb", "male_06.wav"),
    "MALE_OLD_B": ("young_male", 1.18, 32, 26007, "MALE_OLD_B.wav", "7487a613cf551235635d4a5a382a438ec1c96b9fa9d0e8a8a1d64a9479786dd7", "male_07.wav"),
    "MALE_OLD_C": ("young_male", 1.18, 32, 26011, "MALE_OLD_C.wav", "44c834c2acd5c8383641815f54fdf7600dab8d68c6105fc261028182ab96f6ab", "male_11.wav"),
    "FEMALE_CHILD_B": ("bright_female", 1.3, 32, 28202, "FEMALE_CHILD_B.wav", "b17331425315bef7a101c9854cd228dab334588ba50910070d32442ad5290553", "FEMALE_CHILD_B.wav"),
    "FEMALE_CHILD_A": ("cute_young_female", 1.3, 32, 19102, "FEMALE_CHILD_A.wav", "514c663a45df1f3982ac39025372014d9bcbf94a1572d13d55fcd094b85b00b0", "mipha_candidate_B.wav"),
    "FEMALE_CHILD_C": ("bright_female", 1.3, 32, 28203, "FEMALE_CHILD_C.wav", "4907112457ddaaa1099150a43c7156b7d23d68f44ded4a0d0283af26a8947e80", "FEMALE_CHILD_C.wav"),
    "FEMALE_YOUNG_A": ("bright_female", 1.3, 32, 15016, "FEMALE_YOUNG_A.wav", "db717dd18264774162dbb2fb1601dc6afd65ba43b96f44d0c5e999130f11c1d5", "bright_02_dialogue_01_friendly.wav"),
    "FEMALE_YOUNG_B": ("bright_female", 1.3, 32, 15016, "FEMALE_YOUNG_B.wav", "0a042044f296166618e075b6f4e6b7a736c04f1ac6af6d49d695fcb03a34171c", "bright_01_dialogue_02_bright.wav"),
    "FEMALE_YOUNG_C": ("cute_teen_bright", 1.3, 32, 15019, "FEMALE_YOUNG_C.wav", "814b5ab3e2010b6281b6f999994ee5a8fa38359aeb694be7110e7cd0ee67ee88", "cute_teen_02_dialogue_02_bright.wav"),
    "FEMALE_ADULT_A": ("bright_female", 1.26, 32, 15016, "FEMALE_ADULT_A.wav", "c9696d5e11dcb60f806c856836d2f5786403c0a561da74c8b4af2f684aa3f308", "04_NNN_0030.wav"),
    "FEMALE_ADULT_B": ("bright_female", 1.26, 32, 15016, "FEMALE_ADULT_B.wav", "d3da6d50e64cd040c807a8306b26bd6e26b0d3da9b2d31dbcc26c372e25a5f9e", "08_NNN_0060.wav"),
    "FEMALE_ADULT_C": ("bright_female", 1.26, 32, 15016, "FEMALE_ADULT_C.wav", "abdf2d8a1b41e8c598b29862e8101fa0a1816f168deae6afe72ef91c03004a55", "line_07_chunk_02.wav"),
    "FEMALE_OLD_A": ("bright_female", 1.18, 32, 15016, "FEMALE_OLD_A.wav", "9ad0829d14fe52e0a2f236fd40705ae1a1524856a1582eaca75995dc4a7575ac", "line_12_chunk_03.wav"),
    "FEMALE_OLD_B": ("warm_female_1", 1.18, 32, 28402, "FEMALE_OLD_B.wav", "550b1667829f3f4da00fe0b593b2fafa281a4ea2601cd1d5a448c89e85a52819", "FEMALE_OLD_B.wav"),
    "FEMALE_OLD_C": ("warm_female_1", 1.18, 32, 28403, "FEMALE_OLD_C.wav", "8bcaa6fbbc7e2ca83a47047bd9844987cc8f6c7653c9b54a256566de946cd902", "FEMALE_OLD_C.wav"),
    "MALE_ANGER_STRONG_01": ("young_male", 1.3, 32, 28501, "MALE_ANGER_STRONG_01.wav", "f39f63c4bf06b5c77aa69fe4c434308f4639d59951f19bf9df54d01810cbefab", "s001_con_actor001_script2_2_2b.flac"),
    "MALE_ANGER_STRONG_02": ("young_male", 1.3, 32, 28502, "MALE_ANGER_STRONG_02.wav", "ec03e32f99d1d113d06f4c5216be30d1541ef5a07c2b32141257ab7b4da1ac9a", "s002_con_actor003_script2_2_2b.flac"),
    "FEMALE_ANGER_STRONG_01": ("bright_female", 1.3, 32, 28601, "FEMALE_ANGER_STRONG_01.wav", "a19d630d46bb35120ee409e98b643f33966f892cd17f3bc056ad1be05d793fa5", "s001_con_actor002_script2_2_2b.flac"),
    "FEMALE_ANGER_STRONG_02": ("bright_female", 1.3, 32, 28602, "FEMALE_ANGER_STRONG_02.wav", "6b30556f0e39dc444a074f787cf24893f3305acb4d7a1f64006f27f8f67fadcb", "s003_con_actor005_script2_2_2b.flac"),
    "patriatte": ("young_male", 1.2, 32, 42001, "patriatte.wav", "5af60b363815562f71868af755ba6f42498a75261d406f4245d412e5acdc54c8", "PTR_A.wav"),
    "silvio": ("young_male", 1.26, 32, 42002, "silvio.wav", "64372a4eedaf7957c5441f8d68255e43a1eb0cca508e4e2148440943e2083456", "JUL_A.wav"),
    "rufus": ("young_male", 1.26, 32, 42003, "rufus.wav", "6d77d0d345a0478af5b49adcad48968abc3a96cda7cd63a1f4cc42f3c6b947f9", "ROF_B.wav"),
    "landroi": ("young_male", 1.2, 32, 42004, "landroi.wav", "a1e52f5d7f326e3cadafa3038afb5e85da3124b2a6638b853d92e184fc53e065", "LND_A.wav"),
    "jerrom": ("young_male", 1.3, 32, 42005, "jerrom.wav", "c35c40765e120bf04e183dcf70438d26672bcebb7e36bf40c92d12775051ce0a", "JRM_A.wav"),
    "gustadolph": ("young_male", 1.22, 32, 42006, "gustadolph.wav", "97bc3d6f431c5d411451be617cf0413f17da5a85d1bbc5678e4d085ca27c1280", "JRM_B.wav"),
    "svarog": ("young_male", 1.2, 32, 42007, "svarog.wav", "d09b142fbe034e7e9708bc3f5dbc487aa0e9b9a499a0ad21159ca9aa39aea9eb", "BKR_B.wav"),
    "sycras": ("young_male", 1.22, 32, 42008, "sycras.wav", "fd14b6dd4c1a21e38faec7b62a6c6c9101f3e77e658467e56348aaccc1bfde5f", "SEC_C.wav"),
    "booker": ("young_male", 1.22, 32, 26013, "benedict.wav", "2623326eec5a904b6a303b1523c8f62cbef85473d76b726b701c44e8e4ca3d3d", "male_13_slow_0.88_wsola.wav"),
    "kamsell": ("young_male", 1.26, 32, 42011, "kamsell.wav", "e3058261c3480a27dccabb865fa1bdfaf1bca49ed523adc27b91c81ae20f7b1d", "KNS_C.wav"),
    "idore": ("young_male", 1.18, 32, 42012, "idore.wav", "21bb6e689cc87e41ca78500d1fc54573f253a8b7b7938117d9c5c8500cb739fd", "SVR_B_VERY_OLD.wav"),
    "tenebris": ("young_male", 1.2, 32, 42013, "tenebris.wav", "86a4e4c0ccef234c0fec3d558bb313608c14ebac5f15547da2a2f10627db239f", "N208_C.wav"),
    "clarus": ("young_male", 1.26, 32, 42014, "clarus.wav", "87364a93564edaefdd326c0ffbad20b0ba251fd05154fe9cf5b680bb4cd86e7b", "IDO_B.wav"),
    "rudolph": ("young_male", 1.3, 32, 42015, "rudolph.wav", "12a0793a3978ee8ec4d2397adb57cb209964507a7edf1d25b60b864572da998d", "RDL_B.wav"),
    "corentin": ("young_male", 1.26, 32, 42016, "corentin.wav", "71ec133f7dfabb6cf550fb0f8789e77b2f0456cc1f2ccc1132f6a4a4238095a7", "COR_A.wav"),
    "julio": ("young_male", 1.26, 32, 42017, "julio.wav", "4b8ea01e25318b7b3d13b2de0ddf5bda6d0d2e33c915406f58d47150956423c8", "SLV_A.wav"),
    "milo": ("bright_female", 1.3, 32, 42018, "milo.wav", "612ef5bbac66750bc2fbd3066ffc2d06149431268d90d08aea18bbcf318877a9", "ABR_C.wav"),
    "hossabara": ("bright_female", 1.2, 32, 42019, "hossabara.wav", "a246e1299696815743396d504379d08d08c64c4c60653c2f3774557b998abadc", "EZA_B.wav"),
    "narve": ("young_male", 1.3, 32, 42020, "narve.wav", "360e0cf08b7ba0a9b6240f98f88074c84fcf0d67f6f36b7968b92b745ded0640", "male_04_young_bright.wav"),
    "medina": ("bright_female", 1.3, 32, 42021, "medina.wav", "1a8360f9ec82844778f3f98c929dfa594801bfdfb241c889d922f6996e376962", "EZA_A.wav"),
    "jens": ("young_male", 1.26, 32, 42022, "jens.wav", "2b4a1be0a7e21b9fa44870146c83452f0a343dc6498efe8349d8c5117e715387", "YEN_A.wav"),
    "archibald": ("young_male", 1.18, 32, 42023, "archibald.wav", "3a125f6860299263393bb4a77a358855b6fb7e26269b8b631f5c0d39d7228d33", "FLA_A.wav"),
    "flanagan": ("young_male", 1.26, 32, 42024, "flanagan.wav", "7356d6f2f053f84207e757db34fc470346467dc0d8bf666b296acc045b2d8db4", "IDO_C.wav"),
    "ezana": ("bright_female", 1.26, 32, 42025, "ezana.wav", "249e3e42832a4998219c9c43a1e4a282a5e6044b872f4b04c9d0fe45e46b1baf", "GUR_A.wav"),
    "lionel": ("young_male", 1.3, 32, 42026, "lionel.wav", "67dc53f8584412eaea8cbd187337fdc2f389b75c64f2f59e8820be475c67d126", "JUL_C.wav"),
    "groma": ("bright_female", 1.18, 32, 42027, "groma.wav", "d7ac9a400350fc0b912dba3ac7ed64d785b6faf00d76fb67a89b00b11c46020d", "MIR_C.wav"),
    "piccoletta": ("bright_female", 1.3, 32, 42028, "piccoletta.wav", "ed36416e7344e01534422b79f9e1a3736a11ac3b7f3343fb1b5282701824814d", "GIB_C.wav"),
    "decimal": ("narrator", 1.2, 32, 42029, "decimal.wav", "c1528a79e871c83d9533e034eff5f6a316927ccf6d6c1564c739e24223678a2c", "KOH_B.wav"),
    "quahaug": ("young_male", 1.3, 32, 42030, "quahaug.wav", "f93e8904a2b8b999df2e310130e18e1807757aa24b60340796db5f15403c2e79", "MALE_CHILD_C_03.wav"),
    "giovanna": ("bright_female", 1.26, 32, 42031, "giovanna.wav", "7cd81e76bda753ad512ee6d2fe5c004e64530342e9704a5d5d77f8db4db9f8c6", "GIB_A.wav"),
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
            self.assertEqual((data["speed"], data["steps"], data["seed"]), (1.3, 32, seed))
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

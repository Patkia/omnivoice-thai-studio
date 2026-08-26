import unittest

from thai_speech_normalizer import normalize_text
from thai_text_preprocessor import preprocess_text


class ThaiSpeechNormalizerTests(unittest.TestCase):
    def test_integer_seventeen(self):
        self.assertEqual(normalize_text("17").text, "สิบเจ็ด")

    def test_grouped_integer(self):
        self.assertEqual(normalize_text("2,500").text, "สองพันห้าร้อย")

    def test_name_has_no_latin(self):
        result = normalize_text("Roland ยืนรอ")
        self.assertFalse(result.latin_remaining)
        self.assertTrue(result.thai_only_gate_passed)

    def test_mixed_term_has_no_latin_or_digits(self):
        result = normalize_text("Level 10 เริ่มต้น")
        self.assertEqual(result.text, "เลเวล สิบ เริ่มต้น")
        self.assertTrue(result.thai_only_gate_passed)

    def test_disabled_is_verbatim(self):
        source = "HP เหลือ 20 เปอร์เซ็นต์"
        self.assertEqual(normalize_text(source, enabled=False).text, source)

    def test_approved_dictionary_mapping_still_applies_after_normalization(self):
        normalized = normalize_text("ผมหั่นแอปเปิล", enabled=True).text
        self.assertEqual(preprocess_text(normalized, "pronunciation_dictionary.json", enabled=True), "ผมหั่นแอ๊ปเปิ้ล")


if __name__ == "__main__":
    unittest.main()

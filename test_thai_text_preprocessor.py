import unittest

from thai_text_preprocessor import preprocess_text


class ThaiTextPreprocessorTests(unittest.TestCase):
    def test_approved_apple_mapping_when_enabled(self):
        source = "ผมกำลังหั่นแอปเปิลอยู่ในครัว"
        self.assertEqual(
            preprocess_text(source, "pronunciation_dictionary.json", enabled=True),
            "ผมกำลังหั่นแอ๊ปเปิ้ลอยู่ในครัว",
        )

    def test_disabled_returns_input_verbatim(self):
        source = "ผมกำลังหั่นแอปเปิลอยู่ในครัว"
        self.assertEqual(preprocess_text(source, "pronunciation_dictionary.json", enabled=False), source)


if __name__ == "__main__":
    unittest.main()

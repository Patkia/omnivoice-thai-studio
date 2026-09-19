import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from quick_voice_preview import PREVIEW_HARD_MAX, PreviewTextError, preview_output_path, select_preview_text
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from studio import QuickPreviewWorker, StudioWindow


class QuickVoicePreviewTests(unittest.TestCase):
    def test_empty_text_is_rejected(self):
        with self.assertRaises(PreviewTextError):
            select_preview_text("   \n")

    def test_first_complete_sentence_is_selected(self):
        text = "ประโยคแรกจบแล้ว. ประโยคที่สองต้องไม่ถูกเลือก"
        self.assertEqual(select_preview_text(text), "ประโยคแรกจบแล้ว. ")

    def test_overlong_first_sentence_uses_safe_semantic_first_chunk(self):
        text = "คำบรรยายยาว " * 20 + "โดยยังไม่มีจุดจบ"
        selected = select_preview_text(text)
        self.assertLessEqual(len(selected), PREVIEW_HARD_MAX)
        self.assertEqual(text[:len(selected)], selected)

    def test_deterministic_preview_path_is_separate_from_final_output(self):
        one = preview_output_path("ข้อความ", "cute_teen_bright", 1.0, 32, Path("project"))
        two = preview_output_path("ข้อความ", "cute_teen_bright", 1.0, 32, Path("project"))
        changed = preview_output_path("ข้อความ", "cute_teen_bright", 1.01, 32, Path("project"))
        self.assertEqual(one, two)
        self.assertNotEqual(one, changed)
        self.assertEqual(one.parent, Path("project") / "output" / "studio" / "preview")
        self.assertNotEqual(one, Path("project") / "final.wav")

    def test_preview_worker_sends_current_voice_speed_without_long_text_path(self):
        adapter = MagicMock()
        adapter.generate.return_value = {"cache_hit": True, "output": Path("output/studio/preview/test.wav")}
        worker = QuickPreviewWorker(adapter, "ข้อความสั้น", "cute_teen_bright", 1.0, 32, Path("preview.wav"))
        with patch("studio_generation.generate_long") as long_generate:
            worker.run()
        long_generate.assert_not_called()
        adapter.generate.assert_called_once_with("ข้อความสั้น", "cute_teen_bright", 1.0, 32, Path("preview.wav"), force=False)

    def test_preview_completion_does_not_change_final_output_path(self):
        app = QApplication.instance() or QApplication([])
        window = StudioWindow()
        final_output = window.output.text()
        with patch.object(window.player, "play"):
            window.preview_generated({"cache_hit": True, "output": Path("output/studio/preview/test.wav")})
        self.assertEqual(window.output.text(), final_output)
        window.close()

    def test_studio_selector_shows_promoted_profiles_and_uses_distinct_defaults(self):
        app = QApplication.instance() or QApplication([])
        window = StudioWindow()
        for alias in ("mipha_style", "cute_young_female", "ancient_deep_male"):
            self.assertIn(alias, window.aliases)
        window._voice_changed("mipha_style")
        self.assertEqual(window.speed.value(), 0.92)
        window._voice_changed("cute_young_female")
        self.assertEqual(window.speed.value(), 1.00)
        window._voice_changed("ancient_deep_male")
        self.assertEqual(window.speed.value(), 0.68)
        self.assertLessEqual(window.speed.minimum(), 0.68)
        window.close()


if __name__ == "__main__":
    unittest.main()

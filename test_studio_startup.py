from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from studio import ENGINE_LOADING, ENGINE_NOT_LOADED, ENGINE_READY, StudioWindow


class StudioStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_starts_without_runtime_import_or_model(self):
        window = StudioWindow()
        self.assertEqual(window.engine_state, ENGINE_NOT_LOADED)
        self.assertIsNone(window.adapter)
        self.assertIsNone(window.engine_worker)
        self.assertEqual(window.model_label.text(), "Engine: Not loaded")
        window.close()

    def test_import_studio_does_not_import_heavy_runtime(self):
        code = "import sys, studio; print('torch' in sys.modules, 'omnivoice' in sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "False False")

    def test_first_engine_request_is_background_and_pending_action_runs_once(self):
        window = StudioWindow()
        fake_worker = MagicMock()
        fake_worker.progress = MagicMock()
        fake_worker.ready = MagicMock()
        fake_worker.failed = MagicMock()
        with patch("studio.EngineInitWorker", return_value=fake_worker) as worker_type:
            action = MagicMock()
            window._request_engine(action)
            self.assertEqual(window.engine_state, ENGINE_LOADING)
            worker_type.assert_called_once_with(window)
            fake_worker.start.assert_called_once_with()
            adapter = MagicMock()
            window._engine_ready(adapter)
            action.assert_called_once_with(adapter)
            self.assertEqual(window.engine_state, ENGINE_READY)
        window.close()

    def test_ready_engine_is_reused_without_new_worker(self):
        window = StudioWindow()
        adapter = MagicMock()
        window._engine_ready(adapter)
        action = MagicMock()
        with patch("studio.EngineInitWorker") as worker_type:
            window._request_engine(action)
        action.assert_called_once_with(adapter)
        worker_type.assert_not_called()
        window.close()


if __name__ == "__main__":
    unittest.main()

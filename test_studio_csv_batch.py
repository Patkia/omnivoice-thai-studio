from __future__ import annotations

import tempfile
import unittest
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QScrollArea

from csv_batch import CsvBatchRow
from studio import StudioWindow


class StudioCsvBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self) -> StudioWindow:
        window = StudioWindow()
        window.batch_rows = [
            CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความทดสอบ", "character_name": "ผู้บรรยาย"}),
            CsvBatchRow(3, {"file_name": "002.wav", "thai_text": "ข้อความถัดไป", "prosody_note": "เว้นจังหวะ"}),
        ]
        return window

    def test_csv_batch_controls_and_preview_table_exist(self):
        window = self.make_window()
        window.validate_batch_rows()
        self.assertEqual(window.batch_table.rowCount(), 2)
        self.assertTrue(window.import_csv_button.isEnabled())
        self.assertTrue(window.generate_batch_button.isEnabled())
        window.close()

    def test_serenoa_resolution_summary_shows_reference_first_mode(self):
        window = StudioWindow()
        window.batch_rows = [CsvBatchRow(2, {
            "file_name": "001.wav", "thai_text": "ข้อความทดสอบ",
            "voice_project": "triangle-strategy", "voice_target": "serenoa",
        })]
        window.validate_batch_rows()
        summary = window.batch_resolution_summary.text()
        self.assertIn("Generation Mode: reference_first", summary)
        self.assertIn("Voice Project: triangle-strategy", summary)
        self.assertIn("Voice Target: serenoa", summary)
        self.assertIn("Profile Alias: narrator", summary)
        self.assertIn("Instruction: NONE (reference identity only)", summary)
        self.assertEqual(window.batch_table.item(0, 5).text(), "serenoa")
        self.assertEqual(window.batch_table.item(0, 6).text(), "narrator")
        window.close()

    def test_import_uses_csv_sibling_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path = Path(temp) / "rows.csv"
            csv_path.write_text(
                "file_name,thai_text,voice_project,voice_target\n"
                "001.wav,ข้อความไทย,triangle-strategy,serenoa\n",
                encoding="utf-8-sig",
            )
            window = StudioWindow()
            with patch("studio.QFileDialog.getOpenFileName", return_value=(str(csv_path), "CSV (*.csv)")):
                window.import_csv()
            self.assertEqual(
                Path(window.batch_output_label.text()),
                csv_path.parent / "output",
            )
            self.assertIn("Voice Project: triangle-strategy", window.batch_resolution_summary.text())
            window.close()

    def test_display_row_number_is_one_based_data_index_not_csv_physical_row(self):
        window = self.make_window()
        window.validate_batch_rows()
        self.assertEqual([window.batch_table.item(i, 1).text() for i in range(2)], ["1", "2"])
        self.assertEqual([row.csv_row_number for row in window.batch_rows], [2, 3])
        self.assertEqual(window.batch_table.item(0, 5).text(), "")
        self.assertEqual(window.batch_table.item(0, 6).text(), window.voice.currentText())
        window.close()

    def test_thirteen_data_rows_display_one_through_thirteen(self):
        window = StudioWindow()
        window.batch_rows = [
            CsvBatchRow(index + 2, {"file_name": f"{index + 1:02d}.wav", "thai_text": "ข้อความไทย"})
            for index in range(13)
        ]
        window.validate_batch_rows()
        self.assertEqual(
            [window.batch_table.item(index, 1).text() for index in range(13)],
            [str(index + 1) for index in range(13)],
        )
        self.assertEqual([row.csv_row_number for row in window.batch_rows], list(range(2, 15)))
        window.close()

    def test_fresh_import_does_not_inherit_prior_selection_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path = root / "fresh.csv"
            csv_path.write_text("placeholder", encoding="utf-8-sig")
            output = root / "output"
            output.mkdir()
            target = CsvBatchRow(2, {
                "file_name": "MS01_X01_A1_1005_M_SEL_0030.wav",
                "self_id": "MS01_X01_A1_1005_M_SEL_0030",
                "thai_text": "\u0e02\u0e49\u0e2d\u0e04\u0e27\u0e32\u0e21\u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22",
                "voice_project": "triangle-strategy",
                "voice_target": "serenoa",
            })
            (output / target.file_name).write_bytes(b"existing")
            window = StudioWindow()
            window.batch_rows = [CsvBatchRow(2, {"file_name": "old.wav", "thai_text": "\u0e02\u0e49\u0e2d\u0e04\u0e27\u0e32\u0e21"})]
            window.batch_rows[0].selected = True
            window.batch_mission_id = "unrelated-prior-batch"
            window.batch_job_path = root / "old-job.json"
            window.batch_output_label.setText(str(output))
            window._batch_output_user_selected = True
            with patch("studio.QFileDialog.getOpenFileName", return_value=(str(csv_path), "CSV (*.csv)")), \
                 patch("studio.read_csv", return_value=[target]):
                window.import_csv()
            self.assertIsNone(window.batch_mission_id)
            self.assertIsNone(window.batch_job_path)
            self.assertEqual(Path(window.batch_output_label.text()), output)
            self.assertFalse(window._batch_output_user_selected)
            self.assertEqual(len(window.batch_rows), 1)
            self.assertFalse(window.batch_rows[0].selected)
            self.assertEqual(window.batch_table.item(0, 0).checkState().name, "Unchecked")
            window.close()

    def test_csv_layout_uses_scroll_and_keeps_readable_table_geometry(self):
        window = self.make_window()
        window.batch_rows[0].values["thai_text"] = "ข้อความภาษาไทยสำหรับตรวจการตัดบรรทัด " * 8
        window.batch_rows[1].values["prosody_note"] = "หมายเหตุการเว้นจังหวะสำหรับ Human review " * 5
        window.validate_batch_rows()
        self.assertIsInstance(window.centralWidget(), QScrollArea)
        self.assertGreaterEqual(window.batch_table.minimumHeight(), 350)
        self.assertTrue(window.batch_table.wordWrap())
        for width, height in ((1920, 1080), (1600, 900), (1366, 768)):
            with self.subTest(size=(width, height)):
                window.resize(width, height)
                window.show()
                self.app.processEvents()
                window._adjust_csv_table_layout()
                self.assertGreater(window.batch_table.columnWidth(7), window.batch_table.columnWidth(4))
                self.assertGreaterEqual(window.batch_table.rowHeight(0), 56)
                self.assertGreaterEqual(window.batch_table.columnWidth(8), 300)
        window.close()

    def test_selected_rows_launch_external_runner_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            window.batch_rows[1].selected = False
            window.batch_output_label.setText(str(root / "wav"))
            paths = {"base": root / "state"}
            process = MagicMock(); process.poll.return_value = None; process.pid = 4242
            with patch("studio.batch_runner._mission_paths", return_value=paths), \
                 patch("studio.subprocess.Popen", return_value=process) as popen:
                window.generate_csv_batch()
            command = popen.call_args.args[0]
            self.assertIn("tts_batch_runner.py", command[1])
            self.assertIn("run", command)
            self.assertTrue(window.batch_job_path.is_file())
            diagnostic = json.loads((root / "state" / "launch_diagnostic.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["launcher"]["pid"], 4242)
            self.assertEqual(diagnostic["job_build"]["result"], "completed")
            window.close()

    def test_narrator_config_is_visible_before_launch(self):
        window = self.make_window()
        window.batch_rows[0].values["voice_project"] = "triangle-strategy"
        window.batch_rows[0].values["voice_target"] = "narrator"
        window.validate_batch_rows()
        summary = window.batch_resolution_summary.text()
        self.assertIn("Voice Project: triangle-strategy", summary)
        self.assertIn("Voice Target: narrator", summary)
        self.assertIn("Profile Alias: bright_female", summary)
        self.assertIn("Instruction: NONE (reference identity only)", summary)
        self.assertIn("Speed: 1.20", summary)
        self.assertIn("Seed: 15016", summary)
        self.assertIn("Reference Conditioning: ON", summary)
        self.assertIn("assets/triangle-strategy/approved_voice_references/narrator.wav", summary)
        window.close()

    def test_voice_target_and_resolved_profile_are_visible_per_row(self):
        window = self.make_window()
        window.batch_rows[0].values["voice_project"] = "triangle-strategy"
        window.batch_rows[0].values["voice_target"] = "narrator"
        window.validate_batch_rows()
        self.assertEqual(window.batch_table.item(0, 5).text(), "narrator")
        self.assertEqual(window.batch_table.item(0, 6).text(), "bright_female")
        window.close()

    def test_tts_override_is_visible_with_canonical_and_tts_input(self):
        window = self.make_window()
        window.batch_rows[0].values["thai_text"] = "นอร์เซเลีย"
        window.batch_rows[0].values["tts_text"] = "นอร์ เซ เลีย"
        window.validate_batch_rows()
        item = window.batch_table.item(0, 8)
        self.assertEqual(item.text(), "นอร์ เซ เลีย")
        self.assertIn("Canonical:\nนอร์เซเลีย", item.toolTip())
        self.assertIn("TTS input:\nนอร์ เซ เลีย", item.toolTip())
        window.close()

    def test_unknown_target_is_persisted_and_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            for row in window.batch_rows:
                row.values["voice_project"] = "triangle-strategy"
            window.batch_rows[0].values["voice_target"] = "not_in_map"
            window.batch_rows[1].values["voice_target"] = "not_in_map"
            window.batch_output_label.setText(str(root / "wav"))
            with patch("studio.batch_runner._mission_paths", return_value={"base": root / "state"}), \
                 patch("studio.subprocess.Popen") as popen, \
                 patch("studio.QMessageBox.warning"):
                window.generate_csv_batch()
            popen.assert_not_called()
            diagnostic = json.loads((root / "state" / "launch_diagnostic.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["error_stage"], "VOICE_TARGET_RESOLUTION")
            self.assertEqual(diagnostic["error_type"], "CsvBatchError")
            self.assertEqual(diagnostic["validation"]["result"], "completed")
            window.close()

    def test_validation_failure_is_persisted_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            window.batch_rows[0].values["file_name"] = "../unsafe.wav"
            window.batch_rows[1].values["file_name"] = "../unsafe2.wav"
            window.batch_output_label.setText(str(root / "wav"))
            with patch("studio.batch_runner._mission_paths", return_value={"base": root / "state"}), \
                 patch("studio.subprocess.Popen") as popen, \
                 patch("studio.QMessageBox.warning"):
                window.generate_csv_batch()
            popen.assert_not_called()
            diagnostic = json.loads((root / "state" / "launch_diagnostic.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["error_stage"], "VALIDATION")
            self.assertEqual(diagnostic["error_type"], "CsvBatchError")
            self.assertEqual(diagnostic["validation"]["result"], "completed")
            window.close()

    def test_job_write_failure_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            window.batch_output_label.setText(str(root / "wav"))
            with patch("studio.batch_runner._mission_paths", return_value={"base": root / "state"}), \
                 patch("studio.write_job", side_effect=OSError("write denied")), \
                 patch("studio.QMessageBox.warning"):
                window.generate_csv_batch()
            diagnostic = json.loads((root / "state" / "launch_diagnostic.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["error_stage"], "JOB_WRITE")
            self.assertEqual(diagnostic["error_type"], "OSError")
            self.assertIn("write denied", diagnostic["error_message"])
            window.close()

    def test_launcher_failure_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            window.batch_output_label.setText(str(root / "wav"))
            with patch("studio.batch_runner._mission_paths", return_value={"base": root / "state"}), \
                 patch("studio.subprocess.Popen", side_effect=OSError("runner denied")), \
                 patch("studio.QMessageBox.warning"):
                window.generate_csv_batch()
            diagnostic = json.loads((root / "state" / "launch_diagnostic.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["error_stage"], "LAUNCH")
            self.assertEqual(diagnostic["error_type"], "OSError")
            self.assertIn("runner denied", diagnostic["error_message"])
            window.close()

    def test_external_launcher_uses_shared_no_console_options(self):
        window = self.make_window()
        process = MagicMock(); process.pid = 4242
        options = {"creationflags": 123}
        with patch("studio.batch_runner.background_process_kwargs", return_value=options), \
             patch("studio.subprocess.Popen", return_value=process) as popen:
            window._launch_batch_runner(Path("job.json"))
        self.assertEqual(popen.call_args.kwargs["creationflags"], 123)
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.PIPE)
        window.close()

    def test_runner_stdout_stderr_are_persisted_when_external_runner_exits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            window.batch_mission_id = "csv-test"
            window.batch_diagnostic_path = root / "launch_diagnostic.json"
            window.batch_diagnostic = {"launcher": {"result": "launched"}}
            process = MagicMock(); process.poll.return_value = 2; process.communicate.return_value = ("runner stdout", "runner stderr")
            window.batch_launcher = process
            with patch("studio.batch_runner.mission_status", return_value={"running": False, "checkpoint": None}):
                window.poll_batch_status()
            diagnostic = json.loads(window.batch_diagnostic_path.read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["error_stage"], "RUNNER")
            self.assertEqual(diagnostic["launcher"]["stdout"], "runner stdout")
            self.assertEqual(diagnostic["launcher"]["stderr"], "runner stderr")
            window.close()

    def test_checkpoint_polling_maps_row_statuses(self):
        window = self.make_window()
        window.batch_mission_id = "csv-test"
        window.batch_progress.setRange(0, 2)
        launcher = MagicMock(); launcher.poll.return_value = None
        window.batch_launcher = launcher
        state = {"running": True, "checkpoint": {"status": "running", "lines": {
            "csv-00002": {"status": "completed"},
            "csv-00003": {"status": "running"},
        }}}
        with patch("studio.batch_runner.mission_status", return_value=state):
            window.poll_batch_status()
        self.assertEqual(window.batch_rows[0].status, "DONE")
        self.assertEqual(window.batch_rows[1].status, "GENERATING")
        self.assertEqual(window.batch_progress.value(), 1)
        window.close()

    def test_checkpoint_polling_persists_reference_prompt_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            window = self.make_window()
            window.batch_mission_id = "csv-reference-test"
            window.batch_diagnostic_path = root / "launch_diagnostic.json"
            window.batch_diagnostic = {"launcher": {"result": "launched"}}
            window.batch_progress.setRange(0, 2)
            launcher = MagicMock(); launcher.poll.return_value = None
            window.batch_launcher = launcher
            checkpoint = {
                "status": "running",
                "reference_prompts": {"reference-key": {
                    "status": "prepared", "reference_sha256": "9" * 64,
                }},
                "runtime": {"model_load_count": 1, "reference_prompt_prep_count": 1},
                "lines": {
                    "csv-00002": {"status": "running", "resolved_spoken_text": "ข้อความทดสอบ"},
                    "csv-00003": {"status": "pending", "resolved_spoken_text": "ข้อความถัดไป"},
                },
            }
            with patch("studio.batch_runner.mission_status", return_value={"running": True, "checkpoint": checkpoint}):
                window.poll_batch_status()
            diagnostic = json.loads(window.batch_diagnostic_path.read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["reference_prompts"]["reference-key"]["status"], "prepared")
            self.assertEqual(diagnostic["runner_runtime"]["model_load_count"], 1)
            self.assertEqual(diagnostic["runner_runtime"]["reference_prompt_prep_count"], 1)
            window.close()

    def test_stop_uses_external_mission_not_studio_process(self):
        window = self.make_window()
        window.batch_mission_id = "csv-test"
        with patch("studio.batch_runner.mission_status", return_value={"lock": {"parent_pid": 987654}}), \
             patch("studio.batch_runner.cancel_mission") as cancel:
            window.stop_csv_batch()
        cancel.assert_called_once_with("csv-test")
        window.close()


if __name__ == "__main__":
    unittest.main()

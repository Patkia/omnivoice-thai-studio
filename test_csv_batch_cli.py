import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import csv_batch_cli
from csv_batch_cli import default_csv_output_dir, prepare_job


class CsvBatchCliTests(unittest.TestCase):
    def _write_csv(self, root: Path) -> Path:
        path = root / "chapter0_omnivoice_studio.csv"
        path.write_text(
            "file_name,thai_text,voice_project,voice_target\n"
            "001.wav,ข้อความภาษาไทย,triangle-strategy,narrator\n",
            encoding="utf-8-sig",
        )
        return path

    def test_default_output_is_sibling_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path = Path(temp) / "mapping" / "rows.csv"
            csv_path.parent.mkdir()
            self.assertEqual(default_csv_output_dir(csv_path), csv_path.parent.resolve() / "input_wav")

    def test_prepare_job_uses_sibling_output_and_skips_existing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path = self._write_csv(root)
            output = root / "input_wav"
            output.mkdir()
            (output / "001.wav").write_bytes(b"existing")

            job, summary = prepare_job(csv_path)

            self.assertIsNone(job)
            self.assertEqual(Path(summary["output_dir"]), output.resolve())
            self.assertEqual(summary["existing"], 1)
            self.assertEqual(summary["selected"], 0)

    def test_overwrite_selects_existing_row_and_builds_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path = self._write_csv(root)
            output = root / "input_wav"
            output.mkdir()
            (output / "001.wav").write_bytes(b"existing")

            job, summary = prepare_job(csv_path, overwrite=True, mission_id="cli-test")

            self.assertIsNotNone(job)
            self.assertEqual(job["mission_id"], "cli-test")
            self.assertEqual(Path(job["output_dir"]), output.resolve())
            self.assertEqual(len(job["lines"]), 1)
            self.assertTrue(job["lines"][0]["force"])
            self.assertEqual(summary["selected"], 1)


    def test_ctrl_c_cancels_active_mission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path = self._write_csv(root)
            with patch.object(csv_batch_cli, "JOB_ROOT", root / "jobs"), \
                 patch.object(csv_batch_cli, "run_job", side_effect=KeyboardInterrupt), \
                 patch.object(csv_batch_cli, "cancel_mission", return_value=0) as cancel:
                code = csv_batch_cli.main([str(csv_path), "--mission-id", "ctrl-c-test"])
            self.assertEqual(code, 130)
            cancel.assert_called_once_with("ctrl-c-test")


if __name__ == "__main__":
    unittest.main()

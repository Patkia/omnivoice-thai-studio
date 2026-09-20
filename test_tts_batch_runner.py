import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tts_batch_runner as batch


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.prepare_calls = []
        self.session = MagicMock(model_load_count=1, reference_prompt_prep_count=0)

    def prepare_reference_conditioning(self, reference_audio, reference_sha256,
                                       reference_text, reference_text_sha256, *, voice_project=""):
        self.prepare_calls.append((reference_audio, reference_sha256, reference_text,
                                   reference_text_sha256, voice_project))
        self.session.reference_prompt_prep_count = len(self.prepare_calls)
        return {
            "reference_prompt_cache_hit": False,
            "reference_prompt_prep_count": len(self.prepare_calls),
            "reference_audio": reference_audio,
            "reference_sha256": reference_sha256,
            "reference_text_sha256": reference_text_sha256,
            "reference_conditioning_enabled": True,
        }

    def generate(self, text, alias, speed, steps, output, force, seed=None, single_input=False, **kwargs):
        self.calls.append((text, alias, speed, steps, Path(output), force, seed))
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(b"RIFF-fake")
        return {"cache_hit": False, "inference_seconds": 1.25}


class BatchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="recovery")
        self.root = Path(self.temp.name)
        self.state_root = self.root / "state"
        self.state_patch = patch.object(batch, "STATE_ROOT", self.state_root)
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.temp.cleanup()

    def write_job(self, mission="mission-1", lines=None):
        if lines is None:
            lines = [
                {"id": "001", "text": "ข้อความหนึ่ง", "voice": "mipha_style"},
                {"id": "002", "text": "ข้อความสอง", "voice": "mipha_style"},
            ]
        path = self.root / "job.json"
        path.write_text(json.dumps({
            "mission_id": mission,
            "output_dir": str(self.root / "outputs"),
            "defaults": {"steps": 32},
            "lines": lines,
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def narrator_reference_fields(self):
        mapping = json.loads(Path("projects/triangle-strategy/voice_target_map.json").read_text(encoding="utf-8"))
        reference = mapping["targets"]["narrator"]["reference_conditioning"]
        return {
            "voice_project": "triangle-strategy",
            "voice_target": "narrator",
            "reference_conditioning": True,
            "reference_audio": reference["reference_audio"],
            "reference_sha256": reference["reference_sha256"],
            "reference_text": reference["reference_text"],
            "reference_text_sha256": reference["reference_text_sha256"],
        }

    def test_signature_changes_with_seed(self):
        base = {"text": "ทดสอบ", "voice": "narrator", "speed": 1.0, "steps": 32, "seed": None, "output": "001.wav"}
        other = dict(base, seed=15015)
        self.assertNotEqual(batch._line_signature(base), batch._line_signature(other))

    def test_signature_changes_with_voice_project(self):
        base = {"text": "ทดสอบ", "voice": "narrator", "speed": 1.0,
                "steps": 32, "output": "001.wav", "voice_project": "project-a"}
        self.assertNotEqual(batch._line_signature(base),
                            batch._line_signature(dict(base, voice_project="project-b")))

    def test_live_lock_blocks_duplicate_run(self):
        paths = batch._mission_paths("same")
        paths["lock"].parent.mkdir(parents=True, exist_ok=True)
        paths["lock"].write_text(json.dumps({"parent_pid": 111, "worker_pid": 222}), encoding="utf-8")
        with patch.object(batch, "_pid_alive", side_effect=lambda pid: pid == 222):
            with self.assertRaises(batch.BatchRunnerError):
                batch.acquire_lock("same")

    def test_stale_lock_is_recovered(self):
        paths = batch._mission_paths("stale")
        paths["lock"].parent.mkdir(parents=True, exist_ok=True)
        paths["lock"].write_text(json.dumps({"parent_pid": 111, "worker_pid": 222}), encoding="utf-8")
        with patch.object(batch, "_pid_alive", return_value=False):
            lock_path, lock = batch.acquire_lock("stale")
        self.assertEqual(lock["parent_pid"], batch.os.getpid())
        batch.release_lock(lock_path, batch.os.getpid())
        self.assertFalse(lock_path.exists())

    def test_checkpoint_rejects_changed_job(self):
        job_path = self.write_job()
        job = batch._load_job(job_path)
        checkpoint_path = batch._mission_paths(job["mission_id"])["checkpoint"]
        batch._load_or_init_checkpoint(job, checkpoint_path)
        changed = dict(job)
        changed["lines"] = [dict(job["lines"][0], text="ข้อความใหม่"), job["lines"][1]]
        with self.assertRaises(batch.BatchRunnerError):
            batch._load_or_init_checkpoint(changed, checkpoint_path)

    def test_worker_is_sequential_atomic_and_resume_skips_completed(self):
        job_path = self.write_job()
        job = batch._load_job(job_path)
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        checkpoint_path = self.root / "checkpoint.json"
        fake = FakeAdapter()
        with patch.object(batch, "StudioEngineAdapter", return_value=fake):
            self.assertEqual(batch.worker_main(snapshot, checkpoint_path), 0)
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue((self.root / "outputs" / "001.wav").exists())
        self.assertTrue((self.root / "outputs" / "002.wav").exists())
        self.assertFalse((self.root / "outputs" / "001.wav.part").exists())
        checkpoint = batch._read_json(checkpoint_path)
        self.assertEqual(checkpoint["status"], "completed")
        self.assertEqual(checkpoint["lines"]["001"]["status"], "completed")
        fake2 = FakeAdapter()
        with patch.object(batch, "StudioEngineAdapter", return_value=fake2):
            self.assertEqual(batch.worker_main(snapshot, checkpoint_path), 0)
        self.assertEqual(fake2.calls, [])

    def test_crash_after_atomic_rename_recovers_without_regeneration(self):
        job_path = self.write_job(lines=[{"id": "001", "text": "ข้อความ", "voice": "narrator"}])
        job = batch._load_job(job_path)
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        checkpoint_path = self.root / "checkpoint.json"
        checkpoint = batch._new_checkpoint(job)
        checkpoint["status"] = "running"
        checkpoint["current_line_id"] = "001"
        checkpoint["lines"]["001"].update({"status": "running", "started_at_epoch": 100.0})
        batch._atomic_json(checkpoint_path, checkpoint)
        output = self.root / "outputs" / "001.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"committed")
        fake = FakeAdapter()
        with patch.object(batch, "StudioEngineAdapter", return_value=fake):
            self.assertEqual(batch.worker_main(snapshot, checkpoint_path), 0)
        self.assertEqual(fake.calls, [])
        final = batch._read_json(checkpoint_path)
        self.assertTrue(final["lines"]["001"].get("recovered_after_crash"))
        self.assertEqual(final["status"], "completed")

    def test_unowned_existing_output_is_not_overwritten(self):
        job_path = self.write_job(lines=[{"id": "001", "text": "ข้อความ", "voice": "narrator"}])
        job = batch._load_job(job_path)
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        output = self.root / "outputs" / "001.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"existing")
        with patch.object(batch, "StudioEngineAdapter", return_value=FakeAdapter()):
            self.assertEqual(batch.worker_main(snapshot, self.root / "checkpoint.json"), 0)
        self.assertEqual(output.read_bytes(), b"existing")
        checkpoint = batch._read_json(self.root / "checkpoint.json")
        self.assertEqual(checkpoint["lines"]["001"]["status"], "skipped")

    def test_worker_uses_shared_studio_routing_with_seed(self):
        job_path = self.write_job(lines=[{
            "id": "001", "text": "ข้อความ", "voice": "narrator", "seed": 15015,
            "instruction_override": "female, young adult, moderate pitch",
        }])
        job = batch._load_job(job_path)
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        fake = FakeAdapter()
        def routed(*args, **kwargs):
            output = Path(args[5])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"RIFF-routed")
            return {"cache_hit": False, "inference_seconds": 1.0}
        with patch.object(batch, "StudioEngineAdapter", return_value=fake), \
             patch.object(batch, "generate_studio_request", side_effect=routed) as route:
            self.assertEqual(batch.worker_main(snapshot, self.root / "checkpoint.json"), 0)
        self.assertEqual(route.call_count, 1)
        self.assertEqual(route.call_args.kwargs["seed"], 15015)
        self.assertEqual(route.call_args.kwargs["instruction_override"], "female, young adult, moderate pitch")

    def test_line_signature_changes_with_instruction_override(self):
        base = {"text": "ทดสอบ", "voice": "narrator", "speed": 1.0, "steps": 32,
                "seed": 15015, "instruction_override": None, "output": "001.wav"}
        overridden = dict(base, instruction_override="female, young adult, moderate pitch")
        self.assertNotEqual(batch._line_signature(base), batch._line_signature(overridden))

    def test_reference_config_changes_line_signature(self):
        base = {"text": "ทดสอบ", "voice": "bright_female", "speed": 1.0, "steps": 32,
                "seed": 15016, "instruction_override": "female, young adult, moderate pitch",
                "output": "001.wav", "reference_conditioning": False}
        conditioned = dict(base, **self.narrator_reference_fields())
        self.assertNotEqual(batch._line_signature(base), batch._line_signature(conditioned))

    def test_generation_mode_and_direct_controls_change_line_signature(self):
        base = {"text": "ทดสอบ", "voice": "narrator", "speed": 1.0, "steps": 32,
                "seed": 15032, "instruction_override": None, "output": "001.wav",
                "generation_mode": "voice_design"}
        direct = dict(base, generation_mode="reference_first", language="Thai",
                      denoise=True, postprocess_output=True)
        self.assertNotEqual(batch._line_signature(base), batch._line_signature(direct))

    def test_reference_first_is_forwarded_without_instruction_and_prompt_is_reused(self):
        mapping = json.loads(Path("projects/triangle-strategy/voice_target_map.json").read_text(encoding="utf-8"))
        target = mapping["targets"]["serenoa"]
        reference = target["reference_conditioning"]
        common = {
            "voice": target["profile_alias"], "speed": target["speed"],
            "steps": target["steps"], "seed": target["seed"],
            "generation_mode": target["generation_mode"], "language": target["language"],
            "denoise": target["denoise"], "postprocess_output": target["postprocess_output"],
            "voice_project": "triangle-strategy",
            "voice_target": "serenoa", "reference_conditioning": True,
            "reference_audio": reference["reference_audio"],
            "reference_sha256": reference["reference_sha256"],
            "reference_text": reference["reference_text"],
            "reference_text_sha256": reference["reference_text_sha256"],
        }
        lines = [
            {"id": "001", "text": "ข้อความหนึ่ง", "output": "001.wav", **common},
            {"id": "002", "text": "ข้อความสอง", "output": "002.wav", **common},
        ]
        job = batch._load_job(self.write_job(lines=lines))
        self.assertTrue(all(line["instruction_override"] is None for line in job["lines"]))
        snapshot = self.root / "direct.snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        fake = FakeAdapter()

        def routed(*args, **kwargs):
            output = Path(args[5])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"RIFF-reference-first-fake")
            return {"cache_hit": False, "inference_seconds": 1.0}

        with patch.object(batch, "StudioEngineAdapter", return_value=fake), \
             patch.object(batch, "generate_studio_request", side_effect=routed) as route:
            self.assertEqual(batch.worker_main(snapshot, self.root / "direct-checkpoint.json"), 0)
        self.assertEqual(len(fake.prepare_calls), 1)
        self.assertEqual(fake.prepare_calls[0][-1], "triangle-strategy")
        self.assertEqual(route.call_count, 2)
        for call in route.call_args_list:
            self.assertEqual(call.kwargs["generation_mode"], "reference_first")
            self.assertIsNone(call.kwargs["instruction_override"])
            self.assertEqual(call.kwargs["language"], "Thai")
            self.assertTrue(call.kwargs["denoise"])
            self.assertTrue(call.kwargs["postprocess_output"])

    def test_narrator_reference_prompt_prepared_once_and_reused_across_rows(self):
        reference = self.narrator_reference_fields()
        lines = [
            {"id": "001", "text": "ข้อความหนึ่ง", "voice": "bright_female", "speed": 1.0,
             "steps": 32, "seed": 15016, "instruction_override": "female, young adult, moderate pitch",
             "output": "001.wav", **reference},
            {"id": "002", "text": "ข้อความสอง", "voice": "bright_female", "speed": 1.0,
             "steps": 32, "seed": 15016, "instruction_override": "female, young adult, moderate pitch",
             "output": "002.wav", **reference},
        ]
        job = batch._load_job(self.write_job(lines=lines))
        snapshot = self.root / "reference.snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        fake = FakeAdapter()

        def routed(*args, **kwargs):
            output = Path(args[5])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"RIFF-reference-fake")
            return {"cache_hit": False, "inference_seconds": 1.0}

        with patch.object(batch, "StudioEngineAdapter", return_value=fake), \
             patch.object(batch, "generate_studio_request", side_effect=routed) as route:
            self.assertEqual(batch.worker_main(snapshot, self.root / "reference-checkpoint.json"), 0)
        self.assertEqual(len(fake.prepare_calls), 1)
        self.assertEqual(fake.prepare_calls[0][-1], "triangle-strategy")
        self.assertEqual(route.call_count, 2)
        for call in route.call_args_list:
            self.assertTrue(call.kwargs["reference_conditioning"])
            self.assertEqual(call.kwargs["reference_sha256"], reference["reference_sha256"])
            self.assertEqual(call.kwargs["seed"], 15016)
        checkpoint = batch._read_json(self.root / "reference-checkpoint.json")
        self.assertEqual(checkpoint["runtime"]["model_load_count"], 1)
        self.assertEqual(checkpoint["runtime"]["reference_prompt_prep_count"], 1)
        prompt = next(iter(checkpoint["reference_prompts"].values()))
        self.assertEqual(prompt["status"], "prepared")

    def test_incomplete_reference_config_fails_before_adapter_or_generation(self):
        lines = [{
            "id": "001", "text": "ข้อความ", "voice": "bright_female",
            "reference_conditioning": True, "reference_audio": "missing.wav",
        }]
        with self.assertRaisesRegex(batch.BatchRunnerError, "ห้าม fallback"):
            batch._load_job(self.write_job(lines=lines))

    def test_reference_prompt_failure_happens_before_any_row_generation(self):
        reference = self.narrator_reference_fields()
        lines = [{
            "id": "001", "text": "ข้อความ", "voice": "bright_female", "speed": 1.0,
            "steps": 32, "seed": 15016, "instruction_override": "female, young adult, moderate pitch",
            "output": "001.wav", **reference,
        }]
        job = batch._load_job(self.write_job(lines=lines))
        snapshot = self.root / "failed-reference.snapshot.json"
        snapshot.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        fake = FakeAdapter()
        fake.prepare_reference_conditioning = MagicMock(side_effect=RuntimeError("prompt failed"))
        with patch.object(batch, "StudioEngineAdapter", return_value=fake), \
             patch.object(batch, "generate_studio_request") as route:
            with self.assertRaisesRegex(RuntimeError, "prompt failed"):
                batch.worker_main(snapshot, self.root / "failed-reference-checkpoint.json")
        route.assert_not_called()
        checkpoint = batch._read_json(self.root / "failed-reference-checkpoint.json")
        self.assertEqual(checkpoint["status"], "failed")
        self.assertEqual(checkpoint["lines"]["001"]["status"], "pending")
        self.assertEqual(next(iter(checkpoint["reference_prompts"].values()))["status"], "failed")

    def test_windows_background_process_uses_no_console_and_process_group(self):
        class FakeStartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        with patch.object(batch.os, "name", "nt"), \
             patch.object(batch.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
             patch.object(batch.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             patch.object(batch.subprocess, "STARTF_USESHOWWINDOW", 1, create=True), \
             patch.object(batch.subprocess, "SW_HIDE", 0, create=True), \
             patch.object(batch.subprocess, "STARTUPINFO", FakeStartupInfo, create=True):
            options = batch.background_process_kwargs()
        self.assertEqual(options["creationflags"], 0x08000200)
        self.assertEqual(options["startupinfo"].dwFlags, 1)
        self.assertEqual(options["startupinfo"].wShowWindow, 0)

    def test_windows_tasklist_poll_uses_no_console_without_new_process_group(self):
        class FakeStartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        result = MagicMock(stdout="1234 python.exe")
        with patch.object(batch.os, "name", "nt"), \
             patch.object(batch.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
             patch.object(batch.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             patch.object(batch.subprocess, "STARTF_USESHOWWINDOW", 1, create=True), \
             patch.object(batch.subprocess, "SW_HIDE", 0, create=True), \
             patch.object(batch.subprocess, "STARTUPINFO", FakeStartupInfo, create=True), \
             patch.object(batch.subprocess, "run", return_value=result) as run:
            self.assertTrue(batch._pid_alive(1234))
        self.assertEqual(run.call_args.args[0][:2], ["tasklist", "/FI"])
        self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
        self.assertNotEqual(run.call_args.kwargs["creationflags"] & 0x200, 0x200)
        self.assertIsInstance(run.call_args.kwargs["startupinfo"], FakeStartupInfo)

    def test_windows_taskkill_uses_no_console(self):
        with patch.object(batch.os, "name", "nt"), \
             patch.object(batch.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             patch.object(batch, "_pid_alive", return_value=True), \
             patch.object(batch.subprocess, "run") as run:
            batch._kill_tree(1234)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "1234", "/T", "/F"])
        self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)

    def test_worker_spawn_uses_shared_background_process_options(self):
        options = {"creationflags": 123}
        with patch.object(batch, "background_process_kwargs", return_value=options), \
             patch.object(batch.subprocess, "Popen", return_value=MagicMock()) as popen:
            batch._spawn_worker(Path("snapshot.json"), Path("checkpoint.json"))
        self.assertEqual(popen.call_args.kwargs["creationflags"], 123)

    def test_watchdog_kills_only_worker_and_marks_timeout(self):
        checkpoint_path = self.root / "checkpoint.json"
        checkpoint = {
            "status": "running", "current_line_id": "001", "updated_at": "x",
            "lines": {"001": {"status": "running", "started_at_epoch": 100.0}},
        }
        batch._atomic_json(checkpoint_path, checkpoint)
        proc = MagicMock(pid=4321)
        proc.poll.return_value = None
        with patch.object(batch.time, "time", return_value=111.0), patch.object(batch, "_kill_tree") as kill:
            code = batch._watch_worker(proc, checkpoint_path, line_timeout=10.0, poll_seconds=0)
        self.assertEqual(code, 124)
        kill.assert_called_once_with(4321)
        final = batch._read_json(checkpoint_path)
        self.assertEqual(final["status"], "timeout")
        self.assertEqual(final["lines"]["001"]["status"], "timeout")

    def test_default_timeout_is_conservative_and_per_item(self):
        self.assertEqual(batch.DEFAULT_LINE_TIMEOUT_SECONDS, 1800.0)
        checkpoint_path = self.root / "checkpoint.json"
        checkpoint = {
            "status": "running", "current_line_id": "001",
            "lines": {"001": {"status": "running", "started_at_epoch": 100.0},
                       "002": {"status": "completed"}},
        }
        batch._atomic_json(checkpoint_path, checkpoint)
        proc = MagicMock(pid=4321); proc.poll.return_value = None
        with patch.object(batch.time, "time", return_value=200.0), patch.object(batch, "_kill_tree") as kill:
            code = batch._watch_worker(proc, checkpoint_path, line_timeout=50.0, poll_seconds=0)
        self.assertEqual(code, 124)
        kill.assert_called_once_with(4321)
        final = batch._read_json(checkpoint_path)
        self.assertEqual(final["lines"]["002"]["status"], "completed")

    def test_timeout_removes_only_partial_output_and_preserves_completed_output(self):
        output_dir = self.root / "outputs"; output_dir.mkdir(parents=True)
        (output_dir / "001.wav").write_bytes(b"completed")
        (output_dir / "002.part.wav").write_bytes(b"partial")
        checkpoint_path = self.root / "checkpoint.json"
        batch._atomic_json(checkpoint_path, {
            "status": "running", "current_line_id": "002",
            "lines": {"001": {"status": "completed", "output": "001.wav"},
                       "002": {"status": "running", "output": "002.wav", "started_at_epoch": 100.0}},
        })
        proc = MagicMock(pid=4321); proc.poll.return_value = None
        with patch.object(batch.time, "time", return_value=200.0), patch.object(batch, "_kill_tree"):
            self.assertEqual(batch._watch_worker(proc, checkpoint_path, 50.0, 0, output_dir), 124)
        self.assertTrue((output_dir / "001.wav").exists())
        self.assertFalse((output_dir / "002.part.wav").exists())

    def test_cancel_kills_mission_processes_and_preserves_resume_state(self):
        paths = batch._mission_paths("cancel-me")
        paths["base"].mkdir(parents=True, exist_ok=True)
        batch._atomic_json(paths["lock"], {"mission_id": "cancel-me", "parent_pid": 111, "worker_pid": 222})
        batch._atomic_json(paths["checkpoint"], {
            "mission_id": "cancel-me", "status": "running", "current_line_id": "002",
            "lines": {"001": {"status": "completed"}, "002": {"status": "running"}},
        })
        with patch.object(batch, "_kill_tree") as kill:
            self.assertEqual(batch.cancel_mission("cancel-me"), 0)
        self.assertEqual([call.args[0] for call in kill.call_args_list], [222, 111])
        checkpoint = batch._read_json(paths["checkpoint"])
        self.assertEqual(checkpoint["lines"]["001"]["status"], "completed")
        self.assertEqual(checkpoint["lines"]["002"]["status"], "cancelled")
        self.assertFalse(paths["lock"].exists())


if __name__ == "__main__":
    unittest.main()

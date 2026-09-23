from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
from pathlib import Path

from csv_batch import (CsvBatchError, CsvBatchRow, ERROR, PENDING, SKIPPED,
                       build_job, default_project_output_dir, read_csv,
                       resolve_generation_config, row_diagnostic,
                       validate_rows, validate_voice_project_id,
                       voice_project_map_path)
from long_text_batch import is_long


class CsvBatchTests(unittest.TestCase):
    PROJECT = "triangle-strategy"

    def write_csv(self, root: Path, content: str, *, bom: bool = False) -> Path:
        path = root / "rows.csv"
        path.write_text(content, encoding="utf-8-sig" if bom else "utf-8")
        return path

    def test_utf8_bom_and_quoted_comma_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = self.write_csv(root, 'file_name,thai_text,prosody_note\n001.wav,"สวัสดี, โลก","เว้นจังหวะ"\n', bom=True)
            rows = read_csv(path)
        self.assertEqual(rows[0].thai_text, "สวัสดี, โลก")
        self.assertEqual(rows[0].metadata("prosody_note"), "เว้นจังหวะ")

    def test_required_columns_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(CsvBatchError):
                read_csv(self.write_csv(Path(temp), "file_name\n001.wav\n"))

    def test_validation_rejects_duplicate_paths_and_missing_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = read_csv(self.write_csv(root, "file_name,thai_text\nA.wav,ข้อความไทย\na.WAV,ข้อความไทย\n../bad.wav,ข้อความไทย\nempty.wav,\n"))
            validate_rows(rows, root / "out", "narrator")
        self.assertEqual(rows[0].status, PENDING)
        self.assertEqual(rows[1].status, ERROR)
        self.assertEqual(rows[2].status, ERROR)
        self.assertEqual(rows[3].status, ERROR)

    def test_existing_output_is_skipped_by_default_and_overwrite_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); output = root / "out"; output.mkdir(); (output / "001.wav").write_bytes(b"old")
            rows = read_csv(self.write_csv(root, "file_name,thai_text\n001.wav,ข้อความไทย\n"))
            validate_rows(rows, output, "narrator")
            self.assertEqual(rows[0].status, SKIPPED)
            rows[0].selected = True
            job = build_job(rows, output, "narrator", 0.94, 32, overwrite_selected=True)
        self.assertTrue(job["lines"][0]["force"])

    def test_fresh_import_reset_deselects_existing_output_even_in_overwrite_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out"
            output.mkdir()
            (output / "001.wav").write_bytes(b"existing")
            rows = [CsvBatchRow(2, {
                "file_name": "001.wav",
                "thai_text": "\u0e02\u0e49\u0e2d\u0e04\u0e27\u0e32\u0e21\u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22",
                "voice_project": "triangle-strategy",
                "voice_target": "serenoa",
            })]
            validate_rows(rows, output, "narrator", skip_existing=False, reset_selection=True)
            self.assertFalse(rows[0].selected)
            self.assertEqual(rows[0].status, PENDING)

            # An explicit user selection survives later validation when
            # overwrite mode is enabled.
            rows[0].selected = True
            validate_rows(rows, output, "narrator", skip_existing=False)
            self.assertTrue(rows[0].selected)

    def test_real_triangle_strategy_import_row_with_existing_output_is_unselected(self):
        source = Path(__file__).resolve().parent / "imports" / "chapter1_omnivoice_studio.csv"
        rows = [row for row in read_csv(source)
                if row.values.get("self_id") == "MS01_X01_A1_1005_M_SEL_0030"]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            output.mkdir()
            (output / rows[0].file_name).write_bytes(b"existing")
            validate_rows(rows, output, "narrator", skip_existing=False, reset_selection=True)
        self.assertFalse(rows[0].selected)

    def test_only_selected_rows_and_only_thai_text_enter_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = read_csv(self.write_csv(root, "file_name,thai_text,pronunciation_note,character_name\n001.wav,ข้อความหนึ่ง,หมายเหตุ,ผู้บรรยาย\n002.wav,ข้อความสอง,หมายเหตุสอง,ตัวละคร\n"))
            validate_rows(rows, root / "out", "narrator")
            rows[1].selected = False
            job = build_job(rows, root / "out", "narrator", 0.94, 32, mission_id="csv-test")
        self.assertEqual(len(job["lines"]), 1)
        line = job["lines"][0]
        self.assertEqual(line["id"], "csv-00002")
        self.assertEqual(line["text"], "ข้อความหนึ่ง")
        self.assertEqual(line["output"], "001.wav")
        self.assertFalse(line["force"])
        self.assertNotIn("pronunciation_note", line)
        self.assertNotIn("character_name", line)

    def test_narrator_resolves_from_map_with_profile_seed(self):
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย",
                              "voice_project": self.PROJECT, "voice_target": "narrator"})
        config = resolve_generation_config(row, "ancient_deep_male", 0.68, 12)
        self.assertEqual(config.profile_alias, "bright_female")
        self.assertIsNone(config.instruction)
        self.assertIsNone(config.instruction_override)
        self.assertEqual(config.speed, 1.20)
        self.assertEqual(config.steps, 32)
        self.assertEqual(config.seed, 15016)
        self.assertTrue(config.reference_conditioning)
        self.assertEqual(config.reference_audio, "assets/triangle-strategy/approved_voice_references/narrator.wav")
        self.assertEqual(config.reference_sha256, "902230792ec5b4f0bf64510281f41e0618c3c3fb9b95de98a349d66a11924dd3")
        self.assertEqual(config.generation_mode, "reference_first")

    def test_approved_triangle_targets_resolve_reference_first_with_canonical_controls(self):
        expected = {
            "roland": ("young_male", 1.3, 32, 26003, "assets/triangle-strategy/approved_voice_references/roland.wav"),
            "benedict": ("young_male", 1.2, 32, 42010, "assets/triangle-strategy/approved_voice_references/booker.wav"),
            "frederica": ("bright_female", 1.24, 32, 15016, "assets/triangle-strategy/approved_voice_references/frederica.wav"),
        }
        for target, (alias, speed, steps, seed, reference) in expected.items():
            config = resolve_generation_config(
                CsvBatchRow(2, {"file_name": f"{target}.wav", "thai_text": "ข้อความไทย",
                                "voice_project": self.PROJECT, "voice_target": target}),
                "narrator",
            )
            self.assertEqual(config.generation_mode, "reference_first")
            self.assertEqual(config.profile_alias, alias)
            self.assertEqual((config.speed, config.steps, config.seed), (speed, steps, seed))
            self.assertEqual(config.reference_audio, reference)
            self.assertTrue(config.reference_conditioning)
            self.assertIsNone(config.instruction)
            self.assertIsNone(config.instruction_override)

    def test_triangle_row_speed_overrides_apply_only_to_requested_rows(self):
        source = Path(__file__).resolve().parent / "imports" / "chapter1_omnivoice_studio.csv"
        rows = read_csv(source)
        expected = {
            "MS01_X01_A0_0020_F_HEW_0030": (1.26, 1.3),
            "MS01_X01_A0_0030_M_FRN_0010": (1.22, 1.3),
            "MS01_X01_A1_0010_F_YRA_0020": (1.22, 1.3),
            "MS01_X01_A1_1020_M_ELA_0010": (1.22, 1.3),
            "MS01_X01_A1_1030_M_SMN_0030": (1.18, 1.3),
            "MS01_X01_BATTLE_01_BEFORE_M_TRA_0020": (1.24, 1.3),
        }
        by_id = {row.metadata("self_id"): row for row in rows}
        self.assertTrue(expected.keys() <= by_id.keys())
        mapping = json.loads(voice_project_map_path(self.PROJECT).read_text(encoding="utf-8"))
        for self_id, (old_speed, new_speed) in expected.items():
            row = by_id[self_id]
            target = row.metadata("voice_target")
            before = mapping["targets"][target]
            config = resolve_generation_config(row, "narrator")
            self.assertEqual(float(before["speed"]), old_speed, self_id)
            self.assertAlmostEqual(config.speed, new_speed, places=6, msg=self_id)
            self.assertEqual(config.voice_target, target)
            self.assertEqual(config.reference_audio, before["reference_conditioning"]["reference_audio"])
            self.assertEqual(config.seed, before["seed"])
            self.assertEqual(config.steps, before["steps"])

        untouched = by_id["MS01_X01_A1_0010_F_FRE_0030"]
        untouched_config = resolve_generation_config(untouched, "narrator")
        self.assertEqual(untouched_config.speed,
                         mapping["targets"][untouched.metadata("voice_target")]["speed"])

    def test_all_complete_approved_references_are_reference_first(self):
        mapping = json.loads(voice_project_map_path(self.PROJECT).read_text(encoding="utf-8"))
        for target, data in mapping["targets"].items():
            config = resolve_generation_config(
                CsvBatchRow(2, {"file_name": f"{target}.wav", "thai_text": "ข้อความไทย",
                                "voice_project": self.PROJECT, "voice_target": target}),
                "narrator",
            )
            self.assertEqual(config.generation_mode, "reference_first", target)
            self.assertTrue(config.reference_conditioning, target)
            self.assertIsNone(config.instruction, target)

    def test_reference_first_cache_identity_differs_from_voice_design(self):
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย",
                              "voice_project": self.PROJECT, "voice_target": "roland"})
        config = resolve_generation_config(row, "narrator")
        reference_payload = {"text": row.thai_text, "voice_instruction": None,
                             "generation_mode": config.generation_mode, "reference_sha256": config.reference_sha256,
                             "reference_conditioning": True, "voice_project": self.PROJECT}
        old_payload = dict(reference_payload, generation_mode="voice_design", voice_instruction="male, teenager, moderate pitch")
        from studio_engine_adapter import generation_cache_keys
        self.assertNotEqual(generation_cache_keys(reference_payload, config.seed), generation_cache_keys(old_payload, config.seed))

    def test_serenoa_reference_first_config_and_job_are_canonical(self):
        row = CsvBatchRow(2, {
            "file_name": "001.wav", "thai_text": "ข้อความไทย",
            "voice_project": self.PROJECT, "voice_target": "serenoa",
            "reference_audio": "untrusted.csv.override.wav",
        })
        config = resolve_generation_config(row, "bright_female")
        self.assertEqual(config.generation_mode, "reference_first")
        self.assertEqual(config.profile_alias, "narrator")
        self.assertIsNone(config.instruction_override)
        self.assertEqual((config.speed, config.steps, config.seed), (1.26, 32, 15032))
        self.assertEqual(config.reference_audio,
                         "assets/triangle-strategy/approved_voice_references/serenoa.wav")
        self.assertNotEqual(config.reference_audio, row.metadata("reference_audio"))

    def test_reference_first_without_reference_fails_closed(self):
        mapping = {
            "schema_version": 1,
            "targets": {"direct": {
                "profile_alias": "narrator", "generation_mode": "reference_first",
                "speed": 1.0, "steps": 32, "seed": 15032,
            }},
        }
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย", "voice_target": "direct"})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path = Path(temp) / "map.json"
            path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "reference_first"):
                resolve_generation_config(row, "narrator", map_path=path)

    def test_multiple_voice_targets_resolve_independently(self):
        mapping = json.loads(voice_project_map_path(self.PROJECT).read_text(encoding="utf-8"))
        mapping["targets"]["narrator_alt"] = dict(mapping["targets"]["narrator"])
        with tempfile.TemporaryDirectory() as temp:
            map_path = Path(temp) / "voice_target_map.json"
            map_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
            first = resolve_generation_config(
                CsvBatchRow(2, {"file_name": "a.wav", "thai_text": "ข้อความไทย", "voice_target": "narrator"}),
                "narrator", map_path=map_path,
            )
            second = resolve_generation_config(
                CsvBatchRow(3, {"file_name": "b.wav", "thai_text": "ข้อความไทย", "voice_target": "narrator_alt"}),
                "narrator", map_path=map_path,
            )
        self.assertEqual(first.voice_target, "narrator")
        self.assertEqual(second.voice_target, "narrator_alt")
        self.assertEqual(first.profile_alias, "bright_female")
        self.assertEqual(second.profile_alias, "bright_female")

    def test_same_target_resolves_from_each_project_map_without_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            projects_root = Path(temp)
            configs = {
                "project-a": ("narrator", "male, middle-aged, low pitch", 0.94, 15015),
                "project-b": ("bright_female", "female, young adult, moderate pitch", 1.0, 15016),
            }
            for project, (alias, instruction, mapped_speed, seed) in configs.items():
                directory = projects_root / project
                directory.mkdir()
                (directory / "voice_target_map.json").write_text(json.dumps({
                    "schema_version": 1,
                    "targets": {"lead": {
                        "profile_alias": alias,
                        "instruction_override": instruction,
                        "speed": mapped_speed,
                        "steps": 32,
                        "seed": seed,
                    }},
                }), encoding="utf-8")
            first = resolve_generation_config(
                CsvBatchRow(2, {"file_name": "a.wav", "thai_text": "ข้อความไทย",
                                "voice_project": "project-a", "voice_target": "lead"}),
                "narrator", projects_root=projects_root,
            )
            second = resolve_generation_config(
                CsvBatchRow(3, {"file_name": "b.wav", "thai_text": "ข้อความไทย",
                                "voice_project": "project-b", "voice_target": "lead"}),
                "narrator", projects_root=projects_root,
            )
        self.assertEqual((first.voice_project, first.profile_alias), ("project-a", "narrator"))
        self.assertEqual((second.voice_project, second.profile_alias), ("project-b", "bright_female"))

    def test_narrator_reference_missing_or_hash_mismatch_fails_resolution(self):
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย", "voice_target": "narrator"})
        reference_text = "ข้อความอ้างอิง"
        base_target = {
            "profile_alias": "bright_female",
            "instruction_override": "female, young adult, moderate pitch",
            "speed": 1.0,
            "steps": 32,
            "seed": 15016,
            "reference_conditioning": {
                "enabled": True,
                "reference_audio": "assets/triangle-strategy/approved_voice_references/missing.wav",
                "reference_sha256": "0" * 64,
                "reference_text": reference_text,
                "reference_text_sha256": hashlib.sha256(reference_text.encode("utf-8")).hexdigest(),
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "map.json"
            path.write_text(json.dumps({"schema_version": 1, "targets": {"narrator": base_target}}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "ไม่พบ approved reference_audio"):
                resolve_generation_config(row, "narrator", map_path=path)
            base_target["reference_conditioning"]["reference_audio"] = "assets/triangle-strategy/approved_voice_references/narrator.wav"
            path.write_text(json.dumps({"schema_version": 1, "targets": {"narrator": base_target}}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "SHA256"):
                resolve_generation_config(row, "narrator", map_path=path)

    def test_unknown_voice_target_is_rejected_before_job_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = read_csv(self.write_csv(
                root,
                "file_name,thai_text,voice_project,voice_target\n"
                "001.wav,ข้อความไทย,triangle-strategy,unknown_role\n",
            ))
            validate_rows(rows, root / "out", "narrator")
        self.assertEqual(rows[0].status, ERROR)
        self.assertEqual(rows[0].error_stage, "VOICE_TARGET_RESOLUTION")
        self.assertIn("unknown_role", rows[0].error)

    def test_empty_voice_target_preserves_studio_ui_fallback(self):
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย", "voice_target": ""})
        config = resolve_generation_config(row, "ancient_deep_male", 0.68, 32)
        self.assertEqual(config.source, "studio_ui_fallback")
        self.assertEqual(config.profile_alias, "ancient_deep_male")
        self.assertEqual(config.speed, 0.68)
        self.assertEqual(config.steps, 32)

    def test_narrator_job_persists_resolved_config_without_metadata_in_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = read_csv(self.write_csv(
                root,
                "file_name,thai_text,voice_project,voice_target,pronunciation_note,prosody_note,character_name\n"
                "001.wav,ข้อความไทย,triangle-strategy,narrator,โน้ตออกเสียง,โน้ตจังหวะ,ผู้บรรยาย\n",
            ))
            validate_rows(rows, root / "out", "ancient_deep_male", speed=0.68, steps=12)
            job = build_job(rows, root / "out", "ancient_deep_male", 0.68, 12)
        line = job["lines"][0]
        self.assertEqual(line["text"], "ข้อความไทย")
        self.assertEqual(line["voice"], "bright_female")
        self.assertIsNone(line["instruction_override"])
        self.assertEqual((line["speed"], line["steps"], line["seed"]), (1.20, 32, 15016))
        self.assertTrue(line["reference_conditioning"])
        self.assertEqual(line["reference_sha256"], "902230792ec5b4f0bf64510281f41e0618c3c3fb9b95de98a349d66a11924dd3")

    def test_tts_text_absent_or_blank_falls_back_to_canonical_text(self):
        absent = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความจริง"})
        blank = CsvBatchRow(3, {"file_name": "002.wav", "thai_text": "ข้อความจริง", "tts_text": "  "})
        self.assertEqual(absent.spoken_text, "ข้อความจริง")
        self.assertEqual(blank.spoken_text, "ข้อความจริง")

    def test_tts_text_overrides_only_spoken_input(self):
        row = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "นอร์เซเลีย", "tts_text": "นอร์ เซ เลีย"})
        self.assertEqual(row.thai_text, "นอร์เซเลีย")
        self.assertEqual(row.spoken_text, "นอร์ เซ เลีย")

    def test_human_approved_norselia_override_keeps_canonical_text(self):
        row = CsvBatchRow(2, {
            "file_name": "001.wav", "thai_text": "นอร์เซเลีย",
            "tts_text": "นอร์-เซ-เลีย", "voice_target": "narrator",
        })
        self.assertEqual(row.thai_text, "นอร์เซเลีย")
        self.assertEqual(row.spoken_text, "นอร์-เซ-เลีย")

    def test_job_and_diagnostic_preserve_canonical_override_and_spoken_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = read_csv(self.write_csv(
                root,
                "file_name,thai_text,tts_text,pronunciation_note,prosody_note,voice_project,voice_target\n"
                "001.wav,นอร์เซเลีย,นอร์ เซ เลีย,metadata-only,metadata-only,triangle-strategy,narrator\n",
            ))
            validate_rows(rows, root / "out", "narrator")
            job = build_job(rows, root / "out", "narrator", 0.94, 32)
        line = job["lines"][0]
        self.assertEqual(line["text"], "นอร์ เซ เลีย")
        self.assertEqual(line["canonical_text"], "นอร์เซเลีย")
        self.assertEqual(line["tts_text"], "นอร์ เซ เลีย")
        self.assertEqual(line["resolved_spoken_text"], "นอร์ เซ เลีย")
        self.assertNotIn("pronunciation_note", line)
        self.assertNotIn("prosody_note", line)
        diagnostic = row_diagnostic(rows[0])
        self.assertEqual(diagnostic["thai_text"], "นอร์เซเลีย")
        self.assertEqual(diagnostic["tts_text"], "นอร์ เซ เลีย")
        self.assertEqual(diagnostic["resolved_spoken_text"], "นอร์ เซ เลีย")

    def test_routing_length_is_based_on_resolved_spoken_text(self):
        canonical_long = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ก" * 501, "tts_text": "ก" * 500})
        override_long = CsvBatchRow(3, {"file_name": "002.wav", "thai_text": "ก" * 500, "tts_text": "ก" * 501})
        self.assertFalse(is_long(canonical_long.spoken_text))
        self.assertTrue(is_long(override_long.spoken_text))

    def test_serenoa_regen_csv_has_53_rows_and_uses_map_as_source_of_truth(self):
        rows = read_csv(Path("imports/chapter1_serenoa_regen.csv"))
        self.assertEqual(len(rows), 53)
        self.assertEqual({row.metadata("voice_project") for row in rows}, {self.PROJECT})
        self.assertEqual({row.metadata("voice_target") for row in rows}, {"serenoa"})
        for row in rows:
            config = resolve_generation_config(row, "bright_female")
            self.assertEqual(config.generation_mode, "reference_first")
            self.assertEqual(config.reference_audio,
                             "assets/triangle-strategy/approved_voice_references/serenoa.wav")

    def test_existing_triangle_strategy_csv_is_fully_project_migrated(self):
        rows = read_csv(Path("imports/chapter1_omnivoice_studio.csv"))
        self.assertEqual(len(rows), 323)
        self.assertEqual({row.metadata("voice_project") for row in rows}, {self.PROJECT})
        self.assertEqual(len({row.file_name.casefold() for row in rows}), 323)

    def test_project_id_validation_and_path_are_safe(self):
        self.assertEqual(validate_voice_project_id(self.PROJECT), self.PROJECT)
        self.assertEqual(
            voice_project_map_path(self.PROJECT),
            Path("projects/triangle-strategy/voice_target_map.json").resolve(),
        )
        for invalid in ("../triangle-strategy", "triangle/strategy", "Triangle Strategy", ""):
            with self.subTest(invalid=invalid), self.assertRaises(Exception):
                validate_voice_project_id(invalid)

    def test_batch_rejects_mixed_or_ambiguous_projects(self):
        from csv_batch import batch_voice_project
        mixed = [
            CsvBatchRow(2, {"file_name": "a.wav", "thai_text": "ข้อความ",
                            "voice_project": "project-a"}),
            CsvBatchRow(3, {"file_name": "b.wav", "thai_text": "ข้อความ"}),
        ]
        ambiguous = [
            CsvBatchRow(2, {"file_name": "a.wav", "thai_text": "ข้อความ",
                            "voice_project": "project-a"}),
            CsvBatchRow(3, {"file_name": "b.wav", "thai_text": "ข้อความ",
                            "voice_project": "project-b"}),
        ]
        with self.assertRaises(CsvBatchError):
            batch_voice_project(mixed)
        with self.assertRaises(CsvBatchError):
            batch_voice_project(ambiguous)

    def test_project_changes_job_identity_and_default_output_namespace(self):
        first = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย",
                                "voice_project": "project-a"})
        second = CsvBatchRow(2, {"file_name": "001.wav", "thai_text": "ข้อความไทย",
                                 "voice_project": "project-b"})
        from csv_batch import new_mission_id
        self.assertNotEqual(new_mission_id([first]).split("-")[-1],
                            new_mission_id([second]).split("-")[-1])
        self.assertEqual(default_project_output_dir(self.PROJECT),
                         Path("output/studio/triangle-strategy").resolve())


if __name__ == "__main__":
    unittest.main()

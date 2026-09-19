from __future__ import annotations

import unittest

from narrator_continuity_fixture import TARGET_PHRASE, TARGET_WORD
from narrator_excitement_polish import BOUNDARY, build_excitement_plan
from narrator_length_sweep import build_length_sweep_plan


class NarratorExcitementPolishTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_excitement_plan()
        self.baseline = self.plan["baseline"]
        self.e1, self.e2 = self.plan["candidates"]

    def test_baseline_is_frozen_pause_b(self):
        self.assertTrue(all(self.baseline["audit_checks"].values()))
        self.assertEqual(self.baseline["spoken_text"].count(BOUNDARY), 1)
        self.assertEqual(self.baseline["seed"], 15016)
        self.assertEqual(self.baseline["speed"], 1.0)
        self.assertEqual(self.baseline["steps"], 32)

    def test_candidates_retain_identity_route_and_targets(self):
        for row in (self.e1, self.e2):
            self.assertEqual(row["canonical_text"], self.baseline["canonical_text"])
            self.assertEqual(row["seed"], self.baseline["seed"])
            self.assertEqual(row["voice"], self.baseline["voice"])
            self.assertEqual(row["instruction"], self.baseline["instruction"])
            self.assertEqual(row["steps"], self.baseline["steps"])
            self.assertEqual(row["application_input_count"], 1)
            self.assertEqual(row["application_semantic_chunks"], 0)
            self.assertIn(TARGET_WORD, row["spoken_text"])
            self.assertIn(TARGET_PHRASE, row["spoken_text"])
            self.assertEqual(row["spoken_text"].count(BOUNDARY), 1)
            self.assertTrue(row["thai_only_gate"])

    def test_each_candidate_changes_only_intended_variable(self):
        self.assertEqual(self.e1["speed"], self.baseline["speed"])
        self.assertNotEqual(self.e1["spoken_text"], self.baseline["spoken_text"])
        self.assertEqual(self.e2["spoken_text"], self.baseline["spoken_text"])
        self.assertEqual(self.e2["speed"], 1.03)
        self.assertEqual(self.e2["estimated_audio_tokens"], 490)

    def test_length_sweep_is_single_input_and_not_generated_plan(self):
        for winner in ("baseline", "E1", "E2"):
            plan = build_length_sweep_plan(winner)
            self.assertEqual(plan["status"], "READY_NOT_GENERATED")
            self.assertEqual([row["target_characters"] for row in plan["fixtures"]], [500, 750, 1000])
            if winner == "baseline":
                self.assertEqual([row["output"] for row in plan["fixtures"]], [
                    "length_497.wav", "length_746.wav", "length_995.wav",
                ])
                self.assertEqual(plan["voice"], "bright_female")
                self.assertEqual(plan["instruction"], "female, young adult, high pitch")
                self.assertEqual(plan["seed"], 15016)
                self.assertEqual(plan["speed"], 1.0)
                self.assertEqual(plan["steps"], 32)
            for row in plan["fixtures"]:
                self.assertEqual(row["application_input_count"], 1)
                self.assertTrue(row["application_single_inference"])
                self.assertEqual(row["application_semantic_chunks"], 0)
                self.assertLessEqual(abs(row["actual_characters"] - row["target_characters"]), 12)
                self.assertGreater(row["target_boundary_count"], 0)


if __name__ == "__main__":
    unittest.main()

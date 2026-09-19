from __future__ import annotations

import json
import unittest
from pathlib import Path


class BotwStyleCandidateTests(unittest.TestCase):
    def test_candidate_configuration_is_descriptive_and_complete(self):
        data = json.loads((Path(__file__).resolve().parent / "botw_style_voice_candidates.json").read_text(encoding="utf-8"))
        candidates = data["candidates"]
        self.assertEqual(set(candidates), {
            "mipha_style_A", "mipha_style_B", "great_deku_tree_style_A", "great_deku_tree_style_B",
            "great_deku_tree_style_C", "great_deku_tree_style_D", "great_deku_tree_style_E",
        })
        self.assertTrue(all({"instruct", "speed", "seed", "rationale"} <= set(row) for row in candidates.values()))
        self.assertTrue(all(0.25 <= row["speed"] <= 3.0 for row in candidates.values()))
        self.assertEqual(len({row["seed"] for row in candidates.values()}), len(candidates))
        self.assertTrue(all("reference" not in row and "embedding" not in row for row in candidates.values()))
        supported = {"male", "female", "elderly", "middle-aged", "young adult", "high pitch", "moderate pitch", "low pitch", "very low pitch"}
        for row in candidates.values():
            self.assertTrue(set(row["instruct"].split(", ")) <= supported)

    def test_mipha_c_is_recorded_as_human_approved_without_touching_engine_registry(self):
        data = json.loads((Path(__file__).resolve().parent / "botw_style_voice_candidates.json").read_text(encoding="utf-8"))
        mipha_c = data["mission_21"]["mipha_style_C"]
        self.assertTrue(mipha_c["human_approved"])
        self.assertIn("not an approved Engine v1", mipha_c["approval_scope"])


if __name__ == "__main__":
    unittest.main()

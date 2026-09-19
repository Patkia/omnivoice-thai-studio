"""No-model regression tests for the focused seed and pause search."""
from __future__ import annotations

import unittest

from narrator_continuity_fixture import CANONICAL_TEXT, TARGET_PHRASE, TARGET_WORD
from narrator_single_inference_tuning import (
    BOUNDARY,
    MODEL_CHUNK_THRESHOLD_TOKENS,
    PAUSE_CANDIDATES,
    SEED_CANDIDATES,
    build_tuning_plan,
    pause_representation,
)


class NarratorSingleInferenceTuningTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_tuning_plan()

    def test_seed_search_is_small_symmetric_and_changes_only_seed(self):
        seeds = [seed for _name, seed, _reason in SEED_CANDIDATES]
        self.assertEqual(seeds, [15014, 15015, 15017, 15018])
        rows = [row for row in self.plan["candidates"] if row["kind"] == "seed_search"]
        self.assertEqual(len(rows), 4)
        invariant = {key: rows[0][key] for key in ("canonical_text", "spoken_text", "voice", "instruction", "speed", "steps")}
        for row in rows:
            self.assertEqual({key: row[key] for key in invariant}, invariant)
            self.assertTrue(row["single_inference_expected"])
            self.assertLess(row["estimated_audio_tokens"], MODEL_CHUNK_THRESHOLD_TOKENS)

    def test_pause_candidates_change_only_one_boundary_mark(self):
        self.assertEqual(CANONICAL_TEXT.count(BOUNDARY), 1)
        rows = [row for row in self.plan["candidates"] if row["kind"] == "pause_poc"]
        self.assertEqual(len(rows), 2)
        for row, (_name, seed, mark, _reason) in zip(rows, PAUSE_CANDIDATES):
            represented = pause_representation(mark)
            self.assertEqual(row["canonical_text"], CANONICAL_TEXT)
            self.assertEqual(row["spoken_text"], represented)
            self.assertEqual(len(represented), len(CANONICAL_TEXT) + 1)
            self.assertEqual(seed, 15016)
            self.assertTrue(row["thai_only_gate"])
            self.assertEqual(row["normalization_transformations"], [])
            self.assertEqual(row["pronunciation_substitutions"], [])
            self.assertIn(TARGET_WORD, represented)
            self.assertIn(TARGET_PHRASE, represented)
            self.assertTrue(row["single_inference_expected"])

    def test_plan_is_deterministic(self):
        self.assertEqual(self.plan, build_tuning_plan())


if __name__ == "__main__":
    unittest.main()

"""No-model regression tests for the narrator continuity fixture."""
from __future__ import annotations

import unittest

from narrator_continuity_fixture import (
    CANONICAL_TEXT,
    EXPECTED_INSTRUCTION,
    EXPECTED_SEED,
    EXPECTED_SPEED,
    TARGET_PHRASE,
    TARGET_WORD,
    build_forensic_plan,
)


class NarratorContinuityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_forensic_plan()

    def test_reconstruction_is_exact_and_deterministic(self):
        first = self.plan
        second = build_forensic_plan()
        self.assertEqual("".join(row["text"] for row in first["chunks"]), CANONICAL_TEXT)
        self.assertEqual(first["chunks"], second["chunks"])

    def test_target_word_is_not_split_or_preprocessed(self):
        rows = [row for row in self.plan["chunks"] if row["contains_target_word"]]
        self.assertEqual(len(rows), 1)
        self.assertIn(TARGET_WORD, rows[0]["text"])
        self.assertEqual(self.plan["normalized_text"], CANONICAL_TEXT)
        self.assertEqual(self.plan["spoken_text"], CANONICAL_TEXT)
        self.assertEqual(self.plan["normalization_transformations"], [])
        self.assertEqual(self.plan["pronunciation_substitutions"], [])
        span = self.plan["target_word_span"]
        boundaries = {row["end_char_exclusive_0"] for row in self.plan["chunks"][:-1]}
        self.assertFalse(any(span["start_char_0"] < boundary < span["end_char_exclusive_0"] for boundary in boundaries))

    def test_target_phrase_is_preserved_in_one_generation_unit(self):
        rows = [row for row in self.plan["chunks"] if row["contains_target_phrase"]]
        self.assertEqual(len(rows), 1)
        self.assertIn(TARGET_PHRASE, rows[0]["text"])
        self.assertNotEqual(rows[0]["text"].strip(), TARGET_PHRASE)

    def test_effective_profile_is_frozen(self):
        self.assertEqual(self.plan["voice_alias"], "bright_female")
        self.assertEqual(self.plan["instruction"], EXPECTED_INSTRUCTION)
        self.assertEqual(self.plan["effective_seed"], EXPECTED_SEED)
        self.assertEqual(self.plan["effective_speed"], EXPECTED_SPEED)
        self.assertTrue(self.plan["thai_only_gate"])


if __name__ == "__main__":
    unittest.main()

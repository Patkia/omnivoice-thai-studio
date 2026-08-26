import json
import unittest
from pathlib import Path

from run_engine_candidate import build_cases
from thai_speech_normalizer import normalize_text


class EngineCandidateTests(unittest.TestCase):
    def test_candidate_matrix_and_gate(self):
        engine = json.loads(Path("engine_config.json").read_text(encoding="utf-8"))
        profiles = json.loads(Path("voice_profiles.json").read_text(encoding="utf-8"))
        tests = json.loads(Path("engine_candidate_test.json").read_text(encoding="utf-8"))
        cases = build_cases(engine, profiles, tests)
        self.assertEqual(len(cases), 15)
        self.assertEqual({c["speed"] for c in cases if c["profile_id"] == "narrator" and c["kind"] == "voice_diversity"}, {0.94, 1.06})
        self.assertTrue(all(normalize_text(c["source_text"]).thai_only_gate_passed for c in cases))

    def test_engine_keeps_approved_dictionary_path(self):
        engine = json.loads(Path("engine_config.json").read_text(encoding="utf-8"))
        self.assertEqual(engine["normalization"]["pronunciation_dictionary_path"], "pronunciation_dictionary.json")


if __name__ == "__main__":
    unittest.main()

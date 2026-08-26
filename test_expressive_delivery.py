import json
import unittest
from pathlib import Path

from thai_speech_normalizer import normalize_text


class ExpressiveDeliveryTests(unittest.TestCase):
    def test_controlled_candidate_set(self):
        config = json.loads(Path("expressive_delivery_candidates.json").read_text(encoding="utf-8"))
        candidates = config["candidates"]
        self.assertFalse(config["native_emotion_control_available"])
        self.assertEqual(len(candidates), 12)
        self.assertEqual({x["source_line_id"] for x in candidates}, {"001", "002", "004", "007"})
        self.assertTrue(all(normalize_text(x["input_text"]).thai_only_gate_passed for x in candidates))
        self.assertTrue(all(1.06 <= x["speed"] <= 1.14 for x in candidates))


if __name__ == "__main__":
    unittest.main()

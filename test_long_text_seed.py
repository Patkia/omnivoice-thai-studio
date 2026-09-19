"""No-model regression tests for profile-seed long-text continuity."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import tts
from long_text_batch import generate, resolve_continuity_seed
from novel_chunker import ChunkResult
from studio_engine_adapter import generation_cache_keys
from studio import GenerateWorker


class FakeSession:
    model_load_count = 1


class FakeAdapter:
    def __init__(self, cache_hits=()):
        self.session = FakeSession()
        self.calls = []
        self.cache_hits = set(cache_hits)

    def generate(self, text, alias, speed, steps, output, force, *, seed=None, single_input=False):
        self.calls.append({"text": text, "alias": alias, "output": output, "seed": seed,
                           "single_input": single_input})
        return {"cache_hit": len(self.calls) in self.cache_hits, "inference_seconds": 0.25}


def chunks():
    return [
        ChunkResult(1, "หนึ่ง ", 5, "sentence", 320, 1, False),
        ChunkResult(2, "สอง", 3, "sentence", 320, 1, False),
    ]


class LongTextSeedTests(unittest.TestCase):
    def _generate(self, adapter, *, alias="narrator", cancelled=lambda: False, progress=lambda *_: None):
        with patch("long_text_batch.semantic_chunks", return_value=chunks()), \
             patch("long_text_batch.Path.mkdir"), \
             patch("long_text_batch.remerge_cached", return_value=1.0) as remerge:
            result = generate(adapter, "ข้อความยาว", alias, 0.94, 32, Path("out.wav"),
                              cancelled=cancelled, progress=progress)
        return result, remerge

    def test_long_text_does_not_override_profile_seed(self):
        adapter = FakeAdapter()
        result, _ = self._generate(adapter)
        self.assertEqual([call["seed"] for call in adapter.calls], [None, None])
        self.assertIsNone(result["continuity_seed"])

    def test_profile_seed_is_left_for_adapter_to_resolve(self):
        adapter = FakeAdapter()
        result, _ = self._generate(adapter, alias="young_male")
        self.assertEqual([call["seed"] for call in adapter.calls], [None, None])
        self.assertIsNone(result["continuity_seed"])
        self.assertIsNone(resolve_continuity_seed("narrator"))
        self.assertIsNone(resolve_continuity_seed("young_male"))

    def test_cache_progress_and_order_regression(self):
        adapter, events = FakeAdapter(cache_hits={2}), []
        result, remerge = self._generate(adapter, progress=lambda *event: events.append(event))
        self.assertEqual([call["text"] for call in adapter.calls], ["หนึ่ง ", "สอง"])
        self.assertEqual(events, [(1, 2, "GENERATING"), (1, 2, "GENERATED"),
                                  (2, 2, "GENERATING"), (2, 2, "CACHED")])
        self.assertEqual(result["cache_hits"], 1)
        self.assertEqual(result["model_load_count"], 1)
        remerge.assert_called_once()

    def test_cancel_stops_before_the_next_chunk_and_never_merges(self):
        adapter = FakeAdapter()
        result, remerge = self._generate(adapter, cancelled=lambda: len(adapter.calls) >= 1)
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(adapter.calls), 1)
        remerge.assert_not_called()

    def test_seeded_cache_keys_are_distinct_and_none_is_backward_compatible(self):
        payload = {"text": "ข้อความ", "steps": 32}
        no_seed, legacy_none = generation_cache_keys(payload, None)
        seed_a, _ = generation_cache_keys(payload, 15015)
        seed_b, _ = generation_cache_keys(payload, 15016)
        self.assertEqual(no_seed, tts.cache_key(payload))
        self.assertEqual(legacy_none, tts.cache_key({**payload, "seed": None}))
        self.assertNotEqual(seed_a, seed_b)
        self.assertNotIn(seed_a, {no_seed, legacy_none})

    def test_short_studio_path_leaves_profile_seed_resolution_to_adapter(self):
        adapter = FakeAdapter()
        worker = GenerateWorker(adapter, "สั้น", "narrator", 0.94, 32, Path("short.wav"), False)
        with patch("studio_generation.generate_long") as long_path:
            worker.run()
        long_path.assert_not_called()
        self.assertEqual(len(adapter.calls), 1)
        self.assertIsNone(adapter.calls[0]["seed"])
        self.assertTrue(adapter.calls[0]["single_input"])


if __name__ == "__main__":
    unittest.main()

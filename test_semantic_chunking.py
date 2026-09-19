import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
from long_text_batch import merge, remerge_cached
from build_semantic_chunk_preview import FIXTURE
from novel_chunker import (ACTION_CHAIN_CLAUSE_PHRASES, ACTION_CHAIN_NEXT_PHRASES, CONTINUATION_PAUSE_MS, DIALOGUE_PAUSE_MS, EMOTIONAL_BEAT_PAUSE_MS, LEADING_CONNECTIVE_PHRASES, PARAGRAPH_PAUSE_MS, SENTENCE_PAUSE_MS, semantic_chunks)

def wav_handle(rate=1000):
    handle = MagicMock(); opened = handle.__enter__.return_value
    opened.getframerate.return_value = rate; opened.getnchannels.return_value = 1; opened.getsampwidth.return_value = 2
    return handle

class SemanticChunkingTests(unittest.TestCase):
    def test_leading_connectives_are_not_orphaned_at_chunk_end(self):
        for phrase in ("ทันใดนั้น", "หลังจากนั้น", "อย่างไรก็ตาม"):
            text = "คำเกริ่น " * 14 + f"{phrase} ฉันก็จำได้ว่าต้องไปต่อ และเดินต่อไปอีกเล็กน้อย"
            rows = semantic_chunks(text, 1, 120)
            self.assertEqual("".join(row.text for row in rows), text)
            self.assertFalse(any(row.text.rstrip().endswith(phrase) for row in rows[:-1]))
        self.assertIn("ทันใดนั้น", LEADING_CONNECTIVE_PHRASES)

    def test_final_concluding_phrase_is_a_separate_final_unit(self):
        text = "และนึกถึงคนที่เก็บกระดิ่งนั้นไว้ หลังจากกลับมาจากทัศนศึกษาคราวนั้น เราก็ตกหลุมรักกันอย่างลึกซึ้ง"
        rows = semantic_chunks(text, 1, 120)
        self.assertEqual([row.text for row in rows], ["และนึกถึงคนที่เก็บกระดิ่งนั้นไว้ ", "หลังจากกลับมาจากทัศนศึกษาคราวนั้น เราก็ตกหลุมรักกันอย่างลึกซึ้ง"])
        self.assertEqual(rows[-1].boundary_type, "sentence")
        self.assertEqual(rows[-1].pause_after_ms, SENTENCE_PAUSE_MS)

    def test_deterministic_reconstruction_and_hard_max(self):
        text = "ย่อหน้าแรกยาวพอสมควร, แต่ยังต่อเนื่องกัน.\nย่อหน้าสอง “คำพูดสั้น” แล้วจบ!"
        one, two = semantic_chunks(text, 100, 120), semantic_chunks(text, 100, 120)
        self.assertEqual(one, two); self.assertEqual("".join(x.text for x in one), text); self.assertTrue(all(x.char_count <= 120 for x in one))
    def test_paragraph_sentence_dialogue_and_emotional_beat(self):
        rows = semantic_chunks("จบประโยค.\n“เอ้า นี่” ฉันว่า “ของขวัญ”\nกลายเป็นว่ามันคือความรักนั่นเอง\nต่อไป", 1, 30)
        self.assertIn("paragraph", [x.boundary_type for x in rows]); self.assertEqual(semantic_chunks("one. continuation", 1, 5)[0].boundary_type, "sentence")
        self.assertTrue(any(x.dialogue and "“เอ้า นี่”" in x.text for x in rows))
        beat = next(x for x in rows if "กลายเป็นว่า" in x.text)
        self.assertEqual(beat.boundary_type, "emotional_beat"); self.assertEqual(beat.pause_after_ms, EMOTIONAL_BEAT_PAUSE_MS)
    def test_pause_constants_and_classification(self):
        self.assertEqual(semantic_chunks("one, continuation", 1, 5)[0].pause_after_ms, CONTINUATION_PAUSE_MS)
        self.assertEqual(semantic_chunks("one. continuation", 1, 5)[0].pause_after_ms, SENTENCE_PAUSE_MS)
        thai_end = semantic_chunks("oneฯ continuation", 1, 4)[0]
        self.assertEqual(thai_end.boundary_type, "sentence")
        self.assertEqual(thai_end.pause_after_ms, 320)
        self.assertEqual(semantic_chunks("“hi” continuation", 1, 5)[0].pause_after_ms, DIALOGUE_PAUSE_MS)
        self.assertEqual(semantic_chunks("one\ncontinuation", 1, 4)[0].pause_after_ms, PARAGRAPH_PAUSE_MS)
    def test_overlong_dialogue_uses_phrase_boundaries_not_hard_cut(self):
        text = "“one two three four five six seven eight nine ten”"
        rows = semantic_chunks(text, 1, 12)
        self.assertEqual("".join(row.text for row in rows), text)
        self.assertTrue(all(row.dialogue for row in rows)); self.assertNotIn("hard_cut", [row.boundary_type for row in rows])
    def test_dynamic_merge_no_trailing_silence_and_cached_remerge(self):
        paths = [Path('a.wav'), Path('b.wav')]; read = [(np.ones((10, 1), dtype='float32'), 1000), (np.ones((20, 1), dtype='float32') * .5, 1000)]
        with patch('long_text_batch.wave.open', side_effect=[wav_handle(), wav_handle()]), patch('long_text_batch.sf.read', side_effect=read), patch('long_text_batch.sf.write') as write:
            merge(paths, Path('merged.wav'), pause_after_ms=[7, 999])
        audio = write.call_args.args[1]; self.assertEqual(len(audio), 37); self.assertAlmostEqual(audio[-1, 0], .5, places=3)
        rows = semantic_chunks("one. two", 1, 4)
        with patch('long_text_batch.wave.open', side_effect=[wav_handle(), wav_handle()]), patch('long_text_batch.sf.read', side_effect=read), patch('long_text_batch.sf.write') as write:
            remerge_cached(paths, Path('cached.wav'), rows)
        self.assertEqual(len(write.call_args.args[1]), 10 + 20 + int(1000 * rows[0].pause_after_ms / 1000))

    def test_action_chain_rebalances_before_the_owning_clause(self):
        rows = semantic_chunks(FIXTURE, 100, 120)
        focus = next(i for i, row in enumerate(rows) if row.text.startswith("เขาหัวเราะ"))
        first, second = rows[focus], rows[focus + 1]
        self.assertTrue(first.text.rstrip().endswith("สร้างสรรค์นัก"))
        self.assertTrue(second.text.lstrip().startswith("แต่เขาก็หยิบมันออกจากมือของฉัน แล้วก็ห่อ"))
        self.assertFalse(any(row.text.lstrip().startswith("แล้วก็ห่อ") for row in rows))
        self.assertTrue(all(row.char_count <= 120 for row in rows))
        self.assertEqual("".join(row.text for row in rows), FIXTURE)
        self.assertEqual(rows, semantic_chunks(FIXTURE, 100, 120))
        self.assertIn("แล้วก็", ACTION_CHAIN_NEXT_PHRASES)
        self.assertIn("แต่เขาก็", ACTION_CHAIN_CLAUSE_PHRASES)

if __name__ == "__main__": unittest.main()

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
from long_text_batch import HARD_MAX, is_long, merge
from novel_chunker import chunk_text

def wav_handle(rate=1000):
    handle = MagicMock(); opened = handle.__enter__.return_value
    opened.getframerate.return_value = rate; opened.getnchannels.return_value = 1; opened.getsampwidth.return_value = 2
    return handle

class LongTextTests(unittest.TestCase):
    def test_threshold_and_order(self):
        self.assertFalse(is_long('ก' * 500)); self.assertTrue(is_long('ก' * 501))
        text = 'ก' * 241; chunks = chunk_text(text, 100, HARD_MAX)
        self.assertTrue(all(len(item) <= 120 for item in chunks)); self.assertEqual(''.join(chunks), text)
    def test_merge_order_no_trailing_and_mismatch(self):
        paths = [Path('a.wav'), Path('b.wav')]
        with patch('long_text_batch.wave.open', side_effect=[wav_handle(), wav_handle()]), patch('long_text_batch.sf.read', side_effect=[(np.ones((10, 1), dtype='float32'), 1000), (np.ones((20, 1), dtype='float32') * .5, 1000)]), patch('long_text_batch.sf.write') as write:
            duration = merge(paths, Path('merged.wav'), 10)
        data = write.call_args.args[1]
        self.assertEqual(len(data), 40); self.assertAlmostEqual(data[-1, 0], .5, places=3); self.assertEqual(duration, .04)
        with patch('long_text_batch.wave.open', side_effect=[wav_handle(), wav_handle(800)]), self.assertRaises(RuntimeError):
            merge(paths, Path('merged.wav'))

if __name__ == '__main__': unittest.main()

import csv
from pathlib import Path
from studio_engine_adapter import StudioEngineAdapter

OUT = Path(r'C:\Users\Pat\Workshop\triangle-strategy-thai-voice\work\chapter2_voice_mapping\chapter2_thai_voice_candidates')
with (OUT / 'chapter2_thai_voice_candidates.csv').open('r', encoding='utf-8-sig', newline='') as f:
    row = next(r for r in csv.DictReader(f) if r['speaker_code'] == 'LGN' and r['candidate'] == 'A')
text = row['thai_text'].rstrip('.…').strip()
adapter = StudioEngineAdapter()
for name, speed, seed in [('LGN_THAI_VERY_OLD_FIX1', 0.80, 33325), ('LGN_THAI_VERY_OLD_FIX2', 0.82, 33326)]:
    output = OUT / (name + '.wav')
    result = adapter.generate(text, 'narrator', speed, 32, output, False, seed=seed, instruct_override='male, elderly, very low pitch', generation_mode='voice_design')
    print('DONE', name, 'path=', output)

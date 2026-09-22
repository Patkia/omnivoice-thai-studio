from pathlib import Path
from studio_engine_adapter import StudioEngineAdapter

OUT = Path(r"C:\Users\Pat\Workshop\triangle-strategy-thai-voice\work\chapter2_voice_mapping\chapter2_thai_voice_candidates\LGN_A_tests")
OUT.mkdir(parents=True, exist_ok=True)

TESTS = [
    "วันนี้อากาศแจ่มใส เหมาะกับการออกไปเดินเล่นนอกเมืองเสียจริง",
    "เรื่องนี้ไม่ต้องรีบร้อน เราค่อยคิดกันให้รอบคอบอีกครั้งก็ได้",
    "เจ้าช่วยนำเอกสารเหล่านี้ไปส่งที่ห้องประชุมก่อนเที่ยงด้วยนะ",
    "ถ้าทุกคนพร้อมแล้ว พรุ่งนี้เราจะออกเดินทางตั้งแต่เช้าตรู่",
    "ขอบใจมากที่ช่วยดูแลทุกอย่างแทนข้า ช่วงนี้เจ้าคงเหนื่อยไม่น้อย",
]

adapter = StudioEngineAdapter()
for i, text in enumerate(TESTS, 1):
    output = OUT / f"LGN_A_TEST_{i:02d}.wav"
    result = adapter.generate(
        text,
        "narrator",
        0.90,
        32,
        output,
        force=False,
        seed=33301,
        instruct_override="male, elderly, moderate pitch",
        generation_mode="voice_design",
    )
    print(f"DONE {i} cache={bool(result.get('cache_hit'))} sec={float(result.get('inference_seconds', 0.0)):.3f} path={output}")

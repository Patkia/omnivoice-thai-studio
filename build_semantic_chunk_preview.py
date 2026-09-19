"""Create Mission 12 text/JSON review artifacts; this script never loads or calls TTS."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from novel_chunker import semantic_chunks

# Kept local and explicit so the review fixture is reproducible without external input.
FIXTURE = """ไม่ว่าจะไปที่ไหน ฮิโตชิมักจะมีกระดิ่งอันเล็กซึ่งอยู่ในกล่องที่เขาใช้เก็บบัตรโดยสารรถประจำทางติดตัวไปด้วยเสมอ ถึงแม้มันจะเป็นเพียงแค่สิ่งของเล็กๆ ที่ฉันให้เขาก่อนที่เราจะรักกัน แต่มันก็ถูกลิขิตมาให้อยู่เคียงข้างเขาจนวาระสุดท้าย
เราอยู่คนละห้องกันก็จริง แต่ก็มาเจอกันได้เพราะต่างก็เป็นตัวแทนห้องในคณะกรรมการจัดทัศนศึกษาสำหรับนักเรียนชั้นปีสอง และเนื่องจากเราต้องไปกันคนละเส้นทาง เวลาเดียวที่ได้อยู่ด้วยกันก็คือตอนอยู่บนรถไฟด่วนเท่านั้น เมื่อมาถึงสถานีปลายทาง บนชานชาลา เราแกล้งจับมืออำลาเสมือนว่าเสียใจหนักหนาที่ต้องจากกัน ทันใดนั้น ฉันก็จำได้ว่าฉันเก็บกระดิ่งอันเล็กที่หล่นจากปลอกคอแมวไว้ในกระเป๋าชุดนักเรียน
“เอ้า นี่” ฉันว่า “เป็นของขวัญก่อนจาก” แล้วก็ยื่นกระดิ่งให้เขา
“อะไรกันนี่” เขาหัวเราะ และถึงแม้ว่ามันจะไม่ใช่ของขวัญที่สร้างสรรค์นัก แต่เขาก็หยิบมันออกจากมือของฉัน แล้วก็ห่อไว้ในผ้าเช็ดหน้าของเขาอย่างระมัดระวัง ราวกับว่ามันเป็นสิ่งที่แสนมีค่า กิริยาเช่นนั้นทำให้ฉันรู้สึกแปลกใจเป็นที่สุด เพราะมันไม่ใช่เรื่องปรกติที่เด็กผู้ชายในวัยเดียวกับเขากระทำกันนัก
กลายเป็นว่ามันคือความรักนั่นเอง
ไม่ว่าเขาจะทำอย่างนั้นเพราะว่ากระดิ่งเป็นของขวัญจากฉัน หรือเป็นเพราะเขาถูกเลี้ยงดูมาไม่ให้ทิ้งขว้างของขวัญก็ตาม การกระทำของเขาทำให้ฉันทึ่งและรู้สึกประทับใจในตัวเขาขึ้นมา
เหมือนกับมีกระแสไฟฟ้าวิ่งระหว่างหัวใจของเราทั้งคู่ และสายไฟก็คือเสียงกระดิ่ง ตลอดช่วงเวลาที่เราอยู่ห่างกันในการเดินทางครั้งนั้น ต่างคนต่างเฝ้าคิดถึงแต่กระดิ่งอันเล็ก เมื่อใดก็ตามที่เขาได้ยินเสียงกระดิ่ง เขาก็จะนึกถึงฉันและเวลาที่เราได้อยู่ด้วยกัน ส่วนฉันเองก็ใช้เวลาในการเดินทางครั้งนั้น จินตนาการว่าได้ยินเสียงกระดิ่งดังข้ามท้องฟ้ากว้างมาหา และนึกถึงคนที่เก็บกระดิ่งนั้นไว้ หลังจากกลับมาจากทัศนศึกษาคราวนั้น เราก็ตกหลุมรักกันอย่างลึกซึ้ง"""

def main():
    rows = semantic_chunks(FIXTURE, target=100, hard_max=120)
    payload = {"fixture_characters": len(FIXTURE), "chunk_count": len(rows),
        "boundary_counts": dict(Counter(row.boundary_type for row in rows)),
        "chunks": [row.to_dict() for row in rows]}
    output = Path("output"); output.mkdir(exist_ok=True)
    (output / "semantic_chunk_preview.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"Total chunks: {len(rows)}", f"Total characters: {len(FIXTURE)}", ""]
    for row in rows:
        lines.extend([f"[{row.index:02}] boundary={row.boundary_type} pause={row.pause_after_ms}ms chars={row.char_count} paragraph={row.paragraph_index} dialogue={str(row.dialogue).lower()}", row.text, ""])
    (output / "semantic_chunk_preview.txt").write_text("\n".join(lines), encoding="utf-8")

if __name__ == "__main__": main()

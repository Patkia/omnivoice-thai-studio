# OmniVoice Thai POC

POC นี้สร้างเสียงภาษาไทยด้วยโมเดล pretrained `hotdogs/omnivoice-thai` บนเครื่อง local เท่านั้น ไม่มีการ train, fine-tune, ใช้ไฟล์เกม หรือ clone เสียงบุคคลจริง

## เริ่มใช้งาน

```powershell
.\.venv\Scripts\python.exe generate_tts.py --text "ข้อความภาษาไทย" --output output\sample.wav
```

ค่ามาตรฐานใช้ `male, middle-aged, low pitch` ซึ่งเป็นชุด voice-design tags ที่ runtime รองรับสำหรับผู้ชายวัยประมาณ 30–40 ปี โทนลึกเล็กน้อย. ความนิ่งและจังหวะเล่าเรื่องควบคุมได้ทางอ้อมด้วย `--speed`.

```powershell
.\.venv\Scripts\python.exe generate_tts.py `
  --text "ข้อความภาษาไทย" `
  --output output\narrator_01.wav `
  --voice "male, middle-aged, low pitch" `
  --speed 0.94 --steps 32
```

ตัวเลือก `--voice`, `--speaker` และ `--style` รับ voice-design tags ของ OmniVoice เช่น `male`, `middle-aged`, `young adult`, `low pitch`, `very low pitch`, `moderate pitch` และ `whisper`. คำที่ runtime ไม่รองรับ (เช่น `calm`/`storytelling`) จะถูกข้ามและบันทึก warning แทนการทำให้งานล้ม. `--speed` กำหนดอัตราการพูด และ `--steps` ควบคุม diffusion quality/เวลา. สคริปต์ normalize peak เป็น -1 dBFS และเขียน WAV PCM 16-bit 24 kHz.

## Cache และรายงาน

หากข้อความ, โมเดล, revision, voice/style และ generation parameters เหมือนเดิม พร้อมมีไฟล์ output อยู่ สคริปต์จะข้ามงานและแสดง `CACHE HIT`. ใช้ `--force` เมื่อต้องการสร้างใหม่

`output/report.json` บันทึก model, revision, instruction, parameters, sample rate, duration, เวลา generate, device และ warnings/errors ของแต่ละงาน

`--reference-audio` ถูกสงวนไว้ แต่ตั้งใจปิดใน POC นี้เพื่อไม่ให้เกิด voice cloning. POC นี้ใช้ voice design เท่านั้น.

## ข้อสังเกต

รุ่น Thai ถูก fine-tune จาก OmniVoice ด้วยข้อมูลจำกัดและผู้พูด 2 คน ดังนั้นคุณภาพ/ความนิ่งของ voice design ต้องประเมินจากไฟล์จริงก่อนนำไปใช้ในงานเกมจำนวนมาก. ถ้า CUDA ใช้งานไม่ได้ ระบบยังทำงานบน CPU ได้ แต่ช้ากว่าอย่างมาก.

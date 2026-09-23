# OmniVoice Thai Studio

`OmniVoice Thai Studio` เป็น Windows desktop frontend และ tooling สำหรับงาน Thai TTS บนโมเดล `hotdogs/omnivoice-thai` โดยเน้น workflow แบบ local: พิมพ์ข้อความ, สร้าง/เล่น WAV, CSV batch, normalization, cache, checkpoint/resume และ project-aware voice configuration.

![OmniVoice Thai Studio](docs/images/omnivoice-studio.png)

## ความสามารถหลัก

- Native desktop UI ด้วย PySide6
- Thai text normalization และ Thai-only validation ก่อนส่งเข้าโมเดล
- Voice profiles, speed, fixed seed และ generation parameters
- Lazy persistent model session ใน Studio เพื่อ reuse model ระหว่าง generation
- CSV Batch พร้อม select rows, checkpoint/resume และ watchdog สำหรับงานยาว
- Project-aware `voice_target` mapping
- รองรับ `reference_first` / reference conditioning เมื่อผู้ใช้มี reference audio ที่ได้รับสิทธิ์ใช้งานเอง
- CLI (`tts.py`) และ desktop Studio ใช้ pipeline หลักร่วมกัน

## Public repository policy

Repository สาธารณะตั้งใจเก็บ **source code, tests, configuration examples และ provenance metadata** เท่านั้น โดยไม่แจกไฟล์ต่อไปนี้:

- generated WAV / runtime output
- local voice-reference audio packs
- candidate/audition audio
- game dialogue CSV จริง
- generated chapter audio หรือ game assets

ไฟล์เหล่านี้ถูกเก็บ local และถูก ignore ด้วย `.gitignore`. ตัวอย่าง CSV ที่ไม่มีเนื้อหาเกมอยู่ที่ `imports/example_batch.csv`.

## เริ่มใช้งานบน Windows

สร้าง/เปิด virtual environment และติดตั้ง dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

เปิด Studio:

```powershell
python studio.py
```

หรือใช้ launcher:

```text
Start OmniVoice Studio.bat
```

โมเดลจะถูกโหลดเมื่อจำเป็น ไม่ได้โหลดทันทีตอนเปิดหน้าต่าง Studio.

## CLI

ดู voice aliases:

```powershell
python tts.py --list-voices
```

สร้างเสียง:

```powershell
python tts.py --text "คืนนี้ฝนตกหนักกว่าทุกคืน" --voice bright_female --output output\sample.wav
```

ตรวจ normalization โดยไม่สร้างเสียง:

```powershell
python tts.py --text "เวลา 02:17" --voice bright_female --dry-run --show-normalized
```

ใช้ `--force` เมื่อต้องการสร้างใหม่แม้ cache key เดิมจะตรงกัน.

## CSV Batch

ตัวอย่าง schema อยู่ที่:

```text
imports/example_batch.csv
```

Studio สามารถ import CSV, เลือกเฉพาะบาง row, กำหนด output directory และสร้าง batch job ได้โดยตรง. สำหรับ runner แบบ command line:

```powershell
.\.venv\Scripts\python.exe tts_batch_runner.py run --job tts_batch_job.example.json --line-timeout 600
```

ตรวจสถานะ mission:

```powershell
.\.venv\Scripts\python.exe tts_batch_runner.py status --mission-id example-13-lines
```

## Project-aware voices และ reference conditioning

โครงสร้าง project configuration อยู่ใต้ `projects/`. Project สามารถ map `voice_target` ไปยัง profile, speed, steps, seed และ reference-conditioning configuration ได้.

Public repository **ไม่รวม reference audio**. ถ้าจะใช้ `reference_first` ให้เตรียมไฟล์เสียงของคุณเองที่มีสิทธิ์ใช้งานและวางตาม path ที่กำหนดใน project config หรือปรับ config ให้ชี้ไปยัง asset ของคุณเอง.

## Pipeline

โดยสรุป generation path คือ:

```text
input text
→ Thai speech normalization
→ pronunciation dictionary
→ Thai-only gate
→ voice/project configuration
→ OmniVoice Thai
→ output post-processing
→ WAV
```

Studio ใช้ cache ก่อนโหลดโมเดลเมื่อทำได้ และ generation ทำใน worker thread เพื่อไม่ให้ UI ค้าง.

## ข้อจำกัด

- CPU inference ช้ากว่า CUDA อย่างมาก
- คำยืม/ชื่อเฉพาะบางคำอาจต้องเพิ่ม pronunciation rule
- คุณภาพ reference conditioning ขึ้นอยู่กับความสะอาดและความเหมาะสมของ reference audio
- ผู้ใช้ต้องตรวจสิทธิ์/license ของ reference audio และ dataset ที่นำมาใช้เอง

## Third-party licenses

โมเดลและ dataset ภายนอกมี license ของเจ้าของแต่ละแหล่ง ดูรายละเอียดและ attribution notes ที่ [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

โดยเฉพาะ public repo นี้ไม่ redistribute model weights, generated game audio หรือ local reference clips.

## Development

รันชุดทดสอบที่เกี่ยวข้องด้วย Python `unittest` ตามไฟล์ `test_*.py`. โปรเจกต์มี tests ครอบคลุม Studio startup, CSV batch, runtime adapter, normalization, cache และ reference-first configuration.

## License`r`n`r`nSource code ใน repository นี้เผยแพร่ภายใต้ [MIT License](LICENSE). Third-party models, datasets และ assets ไม่ได้อยู่ภายใต้ MIT โดยอัตโนมัติ; ให้ยึด license ของแต่ละแหล่งตาม [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

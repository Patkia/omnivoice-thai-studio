# OmniVoice Studio — Second PC Setup

เอกสารนี้ใช้สำหรับเตรียมเครื่องใหม่จาก repository หลัง clone โดยไม่รวม virtual environment, generated output หรือ model weights ใน repository

## 1. Clone และเข้า project

```powershell
git clone <PRIVATE_REPO_URL>
Set-Location .\omnivoice-thai-poc
```

`<PRIVATE_REPO_URL>` เป็น placeholder ให้แทนด้วย private repository URL จริงภายหลัง ผู้ใช้เป็นผู้สร้าง remote และ push เอง

## 2. ตรวจ Python

แนะนำ Python 3.11 หรือ 3.12 สำหรับความเข้ากันได้ของ PyTorch/OmniVoice บนเครื่องใหม่ โปรเจกต์ประกาศ runtime ขั้นต่ำ `>=3.10` และเครื่องเดิมใช้ Python 3.13

```powershell
python --version
```

## 3. สร้าง virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

## 4. ติดตั้ง dependencies

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` ระบุ direct runtime dependencies เท่านั้น รวมถึง `omnivoice`, `numpy`, `soundfile`, `PySide6`, `torch` และ `torchaudio` โปรดเลือก PyTorch wheel ที่ตรงกับ CPU/CUDA ของเครื่องใหม่ตามเอกสาร PyTorch ก่อนติดตั้ง หาก pip default เลือก wheel ไม่ตรง platform

## 5. Model และ first run

Engine v1 ใช้:

```text
model: hotdogs/omnivoice-thai
revision: 252d5f2815a5d7300c7676422bee69141c7756de
```

Model weights ไม่ถูก commit ใน repository โดย runtime จะใช้/download model cache ในตำแหน่งของเครื่องใหม่เมื่อทำ first inference ตามสภาพแวดล้อมที่ติดตั้งไว้ โปรดเตรียม network และ disk space ก่อนใช้งานจริง การตรวจ health check จะไม่โหลด model และไม่ทำ inference

## 6. ตรวจ canonical assets

```powershell
python tools\check_installation.py
```

Health check ต้องยืนยัน map, CSV และ SHA256 ของ reference นี้:

```text
assets/triangle-strategy/approved_voice_references/runtime_24k/serenoa_male14.wav
SHA256: 0b54c5e1bd6746e9845080c02c4282664a944683c760285204cbf637e4ccfa6a
```

ห้ามแทนที่ reference ด้วยไฟล์ที่ไม่ตรง hash

## 7. รัน lightweight regression

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -q
```

การทดสอบนี้ไม่ควรสร้าง model inference ใหม่ใน unit-test path หากต้องการทดสอบเสียงจริง ให้ทำเป็นขั้นตอนแยกและตรวจ cache/output ก่อนเสมอ

## 8. เปิด Studio

```powershell
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList ".\studio.py"
```

หรือ:

```powershell
Start OmniVoice Studio.bat
```

จากนั้นกด `Import CSV` และเลือก:

```text
imports/chapter1_serenoa_regen.csv
```

ตรวจว่า:

- Voice Project = `triangle-strategy`
- Voice Target = `serenoa`
- Profile Alias = `narrator`
- Generation Mode = `reference_first`
- Default output อยู่ใต้ `output/studio/triangle-strategy/`

## 9. Optional tools

ตรวจ `ffmpeg` ได้ด้วย:

```powershell
ffmpeg -version
```

ffmpeg ไม่ใช่ dependency หลักของ Engine v1 แต่บางงาน audio utility อาจใช้ หากไม่มี ให้ติดตั้งแยกตาม policy ของเครื่องใหม่

## สิ่งที่ไม่อยู่ใน repository

- `.venv*`
- `output/`
- `work/`
- local recovery/temp/log/cache
- model weights และ Hugging Face cache
- `Thai Voice/` game/extracted artifacts
- secrets และ local environment files

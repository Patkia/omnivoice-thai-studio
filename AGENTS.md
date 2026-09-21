# AGENTS.md — OmniVoice Thai TTS Project

## ภาษา

ตอบผู้ใช้เป็นภาษาไทยเป็นหลัก รวมถึง progress, status, warning, blocker และ final report; technical terms, paths, commands, model ID และ code คงภาษาอังกฤษได้

## Workspace และความปลอดภัย

ทำงานเฉพาะ `C:\Users\Pat\Workshop\omnivoice-thai-studio` ห้ามแตะ F5-TTS, ไฟล์เกม, Git/GitHub โดยไม่ได้รับอนุญาต

## Engine

Thai TTS Engine v1: FROZEN

- model: `hotdogs/omnivoice-thai`
- revision: `252d5f2815a5d7300c7676422bee69141c7756de`
- ห้ามเปลี่ยน model, revision, normalization, pronunciation dictionary, Thai-only gate หรือ approved voice registry semantics

ห้าม train/fine-tune, reference audio หรือ voice cloning หากไม่มีคำสั่งโดยตรง

## Human Listening Gate

ห้ามตัดสินคุณภาพเสียงแทนผู้ใช้ เมื่อมี WAV ใหม่ให้รายงาน `HUMAN LISTENING TEST: WAITING`

## Auto-fix Policy

แก้และ rerun ปัญหาเล็กน้อยได้สูงสุด 3 รอบ (syntax/import/path/fixture/temp permission/assertion/test wiring) แต่ต้องขอคำสั่งก่อนเปลี่ยน architecture, dependency, model/backend หรือ behavior หลัก

## Reporting

รายงานสถานะ, สิ่งที่ทำ, tests, files changed, blocker และ next step เป็นภาษาไทย และห้ามประกาศ READY หาก requirement สำคัญยังไม่ผ่าน

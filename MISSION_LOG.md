# MISSION LOG — OmniVoice Thai TTS

## Batch Runner Safety Guard

แก้ failure mode ที่ caller timeout แต่ TTS process ยังรันจนมีการยิงซ้ำหลาย process: เพิ่ม `tts_batch_runner.py` เป็น orchestration layer เหนือ Engine v1 พร้อม mission lock, sequential persistent worker, checkpoint/resume, per-line timeout watchdog, mission-scoped process-tree cancel, atomic output, stale-lock/crash recovery และ output collision protection. Automated tests ใหม่ใช้ fake adapter เท่านั้น ไม่รัน real TTS.

## Mission 23 — 3 Voice Profile Promotion

Human decisions were promoted to the main Studio registry without altering the frozen engine: `mipha_style` is HUMAN APPROVED from `mipha_candidate_C`; `cute_young_female` is HUMAN APPROVED from `mipha_candidate_B`; and `ancient_deep_male` is HUMAN APPROVED FOR USE from `great_deku_tree_final_raw`. All voice profiles now carry explicit fixed seeds so repeated generations and long-text chunks resolve consistently through the same profile seed. The previous narrator-only long-text seed override was removed; explicit caller seed can still override a profile seed when needed. BOTW voice-style exploration is COMPLETE; no game integration has started.

## POC และการออกเสียง

Thai inference สำเร็จบน CPU ด้วย `hotdogs/omnivoice-thai`.

Approved pronunciation mapping: `แอปเปิล → แอ๊ปเปิ้ล`

เพิ่ม number/time normalization, pronunciation dictionary และ Thai-only gate.

## Voice และ Engine

`bright_female` มาจาก `bright_02`; มี voice profiles สำหรับ narrator, male และ female.

Mission 8: `THAI TTS ENGINE v1: FROZEN` และสร้าง `tts.py`.

Mission 9: Thai TTS Studio พร้อมใช้งาน.

Mission 10: Persistent Model Session สำเร็จ (`studio_v1.1`).

## Long Text

Mission 11C-LITE-G: `LONG TEXT GENERATION: READY`

- 2 chunks
- inference 173.37s
- audio 16.6s
- RTF 10.44
- cache rerun 2/2 cached, 0 inference, model load count 0
- tests 22 passed

## Novel Batch Core

Mission 11/11B/11C: ยังไม่ production-ready แบบเต็ม และสถานะ PAUSED.

## Hermes Integration

Hermes → Codex read-only และ workspace-write auto-fix flow: READY.

## Mission 12B — Natural Boundary Polish

Added deterministic leading-connective protection and concluding-sentence preference while preserving hard max, dialogue/paragraph metadata, emotional beats, and text reconstruction. The preview was rebuilt; human review is required before TTS.

## Mission 13 — Semantic Audio POC

Human review approved semantic chunking for a limited audio POC. Generated only chunks `06, 08, 09, 12, 19, 20` with the frozen model, narrator profile at speed `0.94`, one persistent model load, and recorded dynamic pauses. Preview WAV and `output/semantic_audio_poc/report.json` are ready for human listening. No conclusion about audio quality has been made.

## Mission 14 — Multi-Voice Semantic Audio POC

Generated an A/B comparison from the same six chunks only. The single-voice preview reuses exact Mission 13 narrator WAVs; the multi-voice preview uses a POC-only editorial assignment: chunk 08 `bright_female`, chunks 12 and 19 `warm_female_2`, and narrator elsewhere. The run used one persistent model session for newly required female WAVs. Human listening must choose A, B, or C; Novel Mode is not declared ready.

## Mission 15 — Voice Continuity & Lighter Narration POC

Human feedback: multi-voice is promising but slightly too serious; single narrator chunks do not sound sufficiently continuous. Source inspection confirmed stochastic Gumbel sampling, no direct seed API, and no fixed speaker identity from voice-design tags alone. Added an optional POC seed path that keeps the default Engine v1 path unchanged, then generated current-versus-fixed-seed narrator continuity previews plus `bright_female`, `young_female`, and `cute_teen_soft` lighter narration previews. Human listening is required; no winner has been selected.

## Mission 17 — Long Text Voice Continuity Integration

Human feedback localized a possible continuity issue near chunk 09 in the long passage. Added only a long-text narrator continuity policy: every narrator chunk receives the same POC seed `15015`; no short/simple or Quick Preview call receives it. Seeded cache keys remain separate, while `seed=None` keeps its original cache key plus one backward-compatible lookup. Generated only chunks `08, 09, 10` for an A/B listening pack. The two previews preserve identical order and semantic pause metadata, use `long_text_batch.merge`, omit trailing silence, and share one persistent session (`model_load_count=1`). No conclusion about audio quality has been made; do not promote this POC policy until human listening approves it.

## Mission 18 — Long Text Loudness Continuity POC

Human listening selected the Mission 17 fixed-seed preview for voice identity, while identifying an apparent loudness/energy discontinuity near “แล้วก็ห่อ...”. No TTS was generated. The POC reads only the three existing seeded chunks and writes a separate normalized copy using active-speech RMS, attenuation only, and a 2 dB maximum adjustment. It preserves the semantic order and pauses, adds no trailing silence, and does not enable loudness matching as a production default pending human A/B listening.

## Mission 19 — Continuity-Aware Boundary Rebalancing

Mission 18 did not remove the perceived issue, so the suspected root cause is the mid-sentence action-chain split. Added a small explicit rule that, when an upcoming action tail such as “แล้วก็...” follows an owning action clause such as “แต่เขาก็...”, moves the boundary back before that clause if it remains within the hard maximum. The fixture now produces a 58-character preceding chunk and a 110-character successor containing “แต่เขาก็หยิบ... แล้วก็ห่อ...”. Generated only the two rebalanced fixed-seed chunks for a human A/B comparison against cached Mission 17 chunks 09–10. No quality conclusion or production promotion has been made.

## Mission 19 — BOTW Thai AI Voice Style Reference POC

Identified and decoded a Mipha dialogue reference (`Demo152_0_Text023`) and a Great Deku Tree dialogue reference (`Demo109_2_Text007`) from the supplied Thai Voice mod. The POC uses the clips solely for descriptive style analysis. Four separate candidates use supported OmniVoice tags, fixed seeds, and a single persistent session; no reference audio, speaker embedding, training, or cloning is involved. Candidate profiles are not approved voices and await human listening.

## Current Next Mission

Semantic Novel Chunking & Pause Control: semantic boundary, dialogue/paragraph awareness, emotional beat, dynamic pause metadata และ semantic preview; ไม่มี real long TTS จนกว่าจะผ่าน human review.

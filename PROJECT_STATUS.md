# PROJECT STATUS — OmniVoice Thai TTS

## Batch Runner Safety — READY

เพิ่ม `tts_batch_runner.py` สำหรับงานหลายบรรทัด: single-run lock ต่อ mission, worker เดียวแบบ sequential, checkpoint/resume, per-line watchdog timeout, kill เฉพาะ mission process tree, atomic `.part` → final rename, stale-lock recovery และ collision guard. ถ้า caller เช่น Serena timeout แต่ worker ยังรันอยู่ การเรียก mission เดิมซ้ำจะถูก block; ใช้ `status`/`cancel` แล้ว `run` เดิมเพื่อ resume ได้. ไม่มีการเปลี่ยน frozen Engine v1 หรือ Studio behavior เดิม.

## Mission 23 — Human-Selected Character Profile Promotion

BOTW-style voice exploration is complete. The main Studio registry includes `mipha_style` (seed `19102`, speed `0.92`), `cute_young_female` (seed `19102`, speed `1.00`), and `ancient_deep_male` (seed `20105`, speed `0.68`). All remaining voice profiles now also have explicit fixed seeds so short generation and long-text chunks resolve to the same profile identity. The old narrator-only long-text seed override was removed; long text now delegates seed resolution to the profile through `StudioEngineAdapter`. These profiles use frozen Engine v1; model/revision and voice instructions are unchanged.

## Engine

`THAI TTS ENGINE v1: FROZEN`

- Model: `hotdogs/omnivoice-thai`
- Revision: `252d5f2815a5d7300c7676422bee69141c7756de`
- Device: CPU
- PyTorch: `2.13.0+cpu`
- CUDA: ไม่พร้อมใช้งาน

## CLI และ Studio

- CLI: `tts.py`
- Studio: `studio_v1.1` / `studio.py` / PySide6
- รองรับ text/TXT, voice, speed, normalized preview, Thai-only gate, cache, audio playback และ persistent model session

## Long Text Generation

`LONG TEXT GENERATION: READY`

- `<= 120` characters ใช้ short path
- `> 120` characters ใช้ chunking (target ~100, hard max 120)
- persistent session, progress UI, cooperative cancel, per-chunk cache และ WAV merge
- long-text smoke: 2 chunks, inference 173.37s, audio 16.6s, RTF 10.44
- cache rerun: 2/2 cached, inference 0, model load count 0, ~7.258s
- automated tests: 22 passed

## Novel Work

Novel Batch Core แบบเต็ม: PAUSED

Current priority: Semantic Novel Chunking & Pause Control; ยังห้าม real long TTS จนกว่าจะผ่าน human review

## Mission 12B — Natural Boundary Polish

Semantic preview now protects leading connective phrases and prefers a separate final concluding unit when it fits within the hard limit. Human review remains required before any real long-form TTS.

## Mission 13 — Semantic Audio POC

The approved representative chunks `06, 08, 09, 12, 19, 20` were generated with the frozen Engine v1 using one `PersistentTtsSession`, narrator speed `0.94`, and the preview's recorded pause metadata. Output: `output/semantic_audio_poc/semantic_audio_preview.wav`. Human listening review is pending; Novel Mode is not declared ready.

## Mission 14 — Multi-Voice Semantic Audio POC

Created a limited A/B listening pack from the same six approved chunks. `single_voice_preview.wav` reuses the Mission 13 narrator artifacts; `multi_voice_preview.wav` uses the POC-only role mapping with `bright_female` for chunk 08 and `warm_female_2` for chunks 12 and 19. Human listening review is pending; Novel Mode is not declared ready.

## Mission 15 — Voice Continuity & Lighter Narration POC

Human feedback on Mission 14: multi-voice has potential but is slightly too serious; the narrator-only preview lacks continuity between chunks. The installed OmniVoice runtime uses stochastic Gumbel sampling and offers no direct `seed=` argument. A POC-only optional seed path now reseeds inside the persistent-session lock and is isolated in the cache key; default Engine v1 behavior remains unchanged. Created continuity A/B and three lighter-tone listening previews. Human listening review is pending; Novel Mode is not declared ready.

## Mission 17 — Long Text Voice Continuity Integration

Human feedback identified a narrator continuity break around semantic chunk 09. The long-text path now has a minimal POC-only narrator policy (`seed=15015`) that forwards the same seed to every long-text chunk; short/simple generation and Quick Voice Preview remain unseeded. A limited A/B pack was generated only for reviewed chunks `08, 09, 10`: `current_preview.wav` uses no seed and `fixed_seed_preview.wav` uses seed `15015`. Both packs use one persistent session, the same source order, the same pause metadata, and the same merge function. Human listening must decide whether the seeded candidate helps; this is not a production default and Novel Mode is not declared ready.

## Mission 18 — Long Text Loudness Continuity POC

Human listening selected the fixed-seed continuity candidate but reported an energy/loudness discontinuity. Using only the Mission 17 seeded WAVs, a separate A/B pack applies conservative active-speech RMS matching with attenuation only (maximum 2 dB), no compression, and no changes to TTS source audio, pitch, speed, ordering, or pauses. This remains a listening POC and is not a production default.

## Mission 19 — Continuity-Aware Boundary Rebalancing

Mission 18 loudness matching did not resolve the reported action-chain transition. The root-cause suspect is now the mid-sentence boundary before “แล้วก็ห่อ...”. A narrow deterministic action-chain rule rebalances this fixture to end the preceding chunk after “สร้างสรรค์นัก” and begin the next one with “แต่เขาก็หยิบ... แล้วก็ห่อ...”, while retaining the 120-character hard limit and existing pause policy. A two-chunk fixed-seed A/B listening pack is pending human review; the heuristic is not promoted beyond this tested rule.

## Mission 19 — BOTW Thai AI Voice Style Reference POC

Decoded two identified BOTW Thai dialogue streams into local reference WAVs, then created four descriptive OmniVoice candidates using only runtime-supported gender/age/pitch tags, speed, and fixed seeds. Reference WAVs were never supplied to the model; no embedding or cloning was used. These candidates are separate from the approved registry and require human listening before any future character-profile decision.

## Hermes

Hermes → Codex workspace read-only และ workspace-write auto-fix POC: READY

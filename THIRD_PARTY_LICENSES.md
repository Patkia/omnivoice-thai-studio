# Third-party components and data

This repository contains integration code and metadata for third-party models and datasets. Audio/reference assets and generated output are intentionally excluded from the public repository.

## OmniVoice Thai model

- Model: `hotdogs/omnivoice-thai`
- Source: Hugging Face
- License reported by the model card: Apache-2.0
- This repository does not redistribute the model weights.

## THAI-SER dataset

- Dataset: `airesearch/thai-ser`
- Source: Hugging Face
- License reported by the dataset card: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
- Any locally prepared reference clips derived from THAI-SER remain outside the public repository. If you redistribute derived audio, you are responsible for the attribution/share-alike obligations that apply.

## Other voice-reference sources

`hf_voice_reference_manifest.csv` records provenance and license metadata collected during local voice-reference research. Some candidate sources are marked CC BY 4.0 and some CC BY-NC 4.0. The corresponding audio files are not part of the public release.

Before redistributing any third-party audio or derived voice pack, review the source license and attribution requirements for that specific asset.

## Game-specific content

Game dialogue CSVs, generated chapter audio and local voice-reference packs are intentionally excluded from the public repository. The public tree is intended to contain the Studio/engine code, project configuration examples, tests and provenance metadata rather than copyrighted dialogue/audio assets.

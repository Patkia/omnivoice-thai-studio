"""Thread-safe, lazy OmniVoice runtime shared by persistent Studio sessions."""
from __future__ import annotations
import threading
import time
from typing import Callable
import numpy as np
import torch
from omnivoice import OmniVoice
from omnivoice.utils.common import fix_random_seed
from audio_validation import validate_audible_audio

class PersistentTtsSession:
    def __init__(self, model_id: str, revision: str):
        self.model_id, self.revision = model_id, revision
        self.model = None
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.model_load_count = 0
        self.reference_prompt_prep_count = 0
        self._voice_clone_prompts = {}
        self._lock = threading.RLock()

    @property
    def state(self) -> str: return "MODEL_READY" if self.model is not None else "MODEL_NOT_LOADED"

    def _ensure_model(self, status: Callable[[str], None] | None = None) -> tuple[float, bool]:
        load_seconds = 0.0
        reused = self.model is not None
        if self.model is None:
            if status:
                status("กำลังโหลดโมเดล...")
            started = time.perf_counter()
            try:
                self.model = OmniVoice.from_pretrained(
                    self.model_id, revision=self.revision, device_map=self.device,
                    dtype=torch.float16 if self.device.startswith("cuda") else torch.float32,
                )
            except Exception:
                self.model = None
                raise
            load_seconds = time.perf_counter() - started
            self.model_load_count += 1
        return load_seconds, reused

    def prepare_voice_clone_prompt(
        self, ref_audio: str, ref_text: str, *, prompt_key: str,
        status: Callable[[str], None] | None = None,
    ):
        """Prepare one reference prompt per exact reference/transcript identity."""
        with self._lock:
            load_seconds, model_reused = self._ensure_model(status)
            cached = self._voice_clone_prompts.get(prompt_key)
            if cached is not None:
                return cached, {
                    "reference_prompt_cache_hit": True,
                    "reference_prompt_seconds": 0.0,
                    "reference_prompt_prep_count": self.reference_prompt_prep_count,
                    "model_load_seconds": round(load_seconds, 3),
                    "model_load_count": self.model_load_count,
                    "model_reused": model_reused,
                    "device": self.device,
                }
            if status:
                status("กำลังเตรียม Reference voice...")
            started = time.perf_counter()
            prompt = self.model.create_voice_clone_prompt(
                ref_audio, ref_text=ref_text, preprocess_prompt=True,
            )
            elapsed = time.perf_counter() - started
            self._voice_clone_prompts[prompt_key] = prompt
            self.reference_prompt_prep_count += 1
            return prompt, {
                "reference_prompt_cache_hit": False,
                "reference_prompt_seconds": round(elapsed, 3),
                "reference_prompt_prep_count": self.reference_prompt_prep_count,
                "model_load_seconds": round(load_seconds, 3),
                "model_load_count": self.model_load_count,
                "model_reused": model_reused,
                "device": self.device,
            }

    def generate(self, text: str, instruct: str | None, speed: float, steps: int, status: Callable[[str], None] | None = None,
                 seed: int | None = None, voice_clone_prompt=None,
                 generation_mode: str = "voice_design", language: str | None = None,
                 denoise: bool | None = None, postprocess_output: bool | None = None) -> tuple[np.ndarray, dict]:
        with self._lock:
            load_seconds, reused = self._ensure_model(status)
            if status: status("กำลังสร้างเสียง...")
            if seed is not None:
                fix_random_seed(seed)
            started = time.perf_counter()
            if generation_mode not in {"voice_design", "reference_first"}:
                raise ValueError(f"unsupported generation_mode: {generation_mode}")
            if generation_mode == "reference_first" and voice_clone_prompt is None:
                raise ValueError("reference_first requires voice_clone_prompt")
            generation_options = {"speed": speed, "num_step": steps}
            if instruct is not None:
                generation_options["instruct"] = instruct
            if voice_clone_prompt is not None:
                generation_options["voice_clone_prompt"] = voice_clone_prompt
            if language is not None:
                generation_options["language"] = language
            if denoise is not None:
                generation_options["denoise"] = denoise
            if postprocess_output is not None:
                generation_options["postprocess_output"] = postprocess_output
            audio = np.asarray(self.model.generate(text, **generation_options)[0], dtype=np.float32)
            stats = validate_audible_audio(audio)
            peak = stats["peak"]
            audio *= (10 ** (-1 / 20)) / peak
            return audio, {"model_load_seconds": round(load_seconds, 3), "inference_seconds": round(time.perf_counter()-started, 3), "model_reused": reused, "model_load_count": self.model_load_count, "device": self.device, "seed": seed, "generation_mode": generation_mode, "reference_conditioning": voice_clone_prompt is not None, "reference_prompt_prep_count": self.reference_prompt_prep_count, "audio_signal_stats": stats}

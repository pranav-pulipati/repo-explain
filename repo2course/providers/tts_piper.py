"""Piper: fast, fully local neural TTS.

Install: `uv pip install piper-tts`, then download a voice (.onnx + .onnx.json),
e.g. from https://huggingface.co/rhasspy/piper-voices.
config.yaml:
  tts: {provider: piper, voice: en_US-ryan-high, model_path: voices/en_US-ryan-high.onnx}
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path

from piper import PiperVoice

from .base import ProviderError, TTSProvider
from .registry import register_tts


@register_tts("piper")
class PiperTTS(TTSProvider):
    max_chars = 5000
    output_suffix = ".wav"

    def __init__(self, config, cache=None, usage=None):
        super().__init__(config, cache, usage)
        model_path = config.extra("model_path")
        if not model_path or not Path(model_path).exists():
            raise ProviderError("Piper needs `tts.model_path` pointing to a downloaded .onnx voice file.")
        self._voice = PiperVoice.load(model_path)
        self._lock = threading.Lock()  # PiperVoice is not documented as thread-safe

    def _synthesize(self, text, out_path):
        with self._lock, wave.open(str(out_path), "wb") as wav:
            if hasattr(self._voice, "synthesize_wav"):  # piper-tts >= 1.3
                self._voice.synthesize_wav(text, wav)
            else:
                self._voice.synthesize(text, wav)
        return out_path

    def is_retryable(self, exc):
        return False

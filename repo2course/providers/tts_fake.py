"""Offline fake TTS: writes silent WAV whose length tracks the word count."""

from __future__ import annotations

import wave

from .base import TTSProvider
from .registry import register_tts

WORDS_PER_SECOND = 2.5  # 150 wpm
SAMPLE_RATE = 8000


@register_tts("fake")
class FakeTTS(TTSProvider):
    max_chars = 400
    output_suffix = ".wav"

    def __init__(self, config, cache=None, usage=None):
        super().__init__(config, cache, usage)
        self.calls: list[str] = []

    def _synthesize(self, text, out_path):
        self.calls.append(text)
        seconds = max(0.2, len(text.split()) / WORDS_PER_SECOND)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(b"\x00\x00" * int(seconds * SAMPLE_RATE))
        return out_path

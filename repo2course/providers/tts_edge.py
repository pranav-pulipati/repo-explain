"""Microsoft Edge read-aloud voices via edge-tts (free, no key).

config.yaml:
  tts: {provider: edge, voice: en-US-AndrewNeural, rate: "+0%"}
List voices with `edge-tts --list-voices`.
"""

from __future__ import annotations

import asyncio

import edge_tts

from .base import TTSProvider
from .registry import register_tts


@register_tts("edge")
class EdgeTTS(TTSProvider):
    max_chars = 3000
    output_suffix = ".mp3"

    def _synthesize(self, text, out_path):
        async def run():
            comm = edge_tts.Communicate(text, self.config.voice, rate=self.config.rate)
            await comm.save(str(out_path))

        asyncio.run(run())
        return out_path

    def is_retryable(self, exc):
        # The service drops connections and occasionally returns no audio; a
        # bad voice name surfaces as ValueError and is not worth retrying.
        return not isinstance(exc, (ValueError, TypeError))

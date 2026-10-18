"""ElevenLabs TTS — STUB. A worked implementation is in README.md ("Adding a provider").

TODO: implement with the `elevenlabs` SDK (or plain httpx):
  - __init__: key from `ELEVENLABS_API_KEY`; `voice` in config is the voice_id.
  - _synthesize: `client.text_to_speech.convert(voice_id=..., model_id=self.config.extra(
    "model_id", "eleven_multilingual_v2"), text=text, output_format="mp3_44100_128")`
    returns an iterator of bytes; write them to out_path.
  - max_chars ~ 5000 (model dependent); map HTTP 429 to RetryableError.
"""

from __future__ import annotations

from .base import ProviderError, TTSProvider
from .registry import register_tts


@register_tts("elevenlabs")
class ElevenLabsTTS(TTSProvider):
    def __init__(self, config, cache=None, usage=None):
        raise ProviderError("The ElevenLabs provider is a stub; see providers/tts_elevenlabs.py.")

    def _synthesize(self, text, out_path):  # pragma: no cover
        raise NotImplementedError

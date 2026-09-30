"""Urdu text-to-speech via edge-tts.

Supported voices (selectable per business config):
  ur-PK-GulNawazNeural - female
  ur-PK-AsadNeural      - male
"""
from __future__ import annotations

import asyncio
import io

import edge_tts

SUPPORTED_VOICES = {
    "ur-PK-GulNawazNeural": "female",
    "ur-PK-AsadNeural": "male",
}


def synthesize(text: str, voice: str) -> bytes:
    """Synthesize text to MP3 bytes. Raises ValueError on unknown voice."""
    if voice not in SUPPORTED_VOICES:
        raise ValueError(
            f"unsupported voice '{voice}'. Choose from {sorted(SUPPORTED_VOICES)}"
        )
    if not text or not text.strip():
        raise ValueError("cannot synthesize empty text")
    return asyncio.run(_synthesize_async(text.strip(), voice))


async def _synthesize_async(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    data = buf.getvalue()
    if not data:
        raise RuntimeError(f"edge-tts returned no audio for voice {voice}")
    return data

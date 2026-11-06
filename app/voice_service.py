"""Unified Voice & Cloning Service.

Features:
- Primary: Fish Audio API (v1/tts) via ormsgpack with zero-shot voice cloning from reference audio
- Native Pakistani Fallback: edge-tts 7.3+ (Microsoft Neural: ur-PK-UzmaNeural / ur-PK-AsadNeural)
- In-memory & disk audio caching for fast repeat turns
- FFmpeg audio sanitization for clean 44.1kHz mono speech samples
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from pathlib import Path
import subprocess
import httpx
import edge_tts
import ormsgpack

log = logging.getLogger("voice_service")

# Auto-load .env
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            if _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip()

FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY", "")
FISH_TTS_URL = "https://api.fish.audio/v1/tts"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "audio_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_MEM_CACHE: dict[str, bytes] = {}


def sanitize_audio_to_mp3(raw_bytes: bytes) -> bytes:
    """Converts any browser audio (WebM, OGG, WAV) into pristine 44.1kHz mono MP3."""
    if not raw_bytes or len(raw_bytes) < 500:
        return b""
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                "pipe:0",
                "-ar",
                "44100",
                "-ac",
                "1",
                "-b:a",
                "128k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=raw_bytes,
            capture_output=True,
            check=True,
        )
        if proc.stdout and len(proc.stdout) > 500:
            return proc.stdout
    except Exception as e:
        log.warning("FFmpeg conversion error: %s; using original bytes", e)
    return raw_bytes


def _get_cache_key(text: str, voice_or_ref: str) -> str:
    h = hashlib.sha256()
    h.update(text.strip().encode("utf-8"))
    h.update(voice_or_ref.encode("utf-8"))
    return h.hexdigest()


async def synthesize_speech(
    text: str,
    reference_audio_bytes: bytes | None = None,
    reference_text: str | None = None,
    fallback_voice: str = "ur-PK-UzmaNeural",
) -> bytes:
    """Synthesize speech using Fish Audio voice cloning if reference provided,

    or native Pakistani Neural voice via edge-tts to guarantee authentic accent.
    """
    text = text.strip()
    if not text:
        return b""

    # Cache check
    ref_sig = str(len(reference_audio_bytes)) if reference_audio_bytes else fallback_voice
    cache_key = _get_cache_key(text, ref_sig)

    if cache_key in _MEM_CACHE:
        return _MEM_CACHE[cache_key]

    disk_path = CACHE_DIR / f"{cache_key}.mp3"
    if disk_path.exists():
        try:
            data = disk_path.read_bytes()
            if data:
                _MEM_CACHE[cache_key] = data
                return data
        except Exception:
            pass

    # 1. If user provided a reference voice sample, use Fish Audio zero-shot cloning
    if reference_audio_bytes and FISH_AUDIO_API_KEY:
        try:
            audio_bytes = await _synthesize_fish_cloned(
                text, reference_audio_bytes, reference_text
            )
            if audio_bytes and len(audio_bytes) > 1000:
                _MEM_CACHE[cache_key] = audio_bytes
                disk_path.write_bytes(audio_bytes)
                return audio_bytes
        except Exception as e:
            log.warning("Fish Audio clone failed: %s; falling back to Pakistani Neural voice", e)

    # 2. Native Pakistani Neural voice (edge-tts 7.3+)
    # Guarantees authentic Urdu accent with zero foreign/English accent
    try:
        audio_bytes = await _synthesize_edge_tts(text, fallback_voice)
        if audio_bytes:
            _MEM_CACHE[cache_key] = audio_bytes
            disk_path.write_bytes(audio_bytes)
            return audio_bytes
    except Exception as e:
        log.error("Edge-TTS Pakistani Neural synthesis failed: %s", e)

    # 3. Last-ditch Fish Audio base voice
    if FISH_AUDIO_API_KEY:
        try:
            audio_bytes = await _synthesize_fish_base(text)
            if audio_bytes and len(audio_bytes) > 1000:
                _MEM_CACHE[cache_key] = audio_bytes
                disk_path.write_bytes(audio_bytes)
                return audio_bytes
        except Exception as e:
            log.error("Fish Audio base failed: %s", e)

    return b""


async def _synthesize_fish_cloned(
    text: str,
    reference_audio_bytes: bytes,
    reference_text: str | None = None,
) -> bytes:
    """Clones the voice sample using Fish Audio MessagePack protocol."""
    headers = {
        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
        "Content-Type": "application/msgpack",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    payload = {
        "text": text,
        "format": "mp3",
        "latency": "balanced",
        "temperature": 0.7,
        "top_p": 0.7,
        "references": [
            {
                "audio": reference_audio_bytes,
                "text": reference_text
                or "Salam! Hamari clinic Lahore mein hai. Hum checkups scaling provide karte hain.",
            }
        ],
    }

    packed_data = ormsgpack.packb(payload)

    async with httpx.AsyncClient(timeout=18.0) as client:
        resp = await client.post(FISH_TTS_URL, headers=headers, content=packed_data)
        if resp.status_code == 200:
            return resp.content
        log.warning("Fish Audio clone returned HTTP %s: %s", resp.status_code, resp.text[:200])
        raise RuntimeError(f"Fish Audio error: {resp.status_code}")


async def _synthesize_fish_base(text: str) -> bytes:
    headers = {
        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    payload = {
        "text": text,
        "format": "mp3",
        "latency": "balanced",
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(FISH_TTS_URL, headers=headers, json=payload)
        if resp.status_code == 200:
            return resp.content
        raise RuntimeError(f"Fish Audio base error: {resp.status_code}")


async def _synthesize_edge_tts(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()

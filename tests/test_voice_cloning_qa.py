"""Automated QA Test Suite for Voice Cloning, Authentic Pakistani Urdu Pronunciation,
Free Tier Model Enforcement, and Zero-Hallucination Guardrails.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import voice_service
from app import llm_service
from app import demo_routes


def test_fish_free_model_identifier():
    """Verify that the official free tier model identifier s2.1-pro-free is configured."""
    assert voice_service.FISH_FREE_MODEL == "s2.1-pro-free"
    assert "s2.1-pro-free" in voice_service.FISH_FREE_MODEL


def test_no_aiza_model_in_user_cloning_request():
    """Verify that user instant voice cloning NEVER includes AIZA_MODEL_ID or reference_id anchor.

    User voice cloning must be 100% anchored to the user's uploaded voice sample.
    """
    async def _run():
        mock_post = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ID3" + b"\x00" * 2000  # valid mock mp3 bytes
        mock_post.return_value = mock_resp

        test_audio = b"\x00\x01\x02\x03" * 500
        test_transcript = "السلام علیکم! یہ میری اصلی آواز کا نمونہ ہے۔"

        with patch("httpx.AsyncClient.post", mock_post):
            res = await voice_service._synthesize_fish_cloned(
                text="جی بتائیں، میں آپ کی کیا مدد کر سکتی ہوں؟",
                reference_audio_bytes=test_audio,
                reference_text=test_transcript,
                speed=1.0,
            )

        assert len(res) > 1000
        assert mock_post.called

        # Extract the payload sent to Fish Audio
        called_kwargs = mock_post.call_args.kwargs
        headers = called_kwargs.get("headers", {})
        assert headers.get("model") == "s2.1-pro-free", "Request header must target s2.1-pro-free"

        import ormsgpack
        packed_body = called_kwargs.get("content")
        payload = ormsgpack.unpackb(packed_body)

        # CRITICAL: Verify NO reference_id was passed in cloning request
        assert "reference_id" not in payload, "Cloning request must NEVER contain reference_id or foreign voice anchor!"
        assert payload.get("model") == "s2.1-pro-free"
        assert "references" in payload
        assert len(payload["references"]) == 1
        assert payload["references"][0]["audio"] == test_audio
        assert payload["references"][0]["text"] == test_transcript

    asyncio.run(_run())


def test_no_silent_fallback_on_cloning_failure():
    """Verify that when voice cloning fails and allow_fallback=False,

    VoiceCloningError is raised instead of silently pretending a preset voice is the clone.
    """
    async def _run():
        mock_post = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limit reached on free tier"
        mock_post.return_value = mock_resp

        dummy_audio = b"sample_pcm_audio_data" * 100

        with patch("httpx.AsyncClient.post", mock_post):
            with pytest.raises(voice_service.VoiceCloningError) as exc_info:
                await voice_service.synthesize_speech(
                    text="ہماری ٹائمنگ صبح گیارہ بجے ہے۔",
                    reference_audio_bytes=dummy_audio,
                    reference_text="ریفرنس ٹرانسکرپٹ",
                    fallback_voice="ur-PK-UzmaNeural",
                    allow_fallback=False,  # Strict honesty enforcement
                )

        assert "Voice cloning failed" in str(exc_info.value)
        assert "429" in str(exc_info.value)

    asyncio.run(_run())


def test_cryptographic_cache_uniqueness():
    """Verify that different audio samples or transcripts of identical length

    produce completely unique SHA-256 cache keys (zero cache collision).
    """
    audio_sample_1 = b"AAAA" * 500  # 2000 bytes
    audio_sample_2 = b"BBBB" * 500  # 2000 bytes (identical length!)
    transcript_1 = "السلام علیکم لاہور کلینک"
    transcript_2 = "السلام علیکم کراچی کلینک"

    key1 = voice_service.compute_cache_key("ٹیکسٹ", audio_sample_1, transcript_1, "s2.1-pro-free", 1.0)
    key2 = voice_service.compute_cache_key("ٹیکسٹ", audio_sample_2, transcript_1, "s2.1-pro-free", 1.0)
    key3 = voice_service.compute_cache_key("ٹیکسٹ", audio_sample_1, transcript_2, "s2.1-pro-free", 1.0)

    assert len(key1) == 64
    assert len(key2) == 64
    assert len(key3) == 64
    assert key1 != key2, "Different audio with identical byte count must have different cache keys!"
    assert key1 != key3, "Different reference transcript must produce different cache key!"


def test_no_hallucinated_prices_when_services_empty():
    """Verify that empty or unlisted services do NOT invent default 'Rs 1,500'."""
    profile_empty = {
        "id": "agent-test",
        "agent_name": "Zoya",
        "name": "Empty Services Biz",
        "category": "Consulting",
        "location": "Lahore",
        "hours": "10 AM - 6 PM",
        "services": [],
        "fallback_response": "Maloomat nahi hai ji.",
    }

    prompt = llm_service.build_system_prompt(profile_empty)
    assert "Rs 1,500" not in prompt, "Empty services must NEVER inject hardcoded Rs 1,500 fallback price!"
    assert "No specific services or prices configured" in prompt

    # Verify _normalize_confirmed_items does not fabricate 1500
    confirmed = demo_routes._normalize_confirmed_items(["Pizza Delivery"], [])
    assert confirmed == [], "Unlisted item in empty services must return empty list, not fake 1500 PKR receipt!"


def test_transcribe_reference_does_not_fabricate():
    """Verify that transcribe_reference_audio never returns a canned/fake fallback transcript."""
    async def _run():
        # When audio is too short, must raise ValueError
        with pytest.raises(ValueError):
            await voice_service.transcribe_reference_audio(b"short")

        # When Groq Whisper fails, must raise exception rather than returning fake greeting
        mock_post = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Whisper Error"
        mock_post.return_value = mock_resp

        with patch("httpx.AsyncClient.post", mock_post):
            with pytest.raises(RuntimeError):
                await voice_service.transcribe_reference_audio(b"dummy_audio_bytes" * 100)

    asyncio.run(_run())


def test_transcribe_reference_endpoint():
    """Verify /api/demo/transcribe-reference returns structured JSON with Whisper transcription."""
    with TestClient(app) as client:
        with patch("app.voice_service.transcribe_reference_audio", AsyncMock(return_value="السلام علیکم! یہ میری آواز ہے۔")):
            file_data = io.BytesIO(b"RIFF" + b"\x00" * 1000)
            res = client.post(
                "/api/demo/transcribe-reference",
                files={"voice_file": ("test.wav", file_data, "audio/wav")},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["transcript"] == "السلام علیکم! یہ میری آواز ہے۔"


def test_delete_voice_endpoint():
    """Verify /api/demo/delete-voice purges voice reference and audio cache for user privacy."""
    with TestClient(app) as client:
        res = client.post("/api/demo/delete-voice")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "purged" in data["message"].lower() or "cleared" in data["message"].lower()


def test_code_switching_phonetics_urdu_mapping():
    """Verify natural code-switching terms map to proper native Urdu script for TTS."""
    from app.voice_service import normalize_urdu_phonetics_for_tts

    # Business communication loanwords
    text = "Aap clinic timing aur WhatsApp pe appointment charges send kar dein."
    normalized = normalize_urdu_phonetics_for_tts(text)

    assert "کلینک" in normalized
    assert "واٹس ایپ" in normalized
    assert "اپائنٹمنٹ" in normalized
    assert "چارجز" in normalized
    assert "ٹائمنگ" in normalized


def test_booking_confirmation_tool_validation():
    """Verify verified business services match and unverified services are rejected."""
    services = [
        {"name": "Teeth Scaling", "price_pkr": 4000, "duration_min": 30},
        {"name": "Laser Whitening", "price_pkr": 12000, "duration_min": 60},
    ]

    # Valid service booking
    confirmed = demo_routes._normalize_confirmed_items(["Teeth Scaling"], services)
    assert len(confirmed) == 1
    assert confirmed[0]["name"] == "Teeth Scaling"
    assert confirmed[0]["price_pkr"] == 4000

    # Unlisted service booking (e.g. caller asks dental clinic for Burger)
    unlisted = demo_routes._normalize_confirmed_items(["Chicken Burger"], services)
    assert unlisted == [], "Unlisted item must not be confirmed"

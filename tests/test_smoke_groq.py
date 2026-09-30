"""REAL-API smoke tests. Env-gated: they SKIP cleanly when GROQ_API_KEY is unset.

These are the only tests allowed to touch the network. Per the project's
free-tier frugality policy they are capped at:
  (a) ONE Whisper STT call,
  (b) ONE LLM chat turn,
  (c) ONE edge-tts TTS sample.
Never add more real calls here, and never run them in CI without a key.

Run explicitly:  GROQ_API_KEY=... pytest tests/test_smoke_groq.py -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping real-API smoke tests",
)


def test_a_stt_transcribes_urdu_voice_note():
    """Synthesize one Urdu sentence with edge-tts, transcribe via Groq Whisper."""
    from app import groq_client, tts

    sentence = "السلام علیکم، مجھے کل شام پانچ بجے اپائنٹمنٹ چاہیے"
    audio = tts.synthesize(sentence, "ur-PK-GulNawazNeural")
    assert len(audio) > 1000, "TTS produced no meaningful audio"

    text = groq_client.transcribe_audio(audio, language_hint="ur",
                                        filename="smoke.ogg")
    assert text, "Whisper returned empty transcription"
    # At least one content word should survive the round trip.
    keywords = ["اپائنٹمنٹ", "پانچ", "شام", "کل"]
    assert any(k in text for k in keywords), f"unexpected transcript: {text!r}"


def test_b_llm_chat_as_receptionist():
    """One chat turn as the AI receptionist."""
    from app import groq_client

    reply = groq_client.chat([
        {"role": "system",
         "content": "You are the AI receptionist for SmileCare Dental Clinic in "
                    "Islamabad. Reply in Roman Urdu, keep it to 1-2 sentences."},
        {"role": "user", "content": "Salam, kal shaam 5 baje ka time mil sakta hai?"},
    ])
    assert reply and len(reply) > 10, "LLM returned empty reply"


def test_c_tts_generates_mp3():
    """One edge-tts generation produces non-empty MP3 bytes."""
    from app import tts

    data = tts.synthesize("Khush aamdeed! Hum aap ki kya madad kar sakte hain?",
                          "ur-PK-AsadNeural")
    assert len(data) > 1000, "TTS produced no meaningful audio"
    # MP3 frames start with 0xFF sync bits or an ID3 tag.
    assert data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0), \
        "output does not look like MP3"

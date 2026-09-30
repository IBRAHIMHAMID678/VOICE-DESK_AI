"""Engine routing with mocked Groq + WhatsApp sender. Zero network calls."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import booking as b
from app import cache as cache_mod
from app import db as dbmod
from app import groq_client
from app.engine import Engine

PK = ZoneInfo("Asia/Karachi")


def test_booking_flow_text(engine):
    # 1. Booking intent with a clear slot -> asks for name/phone (required).
    r = engine.handle("test-biz", "+923001234567",
                      text="Salam, kal shaam 5 baje scaling karwana hai")
    assert "booking_intent" in r.actions
    assert "booking_created_pending" in r.actions
    assert r.lang == "roman_urdu"
    assert r.reply_audio is None  # text in -> text out
    assert "5" in r.reply_text

    # 2. Provide name + phone -> asks for confirmation.
    r = engine.handle("test-biz", "+923001234567",
                      text="mera naam Ali Raza hai, number 03001234567")
    assert "details_captured" in r.actions
    assert "haan" in r.reply_text.lower() or "confirm" in r.reply_text.lower()

    # 3. Confirm -> booking confirmed in DB.
    r = engine.handle("test-biz", "+923001234567", text="haan")
    assert "booking_confirmed" in r.actions
    conn = dbmod.connect(engine.db_path)
    try:
        row = conn.execute(
            "SELECT * FROM bookings WHERE business_id='test-biz'").fetchone()
        assert row["status"] == "confirmed"
        assert row["customer_name"] == "Ali Raza"
        assert row["start"] == "2026-09-28T17:00:00+05:00"
    finally:
        conn.close()


def test_booking_cancel_flow(engine):
    engine.handle("test-biz", "+923009999999", text="kal 5 baje checkup")
    engine.handle("test-biz", "+923009999999",
                  text="Sara 03009876543")
    r = engine.handle("test-biz", "+923009999999", text="nahi")
    assert "booking_cancelled" in r.actions


def test_slot_conflict_offers_alternatives(engine):
    conn = dbmod.connect(engine.db_path)
    try:
        dbmod.insert_booking(
            conn, "test-biz", "Ali", "+923001234567", "General Checkup",
            "2026-09-28T17:00:00+05:00", "2026-09-28T17:30:00+05:00",
            status="confirmed")
    finally:
        conn.close()
    r = engine.handle("test-biz", "+923009999999", text="kal 5 baje checkup")
    assert "slot_unavailable:conflict" in r.actions
    assert "1." in r.reply_text and "2." in r.reply_text
    # Pick alternative 1 -> proceeds to details/confirm.
    r2 = engine.handle("test-biz", "+923009999999", text="1")
    assert "booking_created_pending" in r2.actions


def test_audio_inbound_gets_voice_reply_and_cached_transcript(engine):
    r = engine.handle("test-biz", "+923001234567", audio_bytes=b"voice-bytes-1")
    assert r.reply_audio == b"FAKEMP3" + r.reply_text.encode("utf-8")[:10]
    assert "transcribed" in r.actions
    assert engine.calls["transcribe"] == 1
    # Same bytes again -> transcript cache hit, transcriber NOT called again.
    r2 = engine.handle("test-biz", "+923001234567", audio_bytes=b"voice-bytes-1")
    assert "transcript_cache_hit" in r2.actions
    assert engine.calls["transcribe"] == 1


def test_tts_cache_hit_on_repeat(engine):
    actions: list = []
    a1 = engine._tts_cached("salam", "ur-PK-GulNawazNeural", actions)
    a2 = engine._tts_cached("salam", "ur-PK-GulNawazNeural", actions)
    assert a1 == a2
    assert a1 == b"FAKEMP3salam"
    assert engine.calls["tts"] == 1  # synthesized once, then cache hit
    assert "tts_cache_hit" in actions


def test_llm_chat_path(engine):
    r = engine.handle("test-biz", "+923001234567", text="parking available hai?")
    assert "llm_chat" in r.actions
    assert engine.calls["llm"] == 1
    assert "parking" in r.reply_text.lower()


def test_llm_rate_limit_degrades_gracefully(db_path, test_config, tmp_path):
    def boom(messages):
        raise groq_client.GroqRateLimited("429")

    eng = Engine(db_path, {"test-biz": test_config}, llm_chat=boom,
                 tts_cache_dir=tmp_path / "tts",
                 now_fn=lambda: datetime(2026, 9, 27, 13, 40, tzinfo=PK))
    r = eng.handle("test-biz", "+923001234567", text="parking available hai?")
    assert "llm_rate_limited" in r.actions
    assert r.reply_text  # polite templated fallback, never empty


def test_same_language_reply_urdu(engine):
    r = engine.handle("test-biz", "+923001234567",
                      text="کلینک کی ٹائمنگ کیا ہے؟")
    assert r.lang == "ur"


def test_owner_notified_on_confirm(engine):
    engine.handle("test-biz", "+923001234567", text="kal 5 baje checkup")
    engine.handle("test-biz", "+923001234567", text="Ali Raza 03001234567")
    r = engine.handle("test-biz", "+923001234567", text="haan")
    assert r.notify_owner is not None
    assert "General Checkup" in r.notify_owner
    assert "Ali Raza" in r.notify_owner


def test_after_hours_only_first_message(engine, test_config):
    # Sunday is closed in the test config; FIXED_NOW is a Sunday.
    r1 = engine.handle("test-biz", "+923005556666", text="parking available hai?")
    assert "after_hours_notice" in r1.actions
    assert test_config["after_hours_message"] in r1.reply_text
    r2 = engine.handle("test-biz", "+923005556666", text="shukriya")
    assert "after_hours_notice" not in r2.actions
    assert test_config["after_hours_message"] not in r2.reply_text


def test_after_hours_notice_appended(engine, test_config, tmp_path, db_path):
    # Sunday 2026-09-27 is closed in the test config; now is Sunday 13:40.
    r = engine.handle("test-biz", "+923001234567", text="parking available hai?")
    assert "after_hours_notice" in r.actions
    assert test_config["after_hours_message"] in r.reply_text

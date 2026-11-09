"""Hostile self-review: garbage inputs, dead API keys, broken signatures.

Every case must degrade gracefully — clear error states, no crashes, no
stack traces to the user. All network dependencies are mocked.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import whatsapp
from app.engine import Engine
from app.main import app


# ------------------------------------------------------- garbage payloads

@pytest.mark.parametrize("payload", [
    {},
    {"entry": None},
    {"entry": [{"changes": None}]},
    {"entry": [{"changes": [{"value": None}]}]},
    {"entry": [{"changes": [{"value": {"messages": "not-a-list"}}]}]},
    {"entry": [{"changes": [{"value": {"messages": [
        {"from": "123", "id": "x"}  # no type at all
    ]}}]}]},
    {"entry": [{"changes": [{"value": {"messages": [
        {"from": "123", "id": "x", "type": "sticker",
         "sticker": {"id": "s1"}}  # unsupported type
    ]}}]}]},
    None,
])
def test_parse_garbage_never_raises(payload):
    assert whatsapp.parse_webhook_payload(payload or {}) == []


def test_webhook_post_garbage_json_returns_200(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    with TestClient(app) as client:
        r = client.post("/webhook", content=b"{not json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_webhook_post_empty_body_returns_200(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    with TestClient(app) as client:
        r = client.post("/webhook", content=b"")
        assert r.status_code == 200


# ------------------------------------------------------- signatures

def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_bad_signature_rejected(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "s3cret")
    body = json.dumps({"entry": []}).encode()
    with TestClient(app) as client:
        r = client.post("/webhook", content=body,
                        headers={"X-Hub-Signature-256": "sha256=wrong"})
        assert r.status_code == 403


def test_webhook_good_signature_accepted(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "s3cret")
    body = json.dumps({"entry": []}).encode()
    with TestClient(app) as client:
        r = client.post("/webhook", content=body,
                        headers={"X-Hub-Signature-256": _sig("s3cret", body)})
        assert r.status_code == 200


def test_webhook_no_secret_dev_mode_accepted(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    with TestClient(app) as client:
        r = client.post("/webhook", json={"entry": []})
        assert r.status_code == 200


# ------------------------------------------------------- invalid bookings

@pytest.mark.parametrize("text", [
    "book blah blah blah",
    "kal",                       # day but no time -> asks for time
    "zzzzzz qwerty",
    "5",                         # bare number, no context
    "appointment",               # intent, no datetime
])
def test_invalid_booking_requests_degrade(engine, text):
    r = engine.handle("test-biz", "+923001234567", text=text)
    assert r.reply_text and len(r.reply_text) > 5  # never empty, never crash


def test_booking_far_past_time_asks_again(engine):
    # "aaj subah 5 baje" is in the past relative to FIXED_NOW (Sun 13:40).
    r = engine.handle("test-biz", "+923001234567", text="aaj subah 5 baje")
    assert r.reply_text  # graceful: slot unavailable / clarify path
    assert "booking_created_pending" not in r.actions


# ------------------------------------------------------- dead API keys

def test_dead_transcriber_gives_voice_fallback(db_path, test_config, tmp_path):
    def dead_transcriber(audio: bytes, hint: str) -> str:
        raise RuntimeError("401 invalid api key")

    eng = Engine(db_path, {"test-biz": test_config},
                 transcriber=dead_transcriber,
                 tts_cache_dir=tmp_path / "tts")
    r = eng.handle("test-biz", "+923001234567", audio_bytes=b"corrupt")
    assert "stt_failed" in r.actions
    assert r.reply_text  # asks user to send text instead
    assert r.reply_audio is None


def test_dead_llm_gives_busy_template(db_path, test_config, tmp_path):
    def dead_llm(messages):
        raise RuntimeError("401 invalid api key")

    eng = Engine(db_path, {"test-biz": test_config}, llm_chat=dead_llm,
                 tts_cache_dir=tmp_path / "tts")
    r = eng.handle("test-biz", "+923001234567", text="parking available hai?")
    assert "llm_failed" in r.actions
    assert r.reply_text  # polite templated fallback


def test_dead_tts_falls_back_to_text(db_path, test_config, tmp_path):
    def dead_tts(text: str, voice: str) -> bytes:
        raise RuntimeError("edge-tts network down")

    eng = Engine(db_path, {"test-biz": test_config}, tts_fn=dead_tts,
                 tts_cache_dir=tmp_path / "tts")
    # audio path degrades to a text reply when TTS is down
    def ok_transcriber(audio: bytes, hint: str) -> str:
        return "salam"
    eng2 = Engine(db_path, {"test-biz": test_config},
                  transcriber=ok_transcriber, tts_fn=dead_tts,
                  tts_cache_dir=tmp_path / "tts")
    r = eng2.handle("test-biz", "+923001234567", audio_bytes=b"xyz")
    assert "tts_failed" in r.actions
    assert r.reply_text and r.reply_audio is None


# ------------------------------------------------------- bad dashboard inputs

def test_conversation_404_not_500():
    with TestClient(app) as client:
        r = client.get("/conversations/999999?business=smilecare-dental")
        assert r.status_code == 404


def test_settings_rejects_garbage_json():
    with TestClient(app) as client:
        r = client.post("/settings",
                        data={"business": "new", "config_json": "{oops"})
        assert r.status_code == 400
        assert "Invalid config" in r.text
        assert "Traceback" not in r.text


def test_settings_rejects_missing_service_field():
    from tests.conftest import make_test_config
    cfg = make_test_config()
    cfg["services"] = [{"name": "X"}]  # missing price/duration
    with TestClient(app) as client:
        r = client.post("/settings",
                        data={"business": "new",
                              "config_json": json.dumps(cfg)})
        assert r.status_code == 400
        assert "duration_min" in r.text or "price_pkr" in r.text

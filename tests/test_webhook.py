"""Webhook verification + inbound payload parsing. No network calls."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import whatsapp
from app.main import app

TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "111",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "923001234567",
                             "phone_number_id": "PNID123"},
                "contacts": [{"profile": {"name": "Ali Raza"},
                              "wa_id": "923001234567"}],
                "messages": [{
                    "from": "923001234567",
                    "id": "wamid.text1",
                    "timestamp": "1727445600",
                    "type": "text",
                    "text": {"body": "Salam, kal 5 baje appointment chahiye"},
                }],
            },
        }],
    }],
}

AUDIO_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "111",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "923001234567",
                             "phone_number_id": "PNID123"},
                "contacts": [{"profile": {"name": "Ali"},
                              "wa_id": "923009876543"}],
                "messages": [{
                    "from": "923009876543",
                    "id": "wamid.audio1",
                    "timestamp": "1727445601",
                    "type": "audio",
                    "audio": {"mime_type": "audio/ogg; codecs=opus",
                              "id": "MEDIA123"},
                }],
            },
        }],
    }],
}

STATUS_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "111",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": "PNID123"},
                "statuses": [{"id": "wamid.x", "status": "delivered",
                              "recipient_id": "923001234567"}],
            },
        }],
    }],
}


def test_parse_text_message():
    msgs = whatsapp.parse_webhook_payload(TEXT_PAYLOAD)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.sender_wa_id == "923001234567"
    assert m.message_id == "wamid.text1"
    assert m.kind == "text"
    assert m.text == "Salam, kal 5 baje appointment chahiye"
    assert m.phone_number_id == "PNID123"
    assert m.profile_name == "Ali Raza"


def test_parse_audio_message():
    msgs = whatsapp.parse_webhook_payload(AUDIO_PAYLOAD)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.kind == "audio"
    assert m.audio_media_id == "MEDIA123"
    assert m.text is None


def test_statuses_are_ignored():
    assert whatsapp.parse_webhook_payload(STATUS_PAYLOAD) == []


def test_parse_empty_payload():
    assert whatsapp.parse_webhook_payload({}) == []


def test_webhook_verify_ok(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "secret123")
    client = TestClient(app)
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "secret123",
        "hub.challenge": "CHALLENGE-ABC",
    })
    assert r.status_code == 200
    assert r.text == "CHALLENGE-ABC"


def test_webhook_verify_wrong_token(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "secret123")
    client = TestClient(app)
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong",
        "hub.challenge": "CHALLENGE-ABC",
    })
    assert r.status_code == 403


def test_webhook_verify_missing_env(monkeypatch):
    monkeypatch.delenv("WHATSAPP_VERIFY_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "anything",
        "hub.challenge": "CHALLENGE-ABC",
    })
    assert r.status_code == 403

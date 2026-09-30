"""WhatsApp Cloud API layer.

- parse_webhook_payload: clean extraction of inbound messages from Meta's
  webhook JSON (text + audio voice notes; statuses/echoes ignored).
- download_media: fetch voice-note bytes via the Graph API.
- send_text / send_audio: outbound messaging (media upload + send).

Tokens are read from environment variables at call time, never stored.
In tests, pass explicit arguments / mock httpx.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

GRAPH_BASE = "https://graph.facebook.com"


@dataclass
class InboundMessage:
    sender_wa_id: str
    message_id: str
    kind: str                      # 'text' | 'audio'
    text: str | None = None        # for kind == 'text'
    audio_media_id: str | None = None  # for kind == 'audio'
    timestamp: str | None = None
    phone_number_id: str | None = None  # which business number received it
    profile_name: str | None = None


def parse_webhook_payload(payload: dict) -> list[InboundMessage]:
    """Extract inbound user messages. Returns [] for statuses/delivery receipts.

    Defensive: Meta occasionally sends unexpected shapes; malformed entries
    are skipped, never raised.
    """
    out: list[InboundMessage] = []
    if not isinstance(payload, dict):
        return out
    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes") or []
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            if "statuses" in value and "messages" not in value:
                continue  # delivery receipts / read receipts
            metadata = value.get("metadata") or {}
            pnid = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            contacts_raw = value.get("contacts") or []
            contacts = {}
            if isinstance(contacts_raw, list):
                contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name")
                            for c in contacts_raw if isinstance(c, dict)}
            messages = value.get("messages") or []
            if not isinstance(messages, list):
                continue
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
                if mtype == "text":
                    out.append(InboundMessage(
                        sender_wa_id=msg.get("from", ""),
                        message_id=msg.get("id", ""),
                        kind="text",
                        text=(msg.get("text", {}) or {}).get("body", ""),
                        timestamp=msg.get("timestamp"),
                        phone_number_id=pnid,
                        profile_name=contacts.get(msg.get("from")),
                    ))
                elif mtype == "audio":
                    out.append(InboundMessage(
                        sender_wa_id=msg.get("from", ""),
                        message_id=msg.get("id", ""),
                        kind="audio",
                        audio_media_id=(msg.get("audio", {}) or {}).get("id"),
                        timestamp=msg.get("timestamp"),
                        phone_number_id=pnid,
                        profile_name=contacts.get(msg.get("from")),
                    ))
                # other types (image, sticker, reaction, ...) are ignored
    return [m for m in out if m.sender_wa_id]


def _env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"{name} is not set. See .env.example.")
    return val


def _api_version() -> str:
    return os.environ.get("WHATSAPP_API_VERSION", "v21.0").strip() or "v21.0"


def download_media(media_id: str, token: str | None = None,
                   phone_number_id: str | None = None,
                   client: httpx.Client | None = None) -> bytes:
    """Download media bytes for a WhatsApp media id. Returns raw bytes."""
    token = token or _env("WHATSAPP_TOKEN")
    version = _api_version()
    own_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        r = client.get(f"{GRAPH_BASE}/{version}/{media_id}",
                       headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        url = r.json().get("url")
        if not url:
            raise RuntimeError("Graph API returned no media url")
        d = client.get(url, headers={"Authorization": f"Bearer {token}"})
        d.raise_for_status()
        return d.content
    finally:
        if own_client:
            client.close()


def upload_media(audio_bytes: bytes, mime_type: str = "audio/ogg",
                 token: str | None = None, phone_number_id: str | None = None,
                 client: httpx.Client | None = None) -> str:
    """Upload audio bytes to WhatsApp; returns the media id."""
    token = token or _env("WHATSAPP_TOKEN")
    pnid = phone_number_id or _env("WHATSAPP_PHONE_NUMBER_ID")
    version = _api_version()
    own_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        r = client.post(
            f"{GRAPH_BASE}/{version}/{pnid}/media",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("reply.ogg", audio_bytes, mime_type)},
            data={"messaging_product": "whatsapp"},
        )
        r.raise_for_status()
        media_id = r.json().get("id")
        if not media_id:
            raise RuntimeError("Graph API returned no media id on upload")
        return media_id
    finally:
        if own_client:
            client.close()


def send_text(to: str, body: str, token: str | None = None,
              phone_number_id: str | None = None,
              client: httpx.Client | None = None) -> dict:
    token = token or _env("WHATSAPP_TOKEN")
    pnid = phone_number_id or _env("WHATSAPP_PHONE_NUMBER_ID")
    version = _api_version()
    own_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.post(
            f"{GRAPH_BASE}/{version}/{pnid}/messages",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": to,
                  "type": "text", "text": {"body": body}},
        )
        r.raise_for_status()
        return r.json()
    finally:
        if own_client:
            client.close()


def send_audio(to: str, audio_bytes: bytes, token: str | None = None,
               phone_number_id: str | None = None,
               client: httpx.Client | None = None) -> dict:
    """Upload MP3/OGG bytes then send as a WhatsApp audio (voice-note style)."""
    token = token or _env("WHATSAPP_TOKEN")
    pnid = phone_number_id or _env("WHATSAPP_PHONE_NUMBER_ID")
    media_id = upload_media(audio_bytes, "audio/mpeg", token, pnid, client)
    version = _api_version()
    own_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.post(
            f"{GRAPH_BASE}/{version}/{pnid}/messages",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": to,
                  "type": "audio", "audio": {"id": media_id}},
        )
        r.raise_for_status()
        return r.json()
    finally:
        if own_client:
            client.close()

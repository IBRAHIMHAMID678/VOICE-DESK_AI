"""Interactive Live Demo Routes for Voice Receptionist.

Provides:
- GET /demo: Interactive responsive web UI (mobile & desktop)
- POST /api/demo/session: Ingests 30s voice sample + business profile
- POST /api/demo/chat: Fast REST conversation endpoint
- WebSocket /ws/live-call/{session_id}: Real-time full-duplex live call room
- POST /api/demo/export-whatsapp: One-click export to WhatsApp bot config
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import llm_service
from app import voice_service

log = logging.getLogger("demo_routes")

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BUSINESSES_DIR = Path(__file__).resolve().parent.parent / "businesses"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory session store: session_id -> {profile, reference_audio_b64, history}
SESSIONS: dict[str, dict] = {}


@router.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    """Render the responsive live voice agent demo page."""
    return templates.TemplateResponse(request, "live_demo.html", {})


@router.post("/api/demo/session")
async def create_demo_session(
    business_name: str = Form(...),
    category: str = Form("General Business"),
    location: str = Form("Lahore, Pakistan"),
    hours: str = Form("11:00 AM - 9:00 PM"),
    services_json: str = Form("[]"),
    voice_file: UploadFile | None = File(None),
):
    """Initialize a live demo session with business info and optional 30s voice sample."""
    session_id = str(uuid.uuid4())[:8]

    try:
        services = json.loads(services_json)
    except Exception:
        services = [
            {"name": "Consultation", "price_pkr": 1500, "duration_min": 30}
        ]

    profile = {
        "id": f"demo-{session_id}",
        "name": business_name.strip(),
        "category": category.strip(),
        "location": location.strip(),
        "hours": hours.strip(),
        "services": services,
        "receptionist_name": "Ayesha",
    }

    reference_bytes = None
    if voice_file:
        raw_content = await voice_file.read()
        if len(raw_content) > 1000:
            reference_bytes = voice_service.sanitize_audio_to_mp3(raw_content)
            log.info("Sanitized reference audio for session %s (%d bytes -> %d bytes)", session_id, len(raw_content), len(reference_bytes))

    SESSIONS[session_id] = {
        "profile": profile,
        "reference_bytes": reference_bytes,
        "history": [],
    }

    # Generate initial dynamic personalized greeting
    welcome_roman, welcome_urdu = await llm_service.generate_dynamic_greeting(profile)

    audio_bytes = await voice_service.synthesize_speech(
        welcome_urdu,
        reference_audio_bytes=reference_bytes,
        reference_text="سلام! ہماری کلینک لاہور میں ہے۔ ہم چیک اپ اور اسکیلنگ کی سہولت دیتے ہیں۔",
    )
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""

    SESSIONS[session_id]["history"].append({"role": "assistant", "content": welcome_roman})

    return {
        "session_id": session_id,
        "welcome_text": welcome_roman,
        "welcome_audio_b64": audio_b64,
        "has_custom_voice": bool(reference_bytes),
    }


@router.post("/api/demo/chat")
async def demo_chat(
    session_id: str = Form(...),
    user_text: str = Form(...),
):
    """Fast turn-based endpoint for testing speech text and audio."""
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session expired or not found")

    user_text = user_text.strip()
    if not user_text:
        return {"reply_text": "", "audio_b64": ""}

    session["history"].append({"role": "user", "content": user_text})

    # Keep last 8 turns for conversational context
    context = session["history"][-8:]
    reply_roman, reply_urdu = await llm_service.generate_response(context, session["profile"])
    session["history"].append({"role": "assistant", "content": reply_roman})

    audio_bytes = await voice_service.synthesize_speech(
        reply_urdu,
        reference_audio_bytes=session.get("reference_bytes"),
    )
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""

    return {
        "reply_text": reply_roman,
        "audio_b64": audio_b64,
    }


@router.websocket("/ws/live-call/{session_id}")
async def live_call_websocket(websocket: WebSocket, session_id: str):
    """Live full-duplex phone call over WebSocket with interruption support."""
    await websocket.accept()
    session = SESSIONS.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close()
        return

    log.info("WebSocket live call connected for session %s", session_id)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "user_speech":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue

                await websocket.send_json({"type": "state", "status": "thinking"})
                session["history"].append({"role": "user", "content": user_text})

                # Generate reply
                context = session["history"][-8:]
                reply_roman, reply_urdu = await llm_service.generate_response(context, session["profile"])
                session["history"].append({"role": "assistant", "content": reply_roman})

                await websocket.send_json({
                    "type": "state",
                    "status": "speaking",
                    "text": reply_roman,
                })

                # Synthesize cloned audio using native Urdu phonemes
                audio_bytes = await voice_service.synthesize_speech(
                    reply_urdu,
                    reference_audio_bytes=session.get("reference_bytes"),
                )
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""

                await websocket.send_json({
                    "type": "audio_chunk",
                    "text": reply_roman,
                    "audio_b64": audio_b64,
                })

            elif msg_type == "interruption":
                # Caller interrupted while AI was speaking; acknowledge immediately
                await websocket.send_json({"type": "stop_audio"})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        log.info("Live call disconnected for session %s", session_id)
    except Exception as e:
        log.warning("WebSocket error in session %s: %s", session_id, e)


@router.post("/api/demo/export-whatsapp")
async def export_to_whatsapp(session_id: str = Form(...)):
    """Convert demo profile into permanent businesses/<id>.json file."""
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    p = session["profile"]
    business_id = p["id"]
    filepath = BUSINESSES_DIR / f"{business_id}.json"

    export_data = {
        "id": business_id,
        "name": p["name"],
        "city": p["location"],
        "default_language": "roman_urdu",
        "services": [
            {
                "name": s["name"],
                "price_pkr": s.get("price_pkr", 1500),
                "duration_min": s.get("duration_min", 30),
                "keywords": [w.lower() for w in s["name"].split()],
            }
            for s in p["services"]
        ],
        "hours": {
            "mon": {"open": "11:00", "close": "21:00"},
            "tue": {"open": "11:00", "close": "21:00"},
            "wed": {"open": "11:00", "close": "21:00"},
            "thu": {"open": "11:00", "close": "21:00"},
            "fri": {"open": "14:00", "close": "21:00"},
            "sat": {"open": "11:00", "close": "21:00"},
            "sun": "closed",
        },
        "location": p["location"],
        "faqs": [
            {
                "q": "Appointment kaise book karein?",
                "a": "Bas humein yahan WhatsApp par apna pasandeeda din aur waqt batayein.",
            }
        ],
        "booking": {
            "slot_minutes": 30,
            "max_advance_days": 14,
            "require_name_phone": True,
        },
        "after_hours_message": "Hamara clinic is waqt band hai. Kal subah 11 baje open hoga.",
        "owner_phone": "+923001234567",
        "tts_voice": "ur-PK-UzmaNeural",
    }

    filepath.write_text(json.dumps(export_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "success", "file": str(filepath.name), "business_id": business_id}

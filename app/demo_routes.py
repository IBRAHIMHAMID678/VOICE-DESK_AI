"""Dedicated Voice Agent Platform & Receipt Generation Routes.

Features:
- GET /demo: Production-grade Voice Agent Studio & Live Call interface
- POST /api/demo/session: Configures custom agent (name, business description, voice cloning/presets, zero-hallucination fallback rules)
- POST /api/demo/chat: Turn-based conversational endpoint with automated physical receipt generation
- WebSocket /ws/live-call/{session_id}: Full-duplex live audio call room with barge-in interruption
- POST /api/demo/receipt/generate: Physical paper-style receipt generator (PNG & structured doc)
- POST /api/demo/receipt/ocr: Multimodal OCR receipt verification inspector
- GET /api/demo/receipt/sample: Pre-rendered sample receipts for instant testing
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import llm_service
from app import voice_service
from app import receipt_service
from app import ocr_service

log = logging.getLogger("demo_routes")

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BUSINESSES_DIR = Path(__file__).resolve().parent.parent / "businesses"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory session store: session_id -> {profile, reference_bytes, reference_text, history, receipts}
SESSIONS: dict[str, dict] = {}


@router.get("/demo", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def demo_page(request: Request):
    """Render the dedicated Voice Agent Studio platform page."""
    return templates.TemplateResponse(request, "live_demo.html", {})


def _normalize_confirmed_items(items, business_services):
    """Ensure items list contains proper dicts with price_pkr mapped from business services."""
    services = business_services or []
    price_map = {}
    for s in services:
        if isinstance(s, dict):
            s_name = s.get("name", "").strip().lower()
            price_map[s_name] = int(s.get("price_pkr", 0))

    default_price = services[0].get("price_pkr", 1500) if services and isinstance(services[0], dict) else 1500

    normalized = []
    raw_list = items if (items and len(items) > 0) else services[:2]
    for it in raw_list:
        if isinstance(it, str):
            clean_name = it.strip()
            # Try exact match or substring in service names
            pkr = price_map.get(clean_name.lower())
            if pkr is None:
                for k, v in price_map.items():
                    if k in clean_name.lower() or clean_name.lower() in k:
                        pkr = v
                        break
            if pkr is None:
                pkr = default_price
            normalized.append({"name": clean_name, "qty": 1, "price_pkr": pkr})
        elif isinstance(it, dict):
            name = str(it.get("name") or it.get("item") or "Service Item")
            qty = int(it.get("qty", 1))
            pkr = it.get("price_pkr")
            if pkr is None:
                pkr = price_map.get(name.strip().lower(), default_price)
            normalized.append({"name": name, "qty": qty, "price_pkr": int(pkr)})

    return normalized or [{"name": "Appointment / Service", "qty": 1, "price_pkr": default_price}]


@router.post("/api/demo/session")
async def create_demo_session(
    agent_name: str = Form("Zoya"),
    business_name: str = Form("Apex Services"),
    category: str = Form("Consulting & Services"),
    description: str = Form("Professional client service and consultations."),
    location: str = Form("Lahore, Pakistan"),
    hours: str = Form("10:00 AM se 9:00 PM (Monday - Saturday)"),
    services_json: str = Form("[]"),
    fallback_response: str = Form("Main is baare mein abhi confirm nahi bata sakti ji, main management se pooch kar aap ko update karti hoon."),
    tone: str = Form("warm_punjabi"),
    voice_mode: str = Form("preset"),
    preset_voice: str = Form("ur-PK-UzmaNeural"),
    voice_speed: float = Form(1.0),
    voice_file: UploadFile | None = File(None),
):
    """Initialize a dedicated custom voice agent session."""
    session_id = str(uuid.uuid4())[:8]

    try:
        services = json.loads(services_json)
    except Exception:
        services = [{"name": "Consultation", "price_pkr": 1500, "duration_min": 30}]

    profile = {
        "id": f"agent-{session_id}",
        "agent_name": agent_name.strip() or "Representative",
        "name": business_name.strip(),
        "category": category.strip(),
        "description": description.strip(),
        "location": location.strip(),
        "hours": hours.strip(),
        "services": services,
        "fallback_response": fallback_response.strip(),
        "tone": tone,
        "voice_mode": voice_mode,
        "preset_voice": preset_voice,
        "voice_speed": float(voice_speed),
    }

    reference_bytes = None
    reference_text = None

    if voice_file and voice_mode == "clone":
        raw_content = await voice_file.read()
        if len(raw_content) > 1000:
            reference_bytes = voice_service.sanitize_audio_to_mp3(raw_content)
            # Transcribe the user's reference speech with Groq Whisper for 100% accurate alignment
            reference_text = await voice_service.transcribe_reference_audio(reference_bytes)
            log.info(
                "Voice sample ingested for session %s (%d bytes -> %d bytes, transcript: %s)",
                session_id,
                len(raw_content),
                len(reference_bytes),
                reference_text[:40],
            )

    SESSIONS[session_id] = {
        "profile": profile,
        "reference_bytes": reference_bytes,
        "reference_text": reference_text,
        "history": [],
        "receipts": [],
    }

    # Generate personalized dynamic greeting
    welcome_roman, welcome_urdu = await llm_service.generate_dynamic_greeting(profile)

    # Synthesize opening greeting
    audio_bytes = await voice_service.synthesize_speech(
        text=welcome_urdu,
        reference_audio_bytes=reference_bytes,
        reference_text=reference_text,
        fallback_voice=preset_voice,
        speed=voice_speed,
    )
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""

    SESSIONS[session_id]["history"].append({"role": "assistant", "content": welcome_roman})

    return {
        "session_id": session_id,
        "agent_name": profile["agent_name"],
        "welcome_text": welcome_roman,
        "welcome_audio_b64": audio_b64,
        "has_custom_voice": bool(reference_bytes),
        "voice_mode": voice_mode,
        "voice_label": "Zero-Shot Cloned Voice" if reference_bytes else f"Studio {preset_voice}",
    }


@router.post("/api/demo/chat")
async def demo_chat(
    session_id: str = Form(...),
    user_text: str = Form(...),
):
    """Turn-based conversational chat with automatic physical receipt generation."""
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session expired or not found")

    user_text = user_text.strip()
    if not user_text:
        return {"reply_text": "", "audio_b64": "", "receipt": None}

    session["history"].append({"role": "user", "content": user_text})

    # Context history
    context = session["history"][-8:]
    p = session["profile"]
    reply_roman, reply_urdu, meta = await llm_service.generate_response(context, p)
    session["history"].append({"role": "assistant", "content": reply_roman})

    # Synthesize speech
    audio_bytes = await voice_service.synthesize_speech(
        text=reply_urdu,
        reference_audio_bytes=session.get("reference_bytes"),
        reference_text=session.get("reference_text"),
        fallback_voice=p.get("preset_voice", "ur-PK-UzmaNeural"),
        speed=p.get("voice_speed", 1.0),
    )
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""

    # Receipt generation if order/booking was confirmed
    receipt_data = None
    receipt_b64 = ""
    if meta.get("booking_confirmed"):
        items = _normalize_confirmed_items(meta.get("confirmed_items"), p.get("services", []))
        receipt_dict = {
            "business_name": p["name"],
            "category": p["category"],
            "location": p["location"],
            "agent_name": p["agent_name"],
            "customer_name": "Caller",
            "items": items,
            "status": "BOOKING CONFIRMED",
        }
        receipt_b64 = receipt_service.receipt_to_base64(receipt_dict)
        receipt_data = receipt_dict
        session["receipts"].append(receipt_dict)

    return {
        "reply_text": reply_roman,
        "audio_b64": audio_b64,
        "receipt_b64": receipt_b64,
        "receipt_data": receipt_data,
        "metadata": meta,
    }


@router.websocket("/ws/live-call/{session_id}")
async def live_call_websocket(websocket: WebSocket, session_id: str):
    """Full-duplex phone call over WebSocket with continuous multi-turn voice and physical receipts."""
    await websocket.accept()
    session = SESSIONS.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close()
        return

    p = session["profile"]
    log.info("WebSocket live call connected for agent '%s' (session %s)", p["agent_name"], session_id)

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

                # Keep last 8 turns for context
                context = session["history"][-8:]
                reply_roman, reply_urdu, meta = await llm_service.generate_response(context, p)
                session["history"].append({"role": "assistant", "content": reply_roman})

                await websocket.send_json({
                    "type": "state",
                    "status": "speaking",
                    "text": reply_roman,
                })

                # Synthesize audio (guaranteed non-empty via resilient fallback)
                audio_bytes = await voice_service.synthesize_speech(
                    text=reply_urdu,
                    reference_audio_bytes=session.get("reference_bytes"),
                    reference_text=session.get("reference_text"),
                    fallback_voice=p.get("preset_voice", "ur-PK-UzmaNeural"),
                    speed=p.get("voice_speed", 1.0),
                )
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""

                await websocket.send_json({
                    "type": "audio_chunk",
                    "text": reply_roman,
                    "audio_b64": audio_b64,
                })

                # Check if booking / order was confirmed
                if meta.get("booking_confirmed"):
                    items = _normalize_confirmed_items(meta.get("confirmed_items"), p.get("services", []))
                    receipt_dict = {
                        "business_name": p["name"],
                        "category": p["category"],
                        "location": p["location"],
                        "agent_name": p["agent_name"],
                        "customer_name": "Customer",
                        "items": items,
                        "status": "BOOKING CONFIRMED",
                    }
                    r_b64 = receipt_service.receipt_to_base64(receipt_dict)
                    session["receipts"].append(receipt_dict)

                    await websocket.send_json({
                        "type": "receipt_generated",
                        "receipt_b64": r_b64,
                        "receipt_data": receipt_dict,
                    })

            elif msg_type == "interruption":
                await websocket.send_json({"type": "stop_audio"})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        log.info("Live call disconnected for session %s", session_id)
    except Exception as e:
        log.warning("WebSocket error in session %s: %s", session_id, e)


@router.post("/api/demo/receipt/generate")
async def generate_receipt_endpoint(request: Request):
    """Generate physical paper receipt from JSON payload."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    receipt_dict = {
        "business_name": body.get("business_name", "Lahore Biryani & Grill"),
        "category": body.get("category", "Restaurant & Dining"),
        "location": body.get("location", "Gulberg III, Lahore"),
        "phone": body.get("phone", "+92 42 35789123"),
        "agent_name": body.get("agent_name", "Zoya"),
        "customer_name": body.get("customer_name", "Walk-in Guest"),
        "customer_phone": body.get("customer_phone", "0300-1234567"),
        "booking_time": body.get("booking_time", "Today, 8:00 PM"),
        "items": body.get("items", [
            {"name": "Special Service Order", "qty": 1, "price_pkr": 1500}
        ]),
        "status": body.get("status", "CONFIRMED"),
    }

    raw_png = receipt_service.generate_physical_receipt_image(receipt_dict)
    r_b64 = base64.b64encode(raw_png).decode("utf-8")

    return {
        "status": "success",
        "receipt_b64": r_b64,
        "receipt_data": receipt_dict,
    }


@router.post("/api/demo/receipt/ocr")
async def ocr_receipt_endpoint(
    image_file: UploadFile | None = File(None),
    raw_text: str = Form(""),
):
    """OCR Document inspector endpoint for receipts and invoices."""
    if image_file:
        content = await image_file.read()
        if len(content) > 100:
            result = await ocr_service.parse_receipt_image(content)
            return {"status": "success", "extracted_data": result}

    if raw_text:
        result = await ocr_service.parse_receipt_text_to_json(raw_text)
        return {"status": "success", "extracted_data": result}

    return {"status": "error", "message": "No image or text provided for OCR"}


@router.get("/api/demo/receipt/sample")
async def get_sample_receipt():
    """Provides a ready-to-inspect physical paper receipt."""
    sample = {
        "business_name": "Lahore Biryani House",
        "category": "Restaurant & Dining",
        "location": "Gulberg, Lahore",
        "phone": "+92 42 35789123",
        "agent_name": "Tariq",
        "customer_name": "Usman Malik",
        "customer_phone": "0321-9876543",
        "booking_time": "Today, 8:30 PM (Dine-in)",
        "items": [
            {"name": "Special Chicken Biryani", "qty": 2, "price_pkr": 750},
            {"name": "Chicken Karahi (Half)", "qty": 1, "price_pkr": 1850},
            {"name": "Fresh Roghni Naan", "qty": 4, "price_pkr": 120},
            {"name": "Raita & Fresh Salad", "qty": 2, "price_pkr": 150}
        ],
        "status": "PAID"
    }
    raw_png = receipt_service.generate_physical_receipt_image(sample)
    return Response(content=raw_png, media_type="image/png")

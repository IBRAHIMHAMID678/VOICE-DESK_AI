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

# In-memory session store: session_id -> {profile, reference_bytes, reference_text, history, receipts, tools}
SESSIONS: dict[str, dict] = {}

TOOLS_CATALOG = [
    {
        "id": "tool-receipt",
        "name": "Thermal Paper Receipt & Invoice Generator",
        "category": "Billing & Proof",
        "icon": "🧾",
        "badge": "Active Core",
        "description": "Automatically computes 5% GST, itemizes PKR charges, and renders downloadable physical thermal paper receipts with barcode verification.",
        "connected": True,
        "parameters": ["business_name", "items", "gst_rate", "stamp_type"],
        "sample_output": {
            "status": "GENERATED",
            "receipt_no": "REC-94182",
            "format": "PNG (460x680 thermal)",
            "verification": "BARCODE_STAMPED",
            "items_count": 2,
            "total_pkr": 5775
        }
    },
    {
        "id": "tool-ocr",
        "name": "Multimodal OCR Document Inspector",
        "category": "Vision & Verification",
        "icon": "🔍",
        "badge": "Active Core",
        "description": "Scans customer payment slips, clinic prescriptions, and handwritten invoices, extracting structured line items and payment totals.",
        "connected": True,
        "parameters": ["image_bytes", "extraction_schema"],
        "sample_output": {
            "status": "VERIFIED",
            "extracted_items": 2,
            "total_pkr": 5500,
            "confidence": 0.98,
            "schema_valid": True
        }
    },
    {
        "id": "tool-calendar",
        "name": "Smart Slot & Appointment Booking",
        "category": "Scheduling",
        "icon": "📅",
        "badge": "Demo Connected",
        "description": "Synchronizes doctor, salon, and consultant slots in real time. Automatically checks conflicting intervals and reserves slots.",
        "connected": True,
        "parameters": ["date", "time_slot", "service_id", "patient_name"],
        "sample_output": {
            "booking_id": "APT-4421",
            "slot": "Tomorrow, 5:00 PM",
            "doctor": "Dr. Bilal (Dental Specialist)",
            "calendar_sync": "SYNCED_MOCK",
            "sms_reminder_queued": True
        }
    },
    {
        "id": "tool-crm",
        "name": "Customer CRM & Lead Profiler",
        "category": "Sales & CRM",
        "icon": "👥",
        "badge": "Demo Connected",
        "description": "Captures caller phone number, name, inquiry interest, classifies lead urgency (Hot/Warm/Cold), and stores interaction timeline.",
        "connected": True,
        "parameters": ["caller_phone", "lead_sentiment", "intent", "notes"],
        "sample_output": {
            "lead_id": "LEAD-8832",
            "customer_name": "Usman Malik",
            "phone": "0300-8849123",
            "status": "HOT_LEAD",
            "interest": "Laser Teeth Whitening Consultation",
            "priority": "HIGH"
        }
    },
    {
        "id": "tool-kds",
        "name": "Kitchen Display & Order Dispatch (KDS)",
        "category": "Restaurant & Retail",
        "icon": "🍳",
        "badge": "Demo Ready",
        "description": "Routes itemized food orders directly to kitchen preparation queues with prep time estimates and pickup token numbers.",
        "connected": False,
        "parameters": ["table_or_delivery", "line_items", "special_instructions"],
        "sample_output": {
            "order_token": "TKN-419",
            "prep_time_est": "18 mins",
            "kds_queue": "STATION_GRILL_1",
            "items_queued": ["Chicken Karahi (Half)", "Roghni Naan x4"]
        }
    },
    {
        "id": "tool-whatsapp",
        "name": "WhatsApp & SMS Auto-Dispatcher",
        "category": "Messaging",
        "icon": "💬",
        "badge": "Demo Connected",
        "description": "Dispatches instant WhatsApp confirmation messages with digital receipt PDFs and Google Maps location pins upon call hangup.",
        "connected": True,
        "parameters": ["recipient_number", "template", "media_url"],
        "sample_output": {
            "message_status": "QUEUED_DISPATCH",
            "channel": "WhatsApp Business Cloud API (Simulation)",
            "recipient": "+92 300 1234567",
            "payload": "Appointment Confirmed with MM Alam Road Pin"
        }
    },
    {
        "id": "tool-kb",
        "name": "Semantic Knowledge Base & Policy Engine",
        "category": "Knowledge",
        "icon": "📚",
        "badge": "Demo Ready",
        "description": "Answers complex caller questions about parking, doctor qualifications, insurance panels, and refund guidelines via semantic search.",
        "connected": False,
        "parameters": ["query_vector", "confidence_threshold"],
        "sample_output": {
            "query": "Parking kahan hai?",
            "matched_clause": "Clause 4.2: Free underground valet parking available for clinic visitors",
            "source_doc": "Clinic_Operations_Manual_v2.pdf",
            "relevance": "97.4%"
        }
    },
    {
        "id": "tool-escalation",
        "name": "Emergency & Supervisor Escalation",
        "category": "Support",
        "icon": "🚨",
        "badge": "Demo Ready",
        "description": "Detects customer distress, VIP client accounts, or medical urgency and triggers an instant SMS alert or live transfer to management.",
        "connected": False,
        "parameters": ["trigger_sentiment", "supervisor_phone"],
        "sample_output": {
            "escalation_id": "ESC-102",
            "priority": "HIGH",
            "reason": "Emergency dental toothache reported",
            "alert_sent_to": "+92 321 9998877 (Clinic Medical Director)",
            "status": "DISPATCHED"
        }
    }
]


@router.get("/demo", response_class=HTMLResponse)
@router.get("/app", response_class=HTMLResponse)
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
        "voice_label": "Zero-Shot Cloned Voice (Aiza Anchor)" if reference_bytes else ("Studio Aiza (Lahori)" if preset_voice == "fish-aiza" else f"Studio {preset_voice}"),
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


@router.get("/api/demo/tools")
async def get_tools_endpoint(session_id: str | None = None):
    """Returns the list of available modular business tools and their connection states."""
    session = SESSIONS.get(session_id) if session_id else None
    active_tool_ids = session.get("tools", {"tool-receipt", "tool-ocr", "tool-calendar", "tool-crm", "tool-whatsapp"}) if session else {"tool-receipt", "tool-ocr", "tool-calendar", "tool-crm", "tool-whatsapp"}

    tools = []
    for t in TOOLS_CATALOG:
        t_copy = dict(t)
        t_copy["connected"] = t["id"] in active_tool_ids
        tools.append(t_copy)
    return {"status": "success", "tools": tools}


@router.post("/api/demo/tools/toggle")
async def toggle_tool_endpoint(request: Request):
    """Toggle a modular business tool ON or OFF for an agent session."""
    body = await request.json()
    tool_id = body.get("tool_id")
    connected = body.get("connected", True)
    session_id = body.get("session_id")

    if session_id and session_id in SESSIONS:
        if "tools" not in SESSIONS[session_id]:
            SESSIONS[session_id]["tools"] = {"tool-receipt", "tool-ocr", "tool-calendar", "tool-crm", "tool-whatsapp"}
        if connected:
            SESSIONS[session_id]["tools"].add(tool_id)
        else:
            SESSIONS[session_id]["tools"].discard(tool_id)

    return {
        "status": "success",
        "tool_id": tool_id,
        "connected": connected,
        "message": f"Tool '{tool_id}' is now {'connected' if connected else 'disconnected'}"
    }


@router.post("/api/demo/tools/simulate")
async def simulate_tool_endpoint(request: Request):
    """Simulates an interactive tool execution demonstrating how the agent utilizes the tool."""
    body = await request.json()
    tool_id = body.get("tool_id", "tool-calendar")

    if tool_id == "tool-receipt":
        sample = {
            "business_name": body.get("business_name", "SmileCare Dental Clinic"),
            "category": "Healthcare",
            "agent_name": "Zoya",
            "customer_name": "Usman Khan",
            "items": [
                {"name": "Teeth Scaling & Polishing", "qty": 1, "price_pkr": 4000},
                {"name": "General Dental Consultation", "qty": 1, "price_pkr": 1500}
            ],
            "status": "CONFIRMED"
        }
        png_bytes = receipt_service.generate_physical_receipt_image(sample)
        r_b64 = base64.b64encode(png_bytes).decode("utf-8")
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Thermal Paper Receipt Generator",
            "simulation_result": {
                "action": "RENDER_THERMAL_RECEIPT",
                "receipt_no": "REC-94182",
                "items_count": 2,
                "subtotal_pkr": 5500,
                "gst_pkr": 275,
                "total_pkr": 5775,
                "status": "PRINT_READY",
                "receipt_b64": r_b64
            }
        }

    elif tool_id == "tool-ocr":
        sample_text = "SMILECARE DENTAL CLINIC\nReceipt #: REC-7741\nDate: 07-Nov-2026\nTeeth Scaling: PKR 4,000\nConsultation: PKR 1,500\nTotal: PKR 5,500\nStatus: PAID"
        extracted = await ocr_service.parse_receipt_text_to_json(sample_text)
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Multimodal OCR Document Inspector",
            "simulation_result": {
                "action": "OCR_EXTRACTION",
                "source_type": "THERMAL_SCAN",
                "extracted_data": extracted,
                "verification_status": "VERIFIED"
            }
        }

    elif tool_id == "tool-calendar":
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Smart Slot & Appointment Booking",
            "simulation_result": {
                "action": "RESERVE_APPOINTMENT_SLOT",
                "booking_id": "APT-4421",
                "patient_name": "Usman Khan",
                "doctor": "Dr. Bilal (Dental Aesthetic Specialist)",
                "reserved_slot": "Tomorrow, 5:00 PM (30 mins)",
                "calendar_sync": "SYNCED_TO_GOOGLE_CALENDAR_MOCK",
                "conflict_checked": "NO_CONFLICT",
                "status": "CONFIRMED"
            }
        }

    elif tool_id == "tool-crm":
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Customer CRM & Lead Profiler",
            "simulation_result": {
                "action": "CRM_LEAD_PROFILE",
                "lead_id": "LEAD-8832",
                "customer_name": "Usman Malik",
                "phone": "+92 300 8849123",
                "city": "Lahore (Gulberg)",
                "lead_temperature": "HOT (95/100)",
                "service_interest": "Laser Teeth Whitening Consultation",
                "call_summary": "Caller inquired about Saturday slots and pricing. Responded with verified Rs 12,000 quote.",
                "status": "LEAD_RECORDED"
            }
        }

    elif tool_id == "tool-kds":
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Kitchen Display & Order Dispatch (KDS)",
            "simulation_result": {
                "action": "DISPATCH_TO_KITCHEN",
                "order_token": "TKN-419",
                "station": "STATION_GRILL_1",
                "items": [
                    {"name": "Special Chicken Karahi (Half)", "qty": 1, "prep_time": "15m"},
                    {"name": "Fresh Roghni Naan", "qty": 4, "prep_time": "5m"}
                ],
                "total_prep_est": "18 mins",
                "status": "DISPATCHED_TO_LINE"
            }
        }

    elif tool_id == "tool-whatsapp":
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "WhatsApp & SMS Auto-Dispatcher",
            "simulation_result": {
                "action": "WHATSAPP_AUTO_DISPATCH",
                "dispatch_id": "WA-883109",
                "channel": "WhatsApp Business Cloud API (Simulation)",
                "recipient": "+92 300 1234567",
                "message_body": "Assalam-o-Alaikum Usman! Your booking with SmileCare Dental Clinic is confirmed for Tomorrow at 5:00 PM. Location: MM Alam Road, Gulberg III, Lahore.",
                "attachments": ["Thermal_Receipt_REC94182.pdf", "Clinic_Location_Pin.vcf"],
                "delivery_status": "DELIVERED_SUCCESS"
            }
        }

    elif tool_id == "tool-kb":
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Semantic Knowledge Base & Policy Engine",
            "simulation_result": {
                "action": "SEMANTIC_POLICY_SEARCH",
                "query": "Parking kahan hai aur discount policy kya hai?",
                "matched_clause": "Clause 4.2: Free underground valet parking available for clinic visitors on MM Alam Road. Discounts apply exclusively to senior citizens (10%).",
                "source_doc": "Clinic_Operations_Manual_v2.pdf",
                "similarity_score": "97.4%",
                "status": "GROUNDED_CLAUSE_RETRIEVED"
            }
        }

    elif tool_id == "tool-escalation":
        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": "Emergency & Supervisor Escalation",
            "simulation_result": {
                "action": "TRIGGER_SUPERVISOR_ALERT",
                "escalation_id": "ESC-102",
                "priority_level": "LEVEL_1_URGENT",
                "reason": "Caller reported acute dental pain requiring emergency slot",
                "sms_alert_sent_to": "+92 321 9998877 (Clinic Medical Director)",
                "call_transfer_target": "Desk Ext 104 (On-duty Doctor)",
                "status": "ALERT_DISPATCHED"
            }
        }

    return {"status": "error", "message": f"Unknown tool ID '{tool_id}'"}


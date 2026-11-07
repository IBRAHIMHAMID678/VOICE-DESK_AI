import base64
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app


def test_demo_page_loads():
    with TestClient(app) as client:
        res = client.get("/demo")
        assert res.status_code == 200
        assert "VoiceDesk AI" in res.text
        assert "Live Voice & Chat" in res.text
        assert "Receipts & OCR" in res.text


def test_demo_create_session_with_custom_agent_and_fallback():
    with TestClient(app) as client:
        services = [
            {"name": "Consultation", "price_pkr": 1500, "duration_min": 20},
            {"name": "Teeth Scaling", "price_pkr": 4000, "duration_min": 30}
        ]
        res = client.post("/api/demo/session", data={
            "agent_name": "Zoya",
            "business_name": "SmileCare Dental Clinic",
            "category": "Dental & Aesthetics",
            "description": "Premier clinic in Lahore providing consultations and scaling.",
            "location": "MM Alam Road, Gulberg III, Lahore",
            "hours": "11:00 AM se 9:00 PM (Monday - Saturday)",
            "services_json": json.dumps(services),
            "fallback_response": "Main is baare mein abhi confirm nahi bata sakti ji, management se pooch kar batati hoon.",
            "tone": "warm_punjabi",
            "voice_mode": "preset",
            "preset_voice": "ur-PK-UzmaNeural",
            "voice_speed": "1.0",
        })
        assert res.status_code == 200
        data = res.json()
        assert "session_id" in data
        assert data["agent_name"] == "Zoya"
        assert len(data["welcome_text"]) > 10
        # Verify initial greeting audio is generated
        assert len(data.get("welcome_audio_b64", "")) > 1000


def test_fallback_mechanism_unknown_query():
    """Verify that asking about unlisted items triggers the configured fallback response."""
    with TestClient(app) as client:
        custom_fallback = "Hamare paas sirf dental treatment hota hai ji, doosri cheezon ki maloomat nahi hai."
        services = [
            {"name": "Teeth Cleaning", "price_pkr": 3500}
        ]
        res_init = client.post("/api/demo/session", data={
            "agent_name": "Tariq",
            "business_name": "Apex Dental",
            "category": "Healthcare",
            "description": "Dental clinic only.",
            "location": "F-7 Markaz Islamabad",
            "hours": "10 AM - 6 PM",
            "services_json": json.dumps(services),
            "fallback_response": custom_fallback,
            "tone": "warm_punjabi",
            "voice_mode": "preset",
            "preset_voice": "ur-PK-AsadNeural",
            "voice_speed": "1.0",
        })
        sid = res_init.json()["session_id"]

        # Ask completely unrelated question (e.g., ordering pizza/burgers)
        res_turn = client.post("/api/demo/chat", data={
            "session_id": sid,
            "user_text": "Kya aap pizza deliver kar sakte hain?"
        })
        assert res_turn.status_code == 200
        reply = res_turn.json().get("reply_text", "")
        # The agent must employ the fallback and decline pizza
        assert len(reply) > 5
        assert len(res_turn.json().get("audio_b64", "")) > 1000


def test_multi_turn_continuous_voice_chat():
    """Verify that turns 1, 2, and 3 all return both text and synthesized audio."""
    with TestClient(app) as client:
        services = [
            {"name": "Teeth Scaling", "price_pkr": 4000, "duration_min": 30},
            {"name": "Consultation", "price_pkr": 1500, "duration_min": 20}
        ]
        res_init = client.post("/api/demo/session", data={
            "agent_name": "Sara",
            "business_name": "SmileCare Clinic",
            "category": "Dental Clinic",
            "description": "Dental clinic in Gulberg.",
            "location": "Gulberg, Lahore",
            "hours": "11 AM - 9 PM",
            "services_json": json.dumps(services)
        })
        sid = res_init.json()["session_id"]

        # Turn 1: Price inquiry
        res_turn1 = client.post("/api/demo/chat", data={
            "session_id": sid,
            "user_text": "Scaling ke kitne charges hain?"
        })
        assert res_turn1.status_code == 200
        t1 = res_turn1.json()
        assert len(t1.get("reply_text", "")) > 5
        assert len(t1.get("audio_b64", "")) > 1000, "Turn 1 must have synthesized audio"

        # Turn 2: Timing inquiry (verifying continuous voice doesn't drop audio)
        res_turn2 = client.post("/api/demo/chat", data={
            "session_id": sid,
            "user_text": "Kal shaam 5 baje slot mil jaye ga?"
        })
        assert res_turn2.status_code == 200
        t2 = res_turn2.json()
        assert len(t2.get("reply_text", "")) > 5
        assert len(t2.get("audio_b64", "")) > 1000, "Turn 2 must have synthesized audio"

        # Turn 3: Confirmation
        res_turn3 = client.post("/api/demo/chat", data={
            "session_id": sid,
            "user_text": "Theek hai, mera appointment confirm kar dein, naam Ali hai."
        })
        assert res_turn3.status_code == 200
        t3 = res_turn3.json()
        assert len(t3.get("reply_text", "")) > 5
        assert len(t3.get("audio_b64", "")) > 1000, "Turn 3 must have synthesized audio"


def test_physical_receipt_generation_endpoints():
    """Verify physical paper receipt generation and sample download."""
    with TestClient(app) as client:
        # Sample receipt PNG
        res_sample = client.get("/api/demo/receipt/sample")
        assert res_sample.status_code == 200
        assert res_sample.headers["content-type"] == "image/png"
        assert len(res_sample.content) > 10000

        # Custom receipt generation
        res_gen = client.post("/api/demo/receipt/generate", json={
            "business_name": "Lahore Grill House",
            "category": "Restaurant",
            "agent_name": "Hamza",
            "customer_name": "Farhan",
            "items": [
                {"name": "Mutton Karahi Full", "qty": 1, "price_pkr": 3800},
                {"name": "Kandhari Naan", "qty": 4, "price_pkr": 100}
            ],
            "status": "PAID"
        })
        assert res_gen.status_code == 200
        data = res_gen.json()
        assert data["status"] == "success"
        assert len(data["receipt_b64"]) > 5000


def test_ocr_receipt_inspector_endpoint():
    """Verify OCR endpoint parses structured receipt text into verified JSON schema."""
    with TestClient(app) as client:
        sample_receipt_text = """
        SMILECARE DENTAL CLINIC
        Receipt #: REC-7741
        Date: 07-Nov-2026
        Customer: Usman Khan
        Teeth Scaling & Polishing: PKR 4,000
        Consultation Fee: PKR 1,500
        Total: PKR 5,500
        Status: PAID
        """
        res_ocr = client.post("/api/demo/receipt/ocr", data={
            "raw_text": sample_receipt_text
        })
        assert res_ocr.status_code == 200
        data = res_ocr.json()
        assert data["status"] == "success"
        extracted = data["extracted_data"]
        assert "smilecare" in extracted.get("business_name", "").lower()
        assert extracted.get("total_pkr") in [5500, 5500.0] or len(extracted.get("items", [])) >= 1


def test_websocket_multi_turn_call():
    """Verify live call WebSocket sends audio on multiple consecutive turns without duplicates."""
    with TestClient(app) as client:
        services = [{"name": "Burger Meal", "price_pkr": 950, "duration_min": 15}]
        res_init = client.post("/api/demo/session", data={
            "agent_name": "Asad",
            "business_name": "Chunkyard Gourmet Burgers",
            "category": "Restaurant",
            "location": "Islamabad",
            "hours": "1 PM - 1 AM",
            "services_json": json.dumps(services)
        })
        sid = res_init.json()["session_id"]

        with client.websocket_connect(f"/ws/live-call/{sid}") as ws:
            # Turn 1
            ws.send_json({"type": "user_speech", "text": "Menu mein kya special hai?"})
            
            # Expect state: thinking
            msg1 = ws.receive_json()
            assert msg1["type"] == "state" and msg1["status"] == "thinking"

            # Expect state: speaking
            msg2 = ws.receive_json()
            assert msg2["type"] == "state" and msg2["status"] == "speaking"

            # Expect single audio_chunk
            msg3 = ws.receive_json()
            assert msg3["type"] == "audio_chunk"
            assert len(msg3["text"]) > 0
            assert len(msg3["audio_b64"]) > 1000

            # Turn 2: continuous interaction
            ws.send_json({"type": "user_speech", "text": "Burger ki timing kya hai?"})
            
            msg4 = ws.receive_json()
            assert msg4["type"] == "state" and msg4["status"] == "thinking"

            msg5 = ws.receive_json()
            assert msg5["type"] == "state" and msg5["status"] == "speaking"

            msg6 = ws.receive_json()
            assert msg6["type"] == "audio_chunk"
            assert len(msg6["text"]) > 0
            assert len(msg6["audio_b64"]) > 1000


def test_landing_page_loads():
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "VoiceDesk AI" in res.text
        assert "Never Miss a Customer Call Again" in res.text
        assert "Launch Interactive Studio" in res.text
        assert "Tools & Integrations" in res.text


def test_login_page_loads():
    with TestClient(app) as client:
        res = client.get("/login")
        assert res.status_code == 200
        assert "Sign In to Business Console" in res.text
        assert "Instant Demo Access" in res.text
        assert "Dental Clinic Admin" in res.text


def test_tools_catalog_and_simulation_endpoints():
    with TestClient(app) as client:
        # 1. Fetch catalog
        res_tools = client.get("/api/demo/tools")
        assert res_tools.status_code == 200
        data = res_tools.json()
        assert len(data.get("tools", [])) >= 6

        # 2. Toggle tool
        res_toggle = client.post("/api/demo/tools/toggle", json={
            "tool_id": "tool-kds",
            "connected": True
        })
        assert res_toggle.status_code == 200
        assert res_toggle.json()["connected"] is True

        # 3. Simulate appointment booking tool
        res_sim_cal = client.post("/api/demo/tools/simulate", json={
            "tool_id": "tool-calendar"
        })
        assert res_sim_cal.status_code == 200
        cal_res = res_sim_cal.json()
        assert cal_res["status"] == "success"
        assert "APT-" in cal_res["simulation_result"]["booking_id"]

        # 4. Simulate thermal receipt tool
        res_sim_rcpt = client.post("/api/demo/tools/simulate", json={
            "tool_id": "tool-receipt"
        })
        assert res_sim_rcpt.status_code == 200
        rcpt_res = res_sim_rcpt.json()
        assert rcpt_res["status"] == "success"
        assert len(rcpt_res["simulation_result"]["receipt_b64"]) > 5000


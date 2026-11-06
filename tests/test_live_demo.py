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
        assert "Step 1 of 3" in res.text


def test_demo_create_session():
    with TestClient(app) as client:
        services = [
            {"name": "Consultation", "price_pkr": 1500, "duration_min": 20},
            {"name": "Scaling", "price_pkr": 4000, "duration_min": 30}
        ]
        res = client.post("/api/demo/session", data={
            "business_name": "Dr. Ayesha Dental Surgery",
            "category": "Dental Clinic",
            "location": "F-8, Islamabad",
            "hours": "12:00 PM - 8:00 PM",
            "services_json": json.dumps(services)
        })
        assert res.status_code == 200
        data = res.json()
        assert "session_id" in data
        assert len(data["session_id"]) > 0
        assert len(data["welcome_text"]) > 10
        # Verify initial greeting audio is generated
        assert len(data.get("welcome_audio_b64", "")) > 1000


def test_multi_turn_continuous_voice_chat():
    """Verify that turns 1, 2, and 3 all return both text and synthesized audio."""
    with TestClient(app) as client:
        services = [
            {"name": "Teeth Scaling", "price_pkr": 4000, "duration_min": 30},
            {"name": "Consultation", "price_pkr": 1500, "duration_min": 20}
        ]
        res_init = client.post("/api/demo/session", data={
            "business_name": "SmileCare Clinic",
            "category": "Dental Clinic",
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

        # Turn 2: Booking inquiry (verifying continuous voice doesn't drop audio)
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


def test_websocket_multi_turn_call():
    """Verify live call WebSocket sends audio on multiple consecutive turns without duplicates."""
    with TestClient(app) as client:
        services = [{"name": "Burger Meal", "price_pkr": 950, "duration_min": 15}]
        res_init = client.post("/api/demo/session", data={
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


def test_demo_export_whatsapp():
    with TestClient(app) as client:
        services = [{"name": "Facial", "price_pkr": 5000, "duration_min": 45}]
        res_init = client.post("/api/demo/session", data={
            "business_name": "Glow Spa",
            "category": "Salon",
            "location": "Karachi",
            "hours": "11 AM - 8 PM",
            "services_json": json.dumps(services)
        })
        sid = res_init.json()["session_id"]

        res_export = client.post("/api/demo/export-whatsapp", data={"session_id": sid})
        export_file = Path("businesses") / f"demo-{sid}.json"
        try:
            assert res_export.status_code == 200
            assert res_export.json()["status"] == "success"
        finally:
            if export_file.exists():
                export_file.unlink()

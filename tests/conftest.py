"""Shared fixtures. All tests use mocks/fakes — never real API calls."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db as dbmod  # noqa: E402
from app.engine import Engine  # noqa: E402

PK = ZoneInfo("Asia/Karachi")

# Sunday 2026-09-27 13:40 PKT — a fixed "now" for deterministic tests.
FIXED_NOW = datetime(2026, 9, 27, 13, 40, tzinfo=PK)


def make_test_config(**overrides):
    cfg = {
        "id": "test-biz",
        "name": "Test Clinic",
        "city": "Islamabad",
        "default_language": "roman_urdu",
        "services": [
            {"name": "General Checkup", "price_pkr": 1500, "duration_min": 30,
             "keywords": ["checkup", "dard", "pain"]},
            {"name": "Scaling & Polishing", "price_pkr": 5000, "duration_min": 45,
             "keywords": ["scaling", "safai", "صفائی"]},
        ],
        "hours": {
            "mon": {"open": "10:00", "close": "21:00"},
            "tue": {"open": "10:00", "close": "21:00"},
            "wed": {"open": "10:00", "close": "21:00"},
            "thu": {"open": "10:00", "close": "21:00"},
            "fri": {"open": "10:00", "close": "21:00"},
            "sat": {"open": "11:00", "close": "20:00"},
            "sun": "closed",
        },
        "location": "Test Road, Islamabad",
        "faqs": [{"q": "Parking?", "a": "Yes, free parking."}],
        "booking": {"slot_minutes": 30, "max_advance_days": 14,
                    "require_name_phone": True},
        "after_hours_message": "We are closed right now.",
        "owner_phone": "+923001234567",
        "tts_voice": "ur-PK-GulNawazNeural",
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture()
def test_config():
    return make_test_config()


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "test.db"
    dbmod.init_db(p)
    return str(p)


@pytest.fixture()
def engine(db_path, test_config, tmp_path):
    """Engine with all network dependencies mocked."""
    calls = {"transcribe": 0, "llm": 0, "tts": 0}

    def fake_transcriber(audio: bytes, hint: str) -> str:
        calls["transcribe"] += 1
        return "kal shaam 5 baje scaling karwana hai"

    def fake_llm(messages) -> str:
        calls["llm"] += 1
        return "Ji, parking bilkul available hai."

    def fake_tts(text: str, voice: str) -> bytes:
        calls["tts"] += 1
        return b"FAKEMP3" + text.encode("utf-8")[:10]

    eng = Engine(
        db_path,
        {"test-biz": test_config},
        transcriber=fake_transcriber,
        llm_chat=fake_llm,
        tts_fn=fake_tts,
        tts_cache_dir=tmp_path / "tts_cache",
        now_fn=lambda: FIXED_NOW,
    )
    eng.calls = calls  # type: ignore[attr-defined]
    return eng

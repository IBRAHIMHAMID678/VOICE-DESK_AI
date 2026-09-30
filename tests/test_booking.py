"""Booking parser: Roman Urdu / Urdu / English + slot conflict logic.

FIXED_NOW in conftest = Sunday 2026-09-27 13:40 PKT. Test config hours:
Mon-Fri 10:00-21:00, Sat 11:00-20:00, Sun closed.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app import booking as b
from app import db as dbmod

PK = ZoneInfo("Asia/Karachi")


def dt(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=PK)


def test_roman_urdu_kal_5_baje(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("kal shaam 5 baje", FIXED_NOW, test_config)
    assert p and not p["partial"]
    assert p["start"] == dt(2026, 9, 28, 17, 0)
    assert p["end"] == dt(2026, 9, 28, 17, 30)  # default checkup 30 min


def test_urdu_script_kal_5_baje(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("کل شام ۵ بجے", FIXED_NOW, test_config)
    assert p and not p["partial"]
    assert p["start"] == dt(2026, 9, 28, 17, 0)


def test_english_tomorrow_5pm(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("tomorrow at 5pm", FIXED_NOW, test_config)
    assert p and not p["partial"]
    assert p["start"] == dt(2026, 9, 28, 17, 0)


def test_next_monday_11_baje(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("next Monday 11 baje", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 28, 11, 0)


def test_parson_subah_10_baje(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("parson subah 10 baje", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 29, 10, 0)


def test_aaj_raat_8_baje(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("aaj raat 8 baje", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 27, 20, 0)


def test_number_words_and_fractions(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("kal paanch baje", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 28, 17, 0)
    p = b.parse_appointment_request("کل ساڑھے پانچ بجے", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 28, 17, 30)


def test_explicit_am_pm(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("kal 10am", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 28, 10, 0)
    p = b.parse_appointment_request("kal subah 10 baje", FIXED_NOW, test_config)
    assert p["start"] == dt(2026, 9, 28, 10, 0)


def test_service_matching(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("kal 5 baje scaling karwana hai",
                                    FIXED_NOW, test_config)
    assert p["service"]["name"] == "Scaling & Polishing"
    assert p["end"] == dt(2026, 9, 28, 17, 45)  # 45-min service


def test_partial_datetime(test_config):
    from tests.conftest import FIXED_NOW
    p = b.parse_appointment_request("kal ka time chahiye", FIXED_NOW, test_config)
    assert p is not None and p["partial"] and p["start"] is None


def test_no_signal_returns_none(test_config):
    from tests.conftest import FIXED_NOW
    assert b.parse_appointment_request("salam, kya haal hai", FIXED_NOW,
                                       test_config) is None


def test_booking_intent():
    assert b.booking_intent("kal 5 baje mil sakta hai")
    assert b.booking_intent("I want to book an appointment")
    assert b.booking_intent("کل اپائنٹمنٹ چاہیے")
    assert not b.booking_intent("parking available hai?")


def test_within_business_hours(test_config):
    ok, _ = b.within_business_hours(test_config, dt(2026, 9, 28, 17, 0),
                                    dt(2026, 9, 28, 17, 30))
    assert ok
    # Sunday is closed.
    ok, reason = b.within_business_hours(test_config, dt(2026, 9, 27, 17, 0),
                                         dt(2026, 9, 27, 17, 30))
    assert not ok and reason == "closed_day"
    # Past closing time.
    ok, reason = b.within_business_hours(test_config, dt(2026, 9, 28, 20, 45),
                                         dt(2026, 9, 28, 21, 15))
    assert not ok and reason == "outside_hours"


def test_conflict_detection(db_path, test_config):
    conn = dbmod.connect(db_path)
    try:
        dbmod.insert_booking(conn, "test-biz", "Ali", "+923001234567",
                             "General Checkup",
                             dt(2026, 9, 28, 17, 0).isoformat(),
                             dt(2026, 9, 28, 17, 30).isoformat(),
                             status="confirmed")
        assert b.has_conflict(conn, "test-biz", dt(2026, 9, 28, 17, 15),
                              dt(2026, 9, 28, 17, 45))
        assert not b.has_conflict(conn, "test-biz", dt(2026, 9, 28, 18, 0),
                                  dt(2026, 9, 28, 18, 30))
        # Cancelled bookings do not block.
        bid = dbmod.insert_booking(conn, "test-biz", "Ali", "+923001234567",
                                   "General Checkup",
                                   dt(2026, 9, 28, 19, 0).isoformat(),
                                   dt(2026, 9, 28, 19, 30).isoformat(),
                                   status="pending")
        dbmod.update_booking_status(conn, bid, "cancelled")
        assert not b.has_conflict(conn, "test-biz", dt(2026, 9, 28, 19, 0),
                                  dt(2026, 9, 28, 19, 30))
    finally:
        conn.close()


def test_suggest_alternatives_skips_taken(db_path, test_config):
    from tests.conftest import FIXED_NOW
    conn = dbmod.connect(db_path)
    try:
        dbmod.insert_booking(conn, "test-biz", "Ali", "+923001234567",
                             "General Checkup",
                             dt(2026, 9, 28, 17, 0).isoformat(),
                             dt(2026, 9, 28, 17, 30).isoformat(),
                             status="confirmed")
        alts = b.suggest_alternatives(conn, test_config, dt(2026, 9, 28, 17, 0),
                                      30, n=3, now=FIXED_NOW)
        assert len(alts) == 3
        assert all(a != dt(2026, 9, 28, 17, 0) for a in alts)
        assert alts[0] == dt(2026, 9, 28, 17, 30)
        # All within business hours.
        for a in alts:
            ok, _ = b.within_business_hours(
                test_config, a, a + b.timedelta(minutes=30))
            assert ok
    finally:
        conn.close()


def test_format_slot_languages():
    s = dt(2026, 9, 28, 17, 0)
    assert "Peer" in b.format_slot(s, "roman_urdu") and "baje" in b.format_slot(s, "roman_urdu")
    assert "پیر" in b.format_slot(s, "ur")
    assert "Monday" in b.format_slot(s, "en") and "PM" in b.format_slot(s, "en")

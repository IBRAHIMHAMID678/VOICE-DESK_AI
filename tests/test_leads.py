"""Lead extraction (regex-first) and the owner daily summary."""
from __future__ import annotations

import pytest

from app import db as dbmod
from app import leads as leads_mod


def test_extract_phones_formats():
    assert leads_mod.extract_phones("mera number 03001234567 hai") == ["+923001234567"]
    assert leads_mod.extract_phones("call me on +92 300 1234567") == ["+923001234567"]
    assert leads_mod.extract_phones("no number here") == []


def test_normalize_phone():
    assert leads_mod.normalize_phone("03001234567") == "+923001234567"
    assert leads_mod.normalize_phone("+923001234567") == "+923001234567"
    assert leads_mod.normalize_phone("923001234567") == "+923001234567"


def test_extract_name_patterns():
    assert leads_mod.extract_name("mera naam Ali Raza hai") == "Ali Raza"
    assert leads_mod.extract_name("my name is Ali Raza") == "Ali Raza"
    assert leads_mod.extract_name("salam, kal 5 baje") is None


def test_capture_from_message(db_path):
    conn = dbmod.connect(db_path)
    try:
        lid = leads_mod.capture_from_message(
            conn, "test-biz", "+923009999999",
            "mera naam Ali Raza hai, number 03001234567")
        assert lid is not None
        # Second message from same number enriches, does not duplicate.
        lid2 = leads_mod.capture_from_message(
            conn, "test-biz", "+923009999999", "03001234567")
        assert lid2 == lid
        leads = leads_mod.list_leads(conn, "test-biz")
        assert len(leads) == 1
        assert leads[0]["name"] == "Ali Raza"
        assert leads[0]["phone"] == "+923001234567"
    finally:
        conn.close()


def test_no_phone_no_lead(db_path):
    conn = dbmod.connect(db_path)
    try:
        assert leads_mod.capture_from_message(
            conn, "test-biz", "+923009999999", "salam, timing kya hai") is None
    finally:
        conn.close()


def test_daily_summary(db_path):
    conn = dbmod.connect(db_path)
    try:
        dbmod.get_or_create_conversation(conn, "test-biz", "+923001234567")
        dbmod.insert_booking(conn, "test-biz", "Ali", "+923001234567",
                             "General Checkup", "2026-09-28T17:00:00+05:00",
                             "2026-09-28T17:30:00+05:00", status="confirmed")
        dbmod.upsert_lead(conn, "test-biz", "+923009999999",
                          name="Sara", need="braces info")
        text = leads_mod.daily_summary(conn, "test-biz", "Test Clinic",
                                       "2026-09-28")
        assert "Test Clinic" in text
        assert "Bookings: 1" in text
        assert "Ali" in text
        assert "New leads:" in text
    finally:
        conn.close()


def test_lead_status_flow(db_path):
    conn = dbmod.connect(db_path)
    try:
        lid = dbmod.upsert_lead(conn, "test-biz", "+923001234567", name="Ali")
        leads_mod.set_lead_status(conn, lid, "contacted")
        assert leads_mod.list_leads(conn, "test-biz", "contacted")[0]["id"] == lid
        with pytest.raises(ValueError):
            leads_mod.set_lead_status(conn, lid, "bogus")
    finally:
        conn.close()

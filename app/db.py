"""SQLite persistence using only the standard library (sqlite3).

Tables:
  businesses    - id, name, config_json, created_at
  conversations - id, business_id, customer_phone, customer_name, state,
                  pending_json, lang, created_at, updated_at
  messages      - id, conversation_id, direction (in|out), kind (text|audio),
                  body, lang, created_at
  bookings      - id, business_id, customer_name, customer_phone, service,
                  start, end, status (pending|confirmed|cancelled), created_at
  leads         - id, business_id, name, phone, need, status, created_at
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PK = ZoneInfo("Asia/Karachi")

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    state TEXT NOT NULL DEFAULT 'idle',
    pending_json TEXT,
    lang TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_biz_phone ON conversations(business_id, customer_phone);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    direction TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text',
    body TEXT NOT NULL,
    lang TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    customer_name TEXT,
    customer_phone TEXT NOT NULL,
    service TEXT,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_booking_biz ON bookings(business_id, start);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    name TEXT,
    phone TEXT NOT NULL,
    need TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);
-- Frugality: transcript cache so a voice note is never transcribed twice.
CREATE TABLE IF NOT EXISTS transcript_cache (
    audio_sha TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(PK).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# ---- conversations ---------------------------------------------------------

def get_or_create_conversation(conn: sqlite3.Connection, business_id: str,
                               customer_phone: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM conversations WHERE business_id=? AND customer_phone=? "
        "ORDER BY id DESC LIMIT 1",
        (business_id, customer_phone),
    ).fetchone()
    if row:
        return row
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO conversations (business_id, customer_phone, state, created_at, updated_at)"
        " VALUES (?, ?, 'idle', ?, ?)",
        (business_id, customer_phone, ts, ts),
    )
    conn.commit()
    return conn.execute("SELECT * FROM conversations WHERE id=?", (cur.lastrowid,)).fetchone()


def update_conversation(conn: sqlite3.Connection, conv_id: int, **fields) -> None:
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE conversations SET {sets} WHERE id=?", (*fields.values(), conv_id))
    conn.commit()


def set_pending(conn: sqlite3.Connection, conv_id: int, pending: dict | None) -> None:
    kind = (pending or {}).get("kind")
    state = {
        "confirm": "awaiting_confirm",
        "details": "awaiting_details",
        "slot_choice": "awaiting_slot_choice",
    }.get(kind, "idle")
    update_conversation(
        conn, conv_id,
        state=state,
        pending_json=json.dumps(pending, ensure_ascii=False) if pending else None,
    )


def get_pending(conn: sqlite3.Connection, conv_id: int) -> dict | None:
    row = conn.execute(
        "SELECT pending_json FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if row and row["pending_json"]:
        return json.loads(row["pending_json"])
    return None


def add_message(conn: sqlite3.Connection, conv_id: int, direction: str, kind: str,
                body: str, lang: str | None = None) -> None:
    conn.execute(
        "INSERT INTO messages (conversation_id, direction, kind, body, lang, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, direction, kind, body, lang, now_iso()),
    )
    conn.commit()


def recent_messages(conn: sqlite3.Connection, conv_id: int, limit: int = 12) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conv_id, limit),
    ).fetchall()[::-1]


# ---- bookings ---------------------------------------------------------------

def insert_booking(conn: sqlite3.Connection, business_id: str, customer_name: str | None,
                   customer_phone: str, service: str | None,
                   start_iso: str, end_iso: str, status: str = "pending") -> int:
    cur = conn.execute(
        "INSERT INTO bookings (business_id, customer_name, customer_phone, service,"
        " start, end, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (business_id, customer_name, customer_phone, service,
         start_iso, end_iso, status, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def update_booking_status(conn: sqlite3.Connection, booking_id: int, status: str) -> None:
    conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    conn.commit()


def update_booking_time(conn: sqlite3.Connection, booking_id: int,
                        start_iso: str, end_iso: str) -> None:
    conn.execute("UPDATE bookings SET start=?, end=?, status='pending' WHERE id=?",
                 (start_iso, end_iso, booking_id))
    conn.commit()


def active_bookings_between(conn: sqlite3.Connection, business_id: str,
                            start_iso: str, end_iso: str,
                            exclude_id: int | None = None) -> list[sqlite3.Row]:
    q = ("SELECT * FROM bookings WHERE business_id=? AND status IN ('pending','confirmed')"
         " AND start < ? AND end > ?")
    params: list = [business_id, end_iso, start_iso]
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(q, params).fetchall()


# ---- leads ------------------------------------------------------------------

def upsert_lead(conn: sqlite3.Connection, business_id: str, phone: str,
                name: str | None = None, need: str | None = None) -> int:
    row = conn.execute(
        "SELECT * FROM leads WHERE business_id=? AND phone=? ORDER BY id DESC LIMIT 1",
        (business_id, phone),
    ).fetchone()
    if row:
        if name and not row["name"]:
            conn.execute("UPDATE leads SET name=? WHERE id=?", (name, row["id"]))
        if need and not row["need"]:
            conn.execute("UPDATE leads SET need=? WHERE id=?", (need, row["id"]))
        conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO leads (business_id, name, phone, need, status, created_at)"
        " VALUES (?, ?, ?, ?, 'new', ?)",
        (business_id, name, phone, need, now_iso()),
    )
    conn.commit()
    return cur.lastrowid

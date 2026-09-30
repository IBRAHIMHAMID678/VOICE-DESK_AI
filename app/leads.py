"""Lead capture: extract name/phone/need from conversations, lead inbox helpers,
and the owner's WhatsApp-ready daily summary."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

# Pakistani phone formats: 03XXXXXXXXX, +92XXXXXXXXXX, 92XXXXXXXXXX, 0092XXXXXXXXXX
PHONE_RE = re.compile(
    r"(?:\+?92|0092|0)?3\d{2}[\s-]?\d{3}[\s-]?\d{4}\b"
)

NAME_PATTERNS = [
    re.compile(r"mera\s+naam\s+([a-zA-Z\u0600-\u06FF]+(?:\s+[a-zA-Z\u0600-\u06FF]+){0,2})", re.I),
    re.compile(r"my\s+name\s+is\s+([a-zA-Z]+(?:\s+[a-zA-Z]+){0,2})", re.I),
    re.compile(r"main\s+([a-zA-Z\u0600-\u06FF]+(?:\s+[a-zA-Z\u0600-\u06FF]+){0,2})"
               r"\s+(?:hoon|hun|bol\s+raha)\b", re.I),
]
# Trailing auxiliaries that leak into the captured name ("Ali Raza hai").
_NAME_TAIL_RE = re.compile(r"\s+(hai|hoon|hun)$", re.I)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0092"):
        digits = digits[4:]
    elif digits.startswith("92") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits.startswith("3"):
        return "+92" + digits
    return "+" + digits if digits else raw.strip()


def extract_phones(text: str) -> list[str]:
    """Find Pakistani phone numbers in free text, normalized to +92XXXXXXXXXX."""
    if not text:
        return []
    found: list[str] = []
    for m in PHONE_RE.finditer(text):
        norm = normalize_phone(m.group(0))
        if norm not in found:
            found.append(norm)
    return found


def extract_name(text: str) -> str | None:
    """Heuristic name extraction ('mera naam X hai', 'my name is X', ...)."""
    t = text.strip().strip(".,!")
    for rx in NAME_PATTERNS:
        m = rx.search(t)
        if m:
            name = _NAME_TAIL_RE.sub("", m.group(1)).strip().strip(".,!")
            if 2 <= len(name) <= 40 and not any(ch.isdigit() for ch in name):
                return name.title() if not re.search(r"[\u0600-\u06FF]", name) else name
    # Fallback: strip phone numbers first, then a short digit-free 1-3 word
    # message ("Sara 03001234567") is probably a name reply.
    c = re.sub(r"\s+", " ", PHONE_RE.sub(" ", t)).strip(" .,!")
    words = c.split()
    if 1 <= len(words) <= 3 and not re.search(r"\d", c) and len(c) >= 3:
        if not any(w.lower().rstrip(".,!") in {
                "haan", "han", "yes", "no", "nahi", "nahin", "ok", "okay",
                "theek", "salam", "assalam", "hello", "hi"}
                for w in words):
            return c.title() if not re.search(r"[\u0600-\u06FF]", c) else c
    return None


def extract_lead_llm(text: str, llm_fn) -> dict:
    """LLM fallback extraction when regex finds nothing.

    llm_fn(messages) -> str. Returns {name, phone, need} (values may be None).
    The LLM is asked to reply with a single JSON object only.
    """
    import json as _json
    prompt = (
        "Extract contact info from this customer message. Reply with ONLY a JSON "
        "object like {\"name\": ..., \"phone\": ..., \"need\": ...} using null for "
        "anything not present. Phone must be a Pakistani mobile number if present.\n"
        f"Message: {text[:500]}"
    )
    try:
        raw = llm_fn([{"role": "user", "content": prompt}])
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            return {"name": None, "phone": None, "need": None}
        data = _json.loads(raw[start:end + 1])
        phone = data.get("phone")
        phones = extract_phones(str(phone)) if phone else []
        return {
            "name": data.get("name") or None,
            "phone": phones[0] if phones else None,
            "need": (str(data.get("need"))[:200] if data.get("need") else None),
        }
    except Exception:  # noqa: BLE001 - extraction is best-effort
        return {"name": None, "phone": None, "need": None}


# Words suggesting the message actually contains contact details.
_CONTACT_HINTS = ["number", "phone", "mobile", "naam", "name", "rabta", "contact"]


def _looks_like_contact_info(text: str) -> bool:
    """Frugality gate: only worth an LLM extraction call for substantive
    messages that mention contact details. Short chit-chat never qualifies."""
    t = text.strip().lower()
    if len(t) < 40:
        return False
    return any(h in t for h in _CONTACT_HINTS)


def capture_from_message(conn: sqlite3.Connection, business_id: str,
                         customer_phone: str, text: str,
                         need_hint: str | None = None,
                         llm_fn=None) -> int | None:
    """Regex-first lead capture from one inbound message. Returns lead id or None."""
    from app import db as _db
    phones = extract_phones(text)
    name = extract_name(text)
    if not phones and llm_fn is not None and _looks_like_contact_info(text):
        # LLM fallback only when regex finds nothing AND the message looks
        # like it contains contact details (frugal: no LLM for chit-chat).
        info = extract_lead_llm(text, llm_fn)
        if info["phone"]:
            phones = [info["phone"]]
        name = name or info["name"]
    if not phones:
        return None
    need = need_hint or (text.strip()[:200] if text.strip() else None)
    return _db.upsert_lead(conn, business_id, phones[0], name=name, need=need)


def list_leads(conn: sqlite3.Connection, business_id: str,
               status: str | None = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM leads WHERE business_id=?"
    params: list = [business_id]
    if status:
        q += " AND status=?"
        params.append(status)
    return conn.execute(q + " ORDER BY id DESC", params).fetchall()


def set_lead_status(conn: sqlite3.Connection, lead_id: int, status: str) -> None:
    if status not in {"new", "contacted", "booked", "closed"}:
        raise ValueError(f"bad lead status '{status}'")
    conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
    conn.commit()


# ---- daily summary ----------------------------------------------------------

def daily_summary(conn: sqlite3.Connection, business_id: str, business_name: str,
                  date_str: str) -> str:
    """WhatsApp-ready plain-text summary for the owner. date_str = 'YYYY-MM-DD'."""
    convs = conn.execute(
        "SELECT COUNT(*) AS n FROM conversations WHERE business_id=? AND date(created_at)=?",
        (business_id, date_str)).fetchone()["n"]
    bookings = conn.execute(
        "SELECT * FROM bookings WHERE business_id=? AND date(start)=? AND status != 'cancelled'"
        " ORDER BY start",
        (business_id, date_str)).fetchall()
    leads = conn.execute(
        "SELECT * FROM leads WHERE business_id=? AND date(created_at)=?",
        (business_id, date_str)).fetchall()

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        d = date_str

    lines = [f"{business_name} - Daily Summary ({d})", ""]
    lines.append(f"Conversations: {convs}")
    lines.append(f"Bookings: {len(bookings)}")
    for b in bookings:
        st = b["start"][11:16]
        who = b["customer_name"] or b["customer_phone"]
        svc = f" ({b['service']})" if b["service"] else ""
        lines.append(f" - {st} - {who}{svc} [{b['status']}]")
    lines.append(f"New leads: {len(leads)}")
    for l in leads:
        who = l["name"] or l["phone"]
        need = f" - {l['need']}" if l["need"] else ""
        lines.append(f" - {who} ({l['phone']}){need} [{l['status']}]")
    if not bookings and not leads:
        lines.append("Quiet day - no bookings or leads yet.")
    return "\n".join(lines)

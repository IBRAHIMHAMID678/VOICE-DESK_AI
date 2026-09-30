"""Natural-language appointment parsing (Roman Urdu / Urdu / English) + slot logic.

Handles relative days (aaj/kal/parson), Urdu-script digits, Urdu/Roman number
words, am/pm and subah/shaam/raat hints. Slot conflict checking against business
hours and existing bookings. All datetimes are Asia/Karachi timezone-aware.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PK = ZoneInfo("Asia/Karachi")
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

DAY_OFFSETS: dict[str, int] = {
    "aaj": 0, "aj": 0, "آج": 0, "today": 0,
    "kal": 1, "کل": 1, "tomorrow": 1,
    "parson": 2, "parsoon": 2, "پرسوں": 2,
}

WEEKDAY_NUM: dict[str, int] = {
    "monday": 0, "mon": 0, "پیر": 0, "peer": 0, "pir": 0,
    "tuesday": 1, "tue": 1, "tues": 1, "منگل": 1, "mangal": 1,
    "wednesday": 2, "wed": 2, "بدھ": 2, "budh": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "جمعرات": 3,
    "jumerat": 3, "jumeraat": 3,
    "friday": 4, "fri": 4, "جمعہ": 4, "juma": 4, "jumma": 4,
    "saturday": 5, "sat": 5, "ہفتہ": 5, "hafta": 5,
    "sunday": 6, "sun": 6, "اتوار": 6, "itwar": 6,
}

NUMBER_WORDS: dict[str, int] = {
    "aek": 1, "aik": 1, "ek": 1, "ایک": 1,
    "do": 2, "دو": 2,
    "teen": 3, "تین": 3,
    "chaar": 4, "char": 4, "چار": 4,
    "paanch": 5, "panch": 5, "پانچ": 5,
    "che": 6, "chay": 6, "چھ": 6,
    "saat": 7, "سات": 7,
    "aath": 8, "ath": 8, "آٹھ": 8,
    "no": 9, "nau": 9, "نو": 9,
    "das": 10, "دس": 10,
    "gyarah": 11, "گیارہ": 11,
    "barah": 12, "بارہ": 12,
}

AM_HINTS = ["subah", "صبح", "morning"]
PM_HINTS = ["dopahar", "dopehar", "دوپہر", "afternoon", "shaam", "sham",
            "شام", "evening", "raat", "رات", "night"]

BOOKING_INTENT_WORDS = [
    "book", "booking", "appointment", "appoint", "reserve", "reservation",
    "slot", "schedule", "time", "timing", "waqt", "وقت", "ٹائم",
    "mil sakta", "mil jaye", "mil jayega", "mil jayegi", "chahiye",
    "aana", "aaunga", "aaungi", "visit", "وزٹ", "baje", "bajay", "بجے",
    "اپائنٹمنٹ", "بکنگ", "aaj", "aj", "kal", "parson", "today", "tomorrow",
    "آج", "کل", "پرسوں",
]

WEEKDAY_NAMES = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "roman_urdu": ["Peer", "Mangal", "Budh", "Jumerat", "Juma", "Hafta", "Itwar"],
    "ur": ["پیر", "منگل", "بدھ", "جمعرات", "جمعہ", "ہفتہ", "اتوار"],
}
MONTH_NAMES = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "roman_urdu": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "ur": ["جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون",
           "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"],
}


def now_pk() -> datetime:
    return datetime.now(PK)


def normalize(text: str) -> str:
    return text.translate(URDU_DIGITS).lower()


def has_any(text: str, words: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def booking_intent(text: str) -> bool:
    t = normalize(text)
    return has_any(t, BOOKING_INTENT_WORDS)


def _num_value(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _extract_time(t: str) -> tuple[int, int] | None:
    """Return (hour24, minute) or None. t must already be normalized."""
    num_alt = "|".join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True))

    # Fractions: "sadhay paanch" (5:30), "sawa teen" (3:15), "paune paanch" (4:45)
    m = re.search(rf"\b(sadhay|saadhay|ساڑھے)\s+({num_alt}|\d{{1,2}})\b", t)
    if m:
        h = _num_value(m.group(2))
        if h is not None:
            return _resolve(h, None, t)[0], 30
    m = re.search(rf"\b(sawa|سوا)\s+({num_alt}|\d{{1,2}})\b", t)
    if m:
        h = _num_value(m.group(2))
        if h is not None:
            return _resolve(h, None, t)[0], 15
    m = re.search(rf"\b(paune|paunay|پونے)\s+({num_alt}|\d{{1,2}})\b", t)
    if m:
        h = _num_value(m.group(2))
        if h is not None:
            h24, _ = _resolve(h, None, t)
            return (h24 - 1) % 24, 45

    # Explicit clock: "5:30", "5.30 pm", "5 pm"
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", t)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
        return _resolve(h, ap, t)[0], mi
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", t)
    if m:
        return _resolve(int(m.group(1)), m.group(2), t)[0], 0

    # "<n> baje": "5 baje", "paanch baje", "5 بجے"
    m = re.search(rf"\b({num_alt}|\d{{1,2}})\s*(baje|bajay|بجے)\b", t)
    if m:
        h = _num_value(m.group(1))
        if h is not None:
            return _resolve(h, None, t)[0], 0
    return None


def _resolve(h: int, ampm: str | None, t: str) -> tuple[int, None]:
    """Resolve a 1-12 hour to 24h using explicit am/pm, daypart hints, defaults."""
    if h >= 13:
        return h, None
    if ampm == "am":
        return (0 if h == 12 else h), None
    if ampm == "pm":
        return (12 if h == 12 else h + 12), None
    if has_any(t, AM_HINTS):
        return (0 if h == 12 else h), None
    if has_any(t, ["raat", "رات", "night"]) and h == 12:
        return 0, None  # "raat 12 baje" = midnight
    if has_any(t, PM_HINTS):
        return (12 if h == 12 else h + 12), None
    # Defaults tuned for Pakistani business hours: 1-9 -> evening, 10-11 -> morning.
    if 1 <= h <= 9:
        return h + 12, None
    if h in (10, 11):
        return h, None
    return 12, None  # h == 12, no hint -> noon


def _extract_date(t: str, now: datetime) -> tuple[datetime | None, str]:
    # Multi-word first
    if "day after tomorrow" in t:
        return (now + timedelta(days=2)).date(), "day after tomorrow"

    for word, off in DAY_OFFSETS.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            return (now + timedelta(days=off)).date(), word

    # "next <weekday>" -> the coming one (strictly ahead)
    m = re.search(
        r"\bnext\s+(" + "|".join(sorted(map(re.escape, WEEKDAY_NUM), key=len, reverse=True)) + r")\b", t)
    if m:
        wd = WEEKDAY_NUM[m.group(1)]
        off = (wd - now.weekday()) % 7
        off = 7 if off == 0 else off
        return (now + timedelta(days=off)).date(), m.group(0)

    # Bare weekday -> nearest upcoming (today counts, time may push it forward)
    for word in sorted(WEEKDAY_NUM, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", t):
            wd = WEEKDAY_NUM[word]
            off = (wd - now.weekday()) % 7
            return (now + timedelta(days=off)).date(), word
    return None, ""


def match_service(text: str, cfg: dict) -> dict | None:
    t = normalize(text)
    for svc in cfg["services"]:
        if svc["name"].lower() in t:
            return svc
        for kw in svc.get("keywords", []):
            if kw and re.search(rf"\b{re.escape(kw.lower())}\b", t):
                return svc
    return None


def parse_appointment_request(text: str, now: datetime, cfg: dict) -> dict | None:
    """Parse a natural-language booking request.

    Returns dict(start, end, service, date_text, time_text, partial) or None if
    no date/time signal was found at all. partial=True when only date or only
    time was found (engine asks for the missing piece).
    """
    t = normalize(text)
    date, date_text = _extract_date(t, now)
    tm = _extract_time(t)

    if date is None and tm is None:
        return None

    svc = match_service(text, cfg)
    duration = (svc or {}).get("duration_min") or cfg["booking"]["slot_minutes"]

    if date is None or tm is None:
        return {
            "start": None, "end": None, "service": svc,
            "date_text": date_text, "time_text": bool(tm),
            "partial": True, "duration_min": duration,
        }

    hour24, minute = tm
    start = datetime(date.year, date.month, date.day, hour24, minute, tzinfo=PK)
    # If a bare weekday resolved to today but the time already passed, push a week.
    if start <= now and date == now.date():
        # check whether a weekday word (not aaj/kal/parson) drove the date
        if not any(re.search(rf"\b{re.escape(w)}\b", t) for w in DAY_OFFSETS):
            start = start + timedelta(days=7)
    end = start + timedelta(minutes=duration)
    return {
        "start": start, "end": end, "service": svc,
        "date_text": date_text, "time_text": True,
        "partial": False, "duration_min": duration,
    }


# ---- availability -----------------------------------------------------------

def within_business_hours(cfg: dict, start: datetime, end: datetime) -> tuple[bool, str]:
    wd = WEEKDAY_KEYS[start.weekday()]
    h = cfg["hours"][wd]
    if h == "closed":
        return False, "closed_day"
    oh, om = map(int, h["open"].split(":"))
    ch, cm = map(int, h["close"].split(":"))
    o = start.replace(hour=oh, minute=om, second=0)
    c = start.replace(hour=ch, minute=cm, second=0)
    if start < o or end > c:
        return False, "outside_hours"
    return True, ""


def has_conflict(conn: sqlite3.Connection, business_id: str,
                 start: datetime, end: datetime,
                 exclude_id: int | None = None) -> bool:
    from app import db as _db  # local import to avoid cycles
    rows = _db.active_bookings_between(
        conn, business_id, start.isoformat(), end.isoformat(), exclude_id)
    return len(rows) > 0


def is_slot_free(conn: sqlite3.Connection, cfg: dict,
                 start: datetime, end: datetime) -> tuple[bool, str]:
    ok, reason = within_business_hours(cfg, start, end)
    if not ok:
        return False, reason
    if has_conflict(conn, cfg["id"], start, end):
        return False, "conflict"
    return True, ""


def _round_up(dt: datetime, minutes: int) -> datetime:
    discard = timedelta(minutes=dt.minute % minutes, seconds=dt.second,
                        microseconds=dt.microsecond)
    dt = dt - discard
    if discard:
        dt += timedelta(minutes=minutes)
    return dt.replace(second=0, microsecond=0)


def suggest_alternatives(conn: sqlite3.Connection, cfg: dict, want: datetime,
                         duration_min: int, n: int = 3,
                         now: datetime | None = None) -> list[datetime]:
    """Find the next n free slots at/after `want`, honoring hours + bookings."""
    now = now or now_pk()
    step = cfg["booking"]["slot_minutes"]
    max_days = cfg["booking"]["max_advance_days"]
    out: list[datetime] = []
    cursor = _round_up(max(want, now + timedelta(minutes=15)), step)
    day = cursor.date()
    limit = (now + timedelta(days=max_days)).date()
    while day <= limit and len(out) < n:
        wd = WEEKDAY_KEYS[day.weekday()]
        h = cfg["hours"][wd]
        if h != "closed":
            oh, om = map(int, h["open"].split(":"))
            ch, cm = map(int, h["close"].split(":"))
            open_dt = datetime(day.year, day.month, day.day, oh, om, tzinfo=PK)
            close_dt = datetime(day.year, day.month, day.day, ch, cm, tzinfo=PK)
            slot = max(cursor, open_dt) if day == cursor.date() else open_dt
            slot = _round_up(slot, step)
            while slot + timedelta(minutes=duration_min) <= close_dt and len(out) < n:
                end = slot + timedelta(minutes=duration_min)
                if slot >= now and not has_conflict(conn, cfg["id"], slot, end):
                    out.append(slot)
                slot += timedelta(minutes=step)
        day += timedelta(days=1)
        cursor = datetime(day.year, day.month, day.day, tzinfo=PK)
    return out


# ---- formatting ---------------------------------------------------------------

def daypart(h: int, lang: str) -> str:
    if lang == "ur":
        if 5 <= h < 12:
            return "صبح"
        if 12 <= h < 17:
            return "دوپہر"
        if 17 <= h < 20:
            return "شام"
        return "رات"
    if lang == "roman_urdu":
        if 5 <= h < 12:
            return "subah"
        if 12 <= h < 17:
            return "dopahar"
        if 17 <= h < 20:
            return "shaam"
        return "raat"
    if 5 <= h < 12:
        return "in the morning"
    if 12 <= h < 17:
        return "in the afternoon"
    if 17 <= h < 20:
        return "in the evening"
    return "at night"


def format_slot(dt: datetime, lang: str = "roman_urdu") -> str:
    wd = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["en"])[dt.weekday()]
    mon = MONTH_NAMES.get(lang, MONTH_NAMES["en"])[dt.month - 1]
    h12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    if lang == "ur":
        return f"{wd}، {dt.day} {mon}، {daypart(dt.hour, lang)} {h12}:{dt.minute:02d} بجے"
    if lang == "roman_urdu":
        return f"{wd}, {dt.day} {mon}, {daypart(dt.hour, lang)} {h12}:{dt.minute:02d} baje"
    return f"{wd}, {dt.day} {mon}, {h12}:{dt.minute:02d} {ampm}"

#!/usr/bin/env python3
"""End-to-end demo: a Roman-Urdu patient-booking conversation against the
dental-clinic config, WITHOUT WhatsApp.

Modes:
  python demo.py            # --mock (DEFAULT): zero API calls. Scripted LLM
                           # stub, mock transcriber, TTS skipped.
  python demo.py --live     # Real Groq Whisper + LLM + edge-tts. Requires
                           # GROQ_API_KEY in the environment. Still frugal:
                           # transcripts and TTS are cached.

Prints the full transcript with annotations (language detection, booking
parse, slot status, cache hits) and exits 0 on success.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import cache as cache_mod  # noqa: E402
from app import config as config_mod  # noqa: E402
from app import db as dbmod  # noqa: E402
from app import leads as leads_mod  # noqa: E402
from app.engine import Engine  # noqa: E402

PK = ZoneInfo("Asia/Karachi")
ROMAN_DAYS = ["Peer", "Mangal", "Budh", "Jumerat", "Juma", "Hafta", "Itwar"]


def scripted_llm(messages) -> str:
    """Deterministic stand-in for Groq chat. Zero network calls."""
    last = messages[-1]["content"].lower()
    if "parking" in last:
        return "Ji, free parking bilkul available hai."
    if "timing" in last or "khule" in last:
        return "Hum Peer se Juma subah 10 se raat 9 baje tak khule rehte hain."
    return "Ji zaroor! (yeh scripted demo reply hai)"


def mock_transcriber(audio: bytes, hint: str) -> str:
    return "shukriya, bahut meherbani"


def mock_tts(text: str, voice: str) -> bytes:
    return b""  # mock mode: TTS skipped silently


def next_open_day(from_date) -> datetime:
    d = from_date + timedelta(days=1)
    while d.weekday() == 6:  # clinic closed Sundays
        d += timedelta(days=1)
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice-receptionist end-to-end demo")
    ap.add_argument("--mock", action="store_true", default=True,
                    help="offline mode: zero API calls (default)")
    ap.add_argument("--live", action="store_true",
                    help="use real Groq + edge-tts (needs GROQ_API_KEY)")
    args = ap.parse_args()
    live = args.live
    if live and not os.environ.get("GROQ_API_KEY"):
        print("ERROR: --live needs GROQ_API_KEY in the environment.", file=sys.stderr)
        return 2
    if live:
        args.mock = False

    tmp = Path(tempfile.mkdtemp(prefix="vr-demo-"))
    db_path = tmp / "demo.db"
    dbmod.init_db(db_path)
    configs = config_mod.load_all_configs(ROOT / "businesses")
    cfg = configs["smilecare-dental"]

    if live:
        engine = Engine(str(db_path), configs,
                        tts_cache_dir=tmp / "tts_cache")
        mode_note = "LIVE (Groq Whisper + LLM, edge-tts)"
    else:
        engine = Engine(str(db_path), configs,
                        transcriber=mock_transcriber,
                        llm_chat=scripted_llm,
                        tts_fn=mock_tts,
                        tts_cache_dir=tmp / "tts_cache")
        mode_note = "MOCK (zero API calls: scripted LLM, mock STT, TTS skipped)"

    sent: list[tuple[str, str, bytes | None]] = []  # mock WhatsApp outbox

    def send(to: str, result) -> None:
        sent.append((to, result.reply_text, result.reply_audio))

    phone = "+923001234567"
    target = next_open_day(datetime.now(PK))
    day_word = ROMAN_DAYS[target.weekday()].lower()

    turns = [
        ("text", f"Salam, mujhe daant mein dard hai. {day_word} ka time mil sakta hai?"),
        ("text", f"{day_word} shaam 5 baje"),
        ("text", "Ali Raza, 03001234567"),
        ("text", "haan"),
        ("audio", b"<fake voice-note bytes>"),  # transcriber mock -> "shukriya..."
        ("text", "parking available hai?"),
    ]

    print("=" * 72)
    print(f"VOICE-RECEPTIONIST DEMO  [{mode_note}]")
    print(f"Business: {cfg['name']}, {cfg['city']}  |  Customer: {phone}")
    print("=" * 72)

    for kind, payload in turns:
        if kind == "text":
            print(f"\nYou (text): {payload}")
            result = engine.handle("smilecare-dental", phone, text=payload)
        else:
            print("\nYou (voice note)  [mock audio bytes]")
            result = engine.handle("smilecare-dental", phone, audio_bytes=payload)
            print(f"  [transcript: {mock_transcriber(payload, 'ur') if not live else '(real STT)'}]")
        send(phone, result)
        print(f"  [lang: {result.lang}] [actions: {', '.join(result.actions) or '-'}]")
        print(f"Receptionist: {result.reply_text}")
        if result.reply_audio:
            print(f"  [voice reply: {len(result.reply_audio)} bytes of audio]")
        elif kind == "audio":
            print("  [voice reply: skipped in mock mode]")

    # ---- final state ------------------------------------------------------
    conn = dbmod.connect(db_path)
    try:
        bookings = conn.execute(
            "SELECT * FROM bookings WHERE business_id='smilecare-dental'").fetchall()
        leads = leads_mod.list_leads(conn, "smilecare-dental")
        tts_stats = cache_mod.TTSCache(tmp / "tts_cache").stats()
        t_stats = cache_mod.transcript_cache_stats(conn)
        summary = leads_mod.daily_summary(conn, "smilecare-dental",
                                          cfg["name"],
                                          target.date().isoformat())
    finally:
        conn.close()

    print("\n" + "=" * 72)
    print("FINAL STATE")
    print("-" * 72)
    for b_ in bookings:
        print(f"booking #{b_['id']}: {b_['service']} | {b_['start']} -> {b_['end']} "
              f"| {b_['customer_name']} {b_['customer_phone']} [{b_['status']}]")
    for l_ in leads:
        print(f"lead #{l_['id']}: {l_['name']} {l_['phone']} [{l_['status']}]")
    print(f"cache: {tts_stats['files']} TTS clips, {t_stats['rows']} transcripts")
    print("-" * 72)
    print("OWNER DAILY SUMMARY (WhatsApp-ready):")
    print(summary)
    print("=" * 72)

    assert bookings and bookings[0]["status"] == "confirmed", "demo booking failed"
    print("\nDemo completed successfully (exit 0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

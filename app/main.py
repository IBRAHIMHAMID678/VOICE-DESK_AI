"""FastAPI app: WhatsApp webhook + owner dashboard.

Run:  uvicorn app.main:app --reload   (from the project root)
Dashboard: http://localhost:8000/
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import booking as booking_mod
from app import cache as cache_mod
from app import config as config_mod
from app import db as dbmod
from app import leads as leads_mod
from app import whatsapp
from app.engine import Engine

log = logging.getLogger("voice-receptionist")

BASE_DIR = Path(__file__).resolve().parent.parent
BUSINESSES_DIR = BASE_DIR / "businesses"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "voice_receptionist.db"
PK = ZoneInfo("Asia/Karachi")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.configs = _load()
    app.state.engine = Engine(str(DB_PATH), app.state.configs)
    log.info("loaded businesses: %s", list(app.state.configs))
    yield


app = FastAPI(title="Voice Receptionist", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ------------------------------------------------------------------ startup

def _load() -> dict:
    configs = config_mod.load_all_configs(BUSINESSES_DIR)
    dbmod.init_db(DB_PATH)
    # Seed businesses table (for dashboard reference).
    conn = dbmod.connect(DB_PATH)
    try:
        for bid, cfg in configs.items():
            conn.execute(
                "INSERT OR REPLACE INTO businesses (id, name, config_json, created_at)"
                " VALUES (?, ?, ?, ?)",
                (bid, cfg["name"], json.dumps(cfg, ensure_ascii=False),
                 dbmod.now_iso()))
        conn.commit()
    finally:
        conn.close()
    return configs


def get_configs(request: Request) -> dict:
    if not hasattr(request.app.state, "configs"):
        request.app.state.configs = _load()
        request.app.state.engine = Engine(str(DB_PATH), request.app.state.configs)
    return request.app.state.configs


def current_business_id(request: Request, business: str | None = None) -> str:
    configs = get_configs(request)
    if business in configs:
        return business
    return next(iter(configs))


def base_ctx(request: Request, business: str | None, page: str) -> dict:
    configs = get_configs(request)
    bid = current_business_id(request, business)
    return {
        "request": request,
        "businesses": configs,
        "business_id": bid,
        "business": configs[bid],
        "page": page,
    }


# ------------------------------------------------------------------ webhook

@app.get("/webhook")
def webhook_verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    """Meta webhook verification handshake."""
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if hub_mode == "subscribe" and expected and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="verification failed")


@app.post("/webhook")
async def webhook_inbound(request: Request):
    """Receive WhatsApp messages, run the engine, send replies.

    Verifies X-Hub-Signature-256 when WHATSAPP_APP_SECRET is configured.
    Never raises: every failure is logged and answered with 200 so Meta
    doesn't retry-storm us.
    """
    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("webhook signature mismatch — rejecting")
        raise HTTPException(status_code=403, detail="bad signature")
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        log.warning("webhook: malformed JSON payload")
        return {"ok": True}
    messages = whatsapp.parse_webhook_payload(payload)
    if not messages:
        return {"ok": True}
    engine: Engine = request.app.state.engine
    configs = get_configs(request)
    default_bid = next(iter(configs))
    for m in messages:
        bid = default_bid
        for cid, cfg in configs.items():  # route by receiving number when mapped
            if cfg.get("whatsapp_phone_number_id") and \
                    cfg["whatsapp_phone_number_id"] == m.phone_number_id:
                bid = cid
                break
        cfg = configs[bid]
        log.info("inbound %s from %s -> %s", m.kind, m.sender_wa_id, bid)
        audio, text = None, m.text
        if m.kind == "audio" and m.audio_media_id:
            try:
                audio = whatsapp.download_media(m.audio_media_id)
            except Exception as e:  # noqa: BLE001
                log.warning("media download failed for %s: %s", m.sender_wa_id, e)
                _safe_send_text(m.sender_wa_id,
                                _fallback_text(cfg["default_language"]))
                continue
        try:
            result = engine.handle(bid, m.sender_wa_id, text=text,
                                   audio_bytes=audio,
                                   profile_name=m.profile_name)
        except Exception as e:  # noqa: BLE001
            log.exception("engine failed for %s: %s", m.sender_wa_id, e)
            continue
        log.info("reply to %s: lang=%s actions=%s",
                 m.sender_wa_id, result.lang, ",".join(result.actions))
        try:
            if result.reply_audio:
                whatsapp.send_audio(m.sender_wa_id, result.reply_audio)
            elif result.reply_text:
                whatsapp.send_text(m.sender_wa_id, result.reply_text)
        except Exception as e:  # noqa: BLE001
            log.warning("send failed to %s: %s", m.sender_wa_id, e)
        # Owner notification (e.g. booking confirmed) — best effort.
        if result.notify_owner:
            try:
                whatsapp.send_text(cfg["owner_phone"], result.notify_owner)
                log.info("owner notified at %s", cfg["owner_phone"])
            except Exception as e:  # noqa: BLE001
                log.warning("owner notify failed: %s", e)
    return {"ok": True}


def _verify_signature(body: bytes, signature: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 header. If WHATSAPP_APP_SECRET is not
    configured, verification is skipped with a warning (dev mode)."""
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret:
        log.warning("WHATSAPP_APP_SECRET not set — webhook signature not verified")
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[len("sha256="):])


def _safe_send_text(to: str, body: str) -> None:
    try:
        whatsapp.send_text(to, body)
    except Exception as e:  # noqa: BLE001
        log.warning("fallback send failed to %s: %s", to, e)


def _fallback_text(lang: str) -> str:
    return {
        "ur": "آواز کا پیغام موصول نہیں ہو سکا۔ براہ کرم ٹیکسٹ میں لکھ کر بھیج دیں۔",
        "roman_urdu": "Voice note receive nahi ho saka. Baraye meherbani text mein likh kar bhej dein.",
        "en": "I couldn't receive your voice note. Please send your message as text.",
    }.get(lang, "Voice note receive nahi ho saka. Text mein bhej dein.")


# ---------------------------------------------------------------- dashboard

@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, business: str | None = None):
    return conversations_page(request, business)


@app.get("/conversations", response_class=HTMLResponse)
def conversations_page(request: Request, business: str | None = None):
    ctx = base_ctx(request, business, "conversations")
    conn = dbmod.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT c.*, (SELECT body FROM messages WHERE conversation_id=c.id"
            " ORDER BY id DESC LIMIT 1) AS last_msg,"
            " (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id) AS msg_count"
            " FROM conversations c WHERE business_id=? ORDER BY updated_at DESC",
            (ctx["business_id"],)).fetchall()
        ctx["conversations"] = rows
    finally:
        conn.close()
    return templates.TemplateResponse(request, "conversations.html", ctx)


@app.get("/conversations/{conv_id}", response_class=HTMLResponse)
def conversation_detail(request: Request, conv_id: int,
                        business: str | None = None):
    ctx = base_ctx(request, business, "conversations")
    conn = dbmod.connect(DB_PATH)
    try:
        conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not conv:
            raise HTTPException(404, "conversation not found")
        ctx["conv"] = conv
        ctx["messages"] = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id",
            (conv_id,)).fetchall()
        ctx["pending"] = dbmod.get_pending(conn, conv_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "conversation_detail.html", ctx)


@app.get("/bookings", response_class=HTMLResponse)
def bookings_page(request: Request, business: str | None = None,
                  week: str | None = None):
    ctx = base_ctx(request, business, "bookings")
    conn = dbmod.connect(DB_PATH)
    try:
        upcoming = conn.execute(
            "SELECT * FROM bookings WHERE business_id=? AND status IN ('pending','confirmed')"
            " AND datetime(start) >= datetime('now', 'localtime')"
            " ORDER BY start LIMIT 50", (ctx["business_id"],)).fetchall()
        ctx["upcoming"] = upcoming
        # Week view: Monday-Sunday grid.
        try:
            ref = datetime.strptime(week, "%Y-%m-%d").date() if week else datetime.now(PK).date()
        except ValueError:
            ref = datetime.now(PK).date()
        monday = ref - timedelta(days=ref.weekday())
        days = [monday + timedelta(days=i) for i in range(7)]
        week_bookings: dict[str, list] = {d.isoformat(): [] for d in days}
        rows = conn.execute(
            "SELECT * FROM bookings WHERE business_id=? AND date(start) BETWEEN ? AND ?"
            " AND status != 'cancelled' ORDER BY start",
            (ctx["business_id"], days[0].isoformat(), days[6].isoformat())).fetchall()
        for r in rows:
            week_bookings[r["start"][:10]].append(r)
        ctx["week_days"] = days
        ctx["week_bookings"] = week_bookings
        ctx["week_start"] = monday
        ctx["today"] = datetime.now(PK).date().isoformat()
        ctx["prev_week"] = (monday - timedelta(days=7)).isoformat()
        ctx["next_week"] = (monday + timedelta(days=7)).isoformat()
    finally:
        conn.close()
    return templates.TemplateResponse(request, "bookings.html", ctx)


@app.post("/api/bookings/{booking_id}/status")
def booking_status(booking_id: int, status: str = Form(...)):
    if status not in {"pending", "confirmed", "cancelled"}:
        raise HTTPException(400, "bad status")
    conn = dbmod.connect(DB_PATH)
    try:
        dbmod.update_booking_status(conn, booking_id, status)
    finally:
        conn.close()
    return {"ok": True}


@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request, business: str | None = None,
               status: str | None = None):
    ctx = base_ctx(request, business, "leads")
    conn = dbmod.connect(DB_PATH)
    try:
        ctx["leads"] = leads_mod.list_leads(conn, ctx["business_id"], status or None)
        ctx["filter_status"] = status or ""
    finally:
        conn.close()
    return templates.TemplateResponse(request, "leads.html", ctx)


@app.post("/api/leads/{lead_id}/status")
def lead_status(lead_id: int, status: str = Form(...)):
    conn = dbmod.connect(DB_PATH)
    try:
        leads_mod.set_lead_status(conn, lead_id, status)
    finally:
        conn.close()
    return {"ok": True}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, business: str | None = None):
    configs = get_configs(request)
    is_new = business == "new"
    cfg = {} if is_new else configs.get(business) or configs[next(iter(configs))]
    ctx = base_ctx(request, None if is_new else business, "settings")
    ctx["cfg"] = cfg
    ctx["is_new"] = is_new
    ctx["cfg_json"] = json.dumps(cfg, ensure_ascii=False, indent=2)
    ctx["error"] = ""
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings", response_class=HTMLResponse)
def settings_save(request: Request, config_json: str = Form(...),
                  business: str | None = Form(None)):
    """Validate and persist a business config edited in the dashboard."""
    configs = get_configs(request)
    try:
        cfg = json.loads(config_json)
        config_mod.validate_config(cfg)
    except (json.JSONDecodeError, config_mod.ConfigValidationError) as e:
        ctx = base_ctx(request, business if business != "new" else None, "settings")
        ctx["cfg"] = {}
        ctx["is_new"] = business == "new"
        ctx["cfg_json"] = config_json
        ctx["error"] = f"Invalid config: {e}"
        return templates.TemplateResponse(request, "settings.html", ctx, status_code=400)
    path = BUSINESSES_DIR / f"{cfg['id']}.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    # Hot-reload configs + engine.
    request.app.state.configs = config_mod.load_all_configs(BUSINESSES_DIR)
    request.app.state.engine = Engine(str(DB_PATH), request.app.state.configs)
    return RedirectResponse(f"/settings?business={cfg['id']}", status_code=303)


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, business: str | None = None):
    ctx = base_ctx(request, business, "analytics")
    conn = dbmod.connect(DB_PATH)
    try:
        bid = ctx["business_id"]
        ctx["total_conversations"] = conn.execute(
            "SELECT COUNT(*) n FROM conversations WHERE business_id=?", (bid,)).fetchone()["n"]
        ctx["total_bookings"] = conn.execute(
            "SELECT COUNT(*) n FROM bookings WHERE business_id=? AND status != 'cancelled'",
            (bid,)).fetchone()["n"]
        ctx["total_leads"] = conn.execute(
            "SELECT COUNT(*) n FROM leads WHERE business_id=?", (bid,)).fetchone()["n"]
        days = [(datetime.now(PK).date() - timedelta(days=i)) for i in range(6, -1, -1)]
        per_day = []
        for d in days:
            n = conn.execute(
                "SELECT COUNT(*) n FROM bookings WHERE business_id=?"
                " AND date(start)=? AND status != 'cancelled'",
                (bid, d.isoformat())).fetchone()["n"]
            c = conn.execute(
                "SELECT COUNT(*) n FROM conversations WHERE business_id=?"
                " AND date(created_at)=?", (bid, d.isoformat())).fetchone()["n"]
            per_day.append({"day": d.strftime("%a"), "bookings": n, "conversations": c})
        ctx["per_day"] = per_day
        ctx["max_n"] = max([p["bookings"] for p in per_day] + [1])
        ctx["tts_cache"] = cache_mod.TTSCache(DATA_DIR / "tts_cache").stats()
        ctx["transcript_cache"] = cache_mod.transcript_cache_stats(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "analytics.html", ctx)


@app.get("/api/daily-summary")
def api_daily_summary(request: Request, business: str | None = None,
                      date: str | None = None):
    """Plain-text owner summary, ready to paste into WhatsApp."""
    configs = get_configs(request)
    bid = current_business_id(request, business)
    date = date or datetime.now(PK).date().isoformat()
    conn = dbmod.connect(DB_PATH)
    try:
        text = leads_mod.daily_summary(conn, bid, configs[bid]["name"], date)
    finally:
        conn.close()
    return PlainTextResponse(text)

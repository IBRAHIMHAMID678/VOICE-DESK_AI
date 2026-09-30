"""Conversation engine: inbound text/voice -> language detection -> booking
dialogue or LLM chat -> reply in the SAME language and modality.

Design notes:
- All business knowledge comes from the per-business config. Nothing is
  hardcoded here.
- Booking is handled explicitly (parse -> availability -> confirm states);
  the LLM only handles free chat (FAQs, small talk, directions).
- Frugality: transcripts are cached by audio sha256 (SQLite); TTS audio is
  cached by (text, voice) on disk. The Groq client raises GroqRateLimited on
  HTTP 429 — the engine degrades to a polite templated reply instead of
  retrying.
- Dependencies (transcriber, llm_chat, tts_fn) are injectable so tests and
  the demo run with zero network calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app import booking as booking_mod
from app import cache as cache_mod
from app import db as dbmod
from app import groq_client
from app import leads as leads_mod
from app import tts as tts_mod
from app.language import detect_language

AFFIRM = {"haan", "han", "ha", "yes", "yeah", "yup", "ok", "okay", "theek",
          "confirm", "done", "kardo", "kardein", "karein", "bilkul", "جی", "ہاں",
          "ٹھیک", "جی ہاں", "ضرور"}
DENY = {"nahi", "nahin", "nhe", "nhi", "no", "nope", "cancel", "mat",
        "نہیں", "نہ"}

# ---------------------------------------------------------------- templates

def _t(key: str, lang: str, **kw) -> str:
    templates = {
        "ask_time": {
            "ur": "کس وقت آنا چاہیں گے؟ براہ کرم وقت بتائیں، مثلاً شام 5 بجے۔",
            "roman_urdu": "Aap kis time aana chahenge? Waqt batayein, masalan shaam 5 baje.",
            "en": "What time would you like to come? For example, 5pm.",
        },
        "ask_day": {
            "ur": "کس دن آنا چاہیں گے؟ مثلاً کل، پرسوں، یا پیر کو۔",
            "roman_urdu": "Kis din aana chahenge? Masalan kal, parson, ya Monday ko.",
            "en": "Which day would you like to come? For example tomorrow or Monday.",
        },
        "need_name_phone": {
            "ur": "{slot} پر {service} دستیاب ہے۔ بکنگ مکمل کرنے کے لیے اپنا نام اور موبائل نمبر بھیج دیں۔",
            "roman_urdu": "{slot} par {service} available hai. Booking confirm karne ke liye apna naam aur mobile number bhej dein.",
            "en": "{slot} is available for {service}. Please send your name and mobile number to complete the booking.",
        },
        "confirm_ask": {
            "ur": "کیا میں {service} کے لیے {slot} بک کر دوں؟ جواب میں 'ہاں' یا 'نہیں' لکھیں۔",
            "roman_urdu": "Kya mein {service} ke liye {slot} book kar dun? 'Haan' ya 'nahi' likh kar confirm karein.",
            "en": "Shall I book {service} for {slot}? Reply 'yes' or 'no' to confirm.",
        },
        "confirmed": {
            "ur": "بکنگ کنفرم ہو گئی ہے: {service}، {slot}۔ وقت پر تشریف لائیے گا۔ شکریہ!",
            "roman_urdu": "Booking confirm ho gayi hai: {service}, {slot}. Time par tashreef laiyega. Shukriya!",
            "en": "Your booking is confirmed: {service}, {slot}. Please arrive on time. Thank you!",
        },
        "cancelled": {
            "ur": "ٹھیک ہے، بکنگ منسوخ کر دی گئی ہے۔",
            "roman_urdu": "Theek hai, booking cancel kar di gayi hai.",
            "en": "Understood, the booking has been cancelled.",
        },
        "clarify": {
            "ur": "معذرت، میں سمجھ نہیں پایا۔ براہ کرم دن اور وقت بتائیں، مثلاً 'کل شام 5 بجے'۔",
            "roman_urdu": "Maazrat, mein samajh nahi paya. Baraye meherbani din aur waqt batayein, masalan 'kal shaam 5 baje'.",
            "en": "Sorry, I didn't understand. Please share a day and time, e.g. 'tomorrow at 5pm'.",
        },
        "busy": {
            "ur": "معذرت، اس وقت سسٹم مصروف ہے۔ تھوڑی دیر بعد دوبارہ کوشش کریں یا اپنا نمبر بھیج دیں، ہم خود رابطہ کریں گے۔",
            "roman_urdu": "Maazrat, is waqt system masroof hai. Thodi der baad dobara message karein ya apna number bhej dein, hum khud rabta karenge.",
            "en": "Sorry, our system is busy right now. Please try again shortly or send your number and we will call you back.",
        },
        "voice_fallback": {
            "ur": "آواز کا پیغام سمجھ نہیں آیا۔ براہ کرم ٹیکسٹ میں لکھ کر بھیج دیں۔",
            "roman_urdu": "Voice note samajh nahi aaya. Baraye meherbani text mein likh kar bhej dein.",
            "en": "I couldn't understand the voice note. Please send your message as text.",
        },
    }
    return templates[key][lang].format(**kw)


def _slot_taken(lang: str, alternatives: list[datetime]) -> str:
    if lang == "ur":
        head = "معذرت، یہ وقت دستیاب نہیں ہے۔ قریبی دستیاب اوقات یہ ہیں:"
        opts = [f"{i+1}. {booking_mod.format_slot(s, 'ur')}" for i, s in enumerate(alternatives)]
        tail = "کوئی ایک منتخب کریں (1، 2 یا 3 لکھیں)۔"
    elif lang == "en":
        head = "Sorry, that time is not available. The nearest free slots are:"
        opts = [f"{i+1}. {booking_mod.format_slot(s, 'en')}" for i, s in enumerate(alternatives)]
        tail = "Please pick one (reply 1, 2 or 3)."
    else:
        head = "Maazrat, ye time available nahi hai. Qareebi free slots ye hain:"
        opts = [f"{i+1}. {booking_mod.format_slot(s, 'roman_urdu')}" for i, s in enumerate(alternatives)]
        tail = "Koi ek muntakhib karein (1, 2 ya 3 likhein)."
    return "\n".join([head, *opts, tail])


# ------------------------------------------------------------------ engine

@dataclass
class EngineResult:
    reply_text: str
    reply_audio: bytes | None = None   # set when inbound was a voice note
    lang: str = "roman_urdu"
    actions: list = field(default_factory=list)
    notify_owner: str | None = None    # message for the business owner, if any


class Engine:
    def __init__(self, db_path, configs: dict,
                 transcriber=None, llm_chat=None, tts_fn=None,
                 tts_cache_dir=None, now_fn=None):
        self.db_path = db_path
        self.configs = configs
        self.transcriber = transcriber or (
            lambda audio, hint: groq_client.transcribe_audio(audio, hint))
        self.llm_chat = llm_chat or groq_client.chat
        self.tts_fn = tts_fn or tts_mod.synthesize
        cache_dir = tts_cache_dir or (dbmod.Path(self.db_path).parent / "tts_cache")
        self.tts_cache = cache_mod.TTSCache(cache_dir)
        self.now_fn = now_fn or booking_mod.now_pk

    # ------------------------------------------------------------- public

    def handle(self, business_id: str, sender_phone: str,
               text: str | None = None, audio_bytes: bytes | None = None,
               profile_name: str | None = None) -> EngineResult:
        cfg = self.configs.get(business_id)
        if cfg is None:
            raise ValueError(f"unknown business '{business_id}'")
        actions: list[str] = []
        now = self.now_fn()
        conn = dbmod.connect(self.db_path)
        try:
            conv = dbmod.get_or_create_conversation(conn, business_id, sender_phone)
            conv_id = conv["id"]
            if profile_name and not conv["customer_name"]:
                dbmod.update_conversation(conn, conv_id, customer_name=profile_name)

            inbound_kind = "audio" if audio_bytes else "text"

            # 1. voice -> text (transcript cache first)
            if audio_bytes:
                text = self._transcribe_cached(conn, audio_bytes, cfg, actions)
                if not text:
                    reply = _t("voice_fallback", cfg["default_language"])
                    return self._finish(conn, conv_id, "", inbound_kind, reply,
                                       cfg, actions, lang=cfg["default_language"])
            text = (text or "").strip()

            # 2. language detection. Weak-signal messages (names, phone
            # numbers, one-word replies) inherit the conversation language
            # so the bot doesn't flip to English mid-flow.
            lang = detect_language(text) if text else cfg["default_language"]
            alpha_words = re.findall(r"[a-zA-Z\u0600-\u06FF]+", text)
            if len(alpha_words) < 3 and conv["lang"] in ("ur", "roman_urdu", "en"):
                lang = conv["lang"]
            dbmod.update_conversation(conn, conv_id, lang=lang)
            dbmod.add_message(conn, conv_id, "in", inbound_kind, text, lang)

            # 3. lead capture (regex first; LLM fallback gated inside)
            need_hint = None
            lead_id = leads_mod.capture_from_message(
                conn, business_id, sender_phone, text,
                need_hint=need_hint, llm_fn=self.llm_chat)
            if lead_id:
                actions.append("lead_captured")

            # 4. route
            state = conv["state"]
            pending = dbmod.get_pending(conn, conv_id)
            notify = None
            if state == "awaiting_confirm" and pending:
                reply, new_actions, notify = self._handle_confirm(
                    conn, conv, pending, text, lang, cfg, now)
                actions += new_actions
            elif state == "awaiting_slot_choice" and pending:
                reply, new_actions, notify = self._handle_slot_choice(
                    conn, conv, pending, text, lang, cfg, now)
                actions += new_actions
            elif state == "awaiting_details" and pending:
                reply, new_actions, notify = self._handle_details(
                    conn, conv, pending, text, lang, cfg, sender_phone)
                actions += new_actions
            elif booking_mod.booking_intent(text):
                reply, new_actions, notify = self._handle_booking_intent(
                    conn, conv, text, lang, cfg, now, sender_phone)
                actions += new_actions
            else:
                reply, new_actions, notify = self._handle_chat(
                    conn, conv_id, text, lang, cfg)
                actions += new_actions

            # 5. after-hours notice — only on the customer's first message,
            # so it informs without nagging on every reply.
            first_message = conn.execute(
                "SELECT COUNT(*) AS n FROM messages"
                " WHERE conversation_id=? AND direction='in'",
                (conv_id,)).fetchone()["n"] == 1
            if first_message and not booking_mod.within_business_hours(
                    cfg, now, now + booking_mod.timedelta(minutes=1))[0]:
                reply = f"{reply}\n\n{cfg['after_hours_message']}"
                actions.append("after_hours_notice")

            return self._finish(conn, conv_id, text, inbound_kind, reply, cfg,
                               actions, lang=lang, notify_owner=notify)
        finally:
            conn.close()

    # ------------------------------------------------------------ helpers

    def _transcribe_cached(self, conn, audio_bytes: bytes, cfg: dict,
                           actions: list) -> str:
        sha = cache_mod.audio_sha256(audio_bytes)
        hit = cache_mod.get_transcript(conn, sha)
        if hit:
            actions.append("transcript_cache_hit")
            return hit
        hint = "ur" if cfg["default_language"] != "en" else "en"
        try:
            text = (self.transcriber(audio_bytes, hint) or "").strip()
        except groq_client.GroqRateLimited:
            actions.append("stt_rate_limited")
            return ""
        except Exception:  # noqa: BLE001 - transcription is best-effort
            actions.append("stt_failed")
            return ""
        if text:
            cache_mod.save_transcript(conn, sha, text)
            actions.append("transcribed")
        return text

    def _finish(self, conn, conv_id: int, in_text: str, inbound_kind: str,
                reply: str, cfg: dict, actions: list, lang: str,
                notify_owner: str | None = None) -> EngineResult:
        dbmod.add_message(conn, conv_id, "out", "text", reply, lang)
        audio = None
        if inbound_kind == "audio" and reply:
            audio = self._tts_cached(reply, cfg["tts_voice"], actions)
            if audio:
                dbmod.add_message(conn, conv_id, "out", "audio",
                                  f"[voice reply] {reply}", lang)
        return EngineResult(reply_text=reply, reply_audio=audio,
                            lang=lang, actions=actions,
                            notify_owner=notify_owner)

    def _tts_cached(self, text: str, voice: str, actions: list) -> bytes | None:
        hit = self.tts_cache.get(text, voice)
        if hit:
            actions.append("tts_cache_hit")
            return hit
        try:
            data = self.tts_fn(text, voice)
        except groq_client.GroqRateLimited:
            actions.append("tts_rate_limited")
            return None
        except Exception:  # noqa: BLE001 - TTS failure falls back to text
            actions.append("tts_failed")
            return None
        if data:
            self.tts_cache.put(text, voice, data)
            actions.append("tts_synthesized")
        else:
            actions.append("tts_skipped")
        return data or None

    # ------------------------------------------------------- booking flow

    def _handle_booking_intent(self, conn, conv, text: str, lang: str,
                               cfg: dict, now: datetime,
                               sender_phone: str) -> tuple[str, list]:
        actions = ["booking_intent"]
        parsed = booking_mod.parse_appointment_request(text, now, cfg)
        if parsed is None:
            actions.append("no_datetime")
            return _t("ask_day", lang), actions, None
        if parsed["partial"]:
            actions.append("partial_datetime")
            if not parsed["time_text"]:
                return _t("ask_time", lang), actions, None
            return _t("ask_day", lang), actions, None

        start, end = parsed["start"], parsed["end"]
        svc = parsed["service"]
        svc_name = svc["name"] if svc else cfg["services"][0]["name"]

        free, reason = booking_mod.is_slot_free(conn, cfg, start, end)
        if not free:
            actions.append(f"slot_unavailable:{reason}")
            alts = booking_mod.suggest_alternatives(
                conn, cfg, start, parsed["duration_min"], n=3, now=now)
            if not alts:
                return _t("clarify", lang), actions, None
            dbmod.set_pending(conn, conv["id"], {
                "kind": "slot_choice",
                "alternatives": [a.isoformat() for a in alts],
                "service": svc_name,
                "duration_min": parsed["duration_min"],
            })
            return _slot_taken(lang, alts), actions, None

        booking_id = dbmod.insert_booking(
            conn, cfg["id"], conv["customer_name"], sender_phone,
            svc_name, start.isoformat(), end.isoformat(), status="pending")
        actions.append("booking_created_pending")
        pending = {"kind": "confirm", "booking_id": booking_id,
                   "start": start.isoformat(), "end": end.isoformat(),
                   "service": svc_name}
        slot_txt = booking_mod.format_slot(start, lang)
        if cfg["booking"]["require_name_phone"] and not (
                conv["customer_name"] and leads_mod.extract_phones(text)):
            dbmod.set_pending(conn, conv["id"], {**pending, "kind": "details"})
            return _t("need_name_phone", lang, slot=slot_txt, service=svc_name), actions, None
        dbmod.set_pending(conn, conv["id"], pending)
        return _t("confirm_ask", lang, slot=slot_txt, service=svc_name), actions, None

    def _handle_confirm(self, conn, conv, pending: dict, text: str,
                        lang: str, cfg: dict, now: datetime) -> tuple[str, list]:
        actions: list[str] = []
        norm = booking_mod.normalize(text)
        booking_id = pending["booking_id"]
        if any(re.search(rf"\b{re.escape(w)}\b", norm) for w in AFFIRM if w.isascii()) \
                or any(w in text for w in AFFIRM if not w.isascii()):
            dbmod.update_booking_status(conn, booking_id, "confirmed")
            dbmod.set_pending(conn, conv["id"], None)
            actions.append("booking_confirmed")
            start = datetime.fromisoformat(pending["start"])
            bk = conn.execute("SELECT * FROM bookings WHERE id=?",
                              (booking_id,)).fetchone()
            owner_msg = (
                f"New booking confirmed for {cfg['name']}: "
                f"{pending['service']} at "
                f"{booking_mod.format_slot(start, 'en')} — "
                f"{bk['customer_name'] or 'unknown'} ({bk['customer_phone']})."
            )
            return _t("confirmed", lang, service=pending["service"],
                      slot=booking_mod.format_slot(start, lang)), actions, owner_msg
        if any(re.search(rf"\b{re.escape(w)}\b", norm) for w in DENY if w.isascii()) \
                or any(w in text for w in DENY if not w.isascii()):
            dbmod.update_booking_status(conn, booking_id, "cancelled")
            dbmod.set_pending(conn, conv["id"], None)
            actions.append("booking_cancelled")
            return _t("cancelled", lang), actions, None
        # Maybe they proposed a new time -> try reschedule.
        parsed = booking_mod.parse_appointment_request(text, now, cfg)
        if parsed and not parsed["partial"]:
            start, end = parsed["start"], parsed["end"]
            free, _ = booking_mod.is_slot_free(conn, cfg, start, end)
            if free:
                dbmod.update_booking_time(conn, booking_id,
                                          start.isoformat(), end.isoformat())
                dbmod.set_pending(conn, conv["id"], pending)
                actions.append("booking_rescheduled")
                return _t("confirm_ask", lang, service=pending["service"],
                          slot=booking_mod.format_slot(start, lang)), actions, None
            actions.append("reschedule_conflict")
            return _t("clarify", lang), actions, None
        return _t("confirm_ask", lang, service=pending["service"],
                  slot=booking_mod.format_slot(
                      datetime.fromisoformat(pending["start"]), lang)), actions, None

    def _handle_slot_choice(self, conn, conv, pending: dict, text: str,
                            lang: str, cfg: dict, now: datetime) -> tuple[str, list]:
        actions: list[str] = []
        alts = [datetime.fromisoformat(a) for a in pending["alternatives"]]
        choice: datetime | None = None
        m = re.search(r"\b([123])\b", text)
        if m:
            idx = int(m.group(1)) - 1
            if idx < len(alts):
                choice = alts[idx]
        if choice is None:
            parsed = booking_mod.parse_appointment_request(text, now, cfg)
            if parsed and not parsed["partial"]:
                choice = parsed["start"]
        if choice is None:
            return _slot_taken(lang, alts), actions, None
        duration = pending["duration_min"]
        end = choice + booking_mod.timedelta(minutes=duration)
        free, _ = booking_mod.is_slot_free(conn, cfg, choice, end)
        if not free:
            actions.append("choice_taken")
            return _slot_taken(lang, alts), actions, None
        booking_id = dbmod.insert_booking(
            conn, cfg["id"], conv["customer_name"], conv["customer_phone"],
            pending["service"], choice.isoformat(), end.isoformat(),
            status="pending")
        actions.append("booking_created_pending")
        new_pending = {"kind": "confirm", "booking_id": booking_id,
                       "start": choice.isoformat(), "end": end.isoformat(),
                       "service": pending["service"]}
        slot_txt = booking_mod.format_slot(choice, lang)
        if cfg["booking"]["require_name_phone"] and not conv["customer_name"]:
            dbmod.set_pending(conn, conv["id"], {**new_pending, "kind": "details"})
            return _t("need_name_phone", lang, slot=slot_txt,
                      service=pending["service"]), actions, None
        dbmod.set_pending(conn, conv["id"], new_pending)
        return _t("confirm_ask", lang, slot=slot_txt,
                  service=pending["service"]), actions, None

    def _handle_details(self, conn, conv, pending: dict, text: str,
                        lang: str, cfg: dict, sender_phone: str) -> tuple[str, list]:
        actions: list[str] = []
        phones = leads_mod.extract_phones(text)
        name = leads_mod.extract_name(text) or conv["customer_name"]
        if name:
            dbmod.update_conversation(conn, conv["id"], customer_name=name)
        if phones or name:
            conn.execute("UPDATE bookings SET customer_name=COALESCE(?, customer_name),"
                         " customer_phone=? WHERE id=?",
                         (name, phones[0] if phones else sender_phone,
                          pending["booking_id"]))
            conn.commit()
            leads_mod.capture_from_message(conn, cfg["id"], sender_phone, text)
            actions.append("details_captured")
        if not name or not phones:
            # still missing something -> ask again (keep pending)
            return _t("need_name_phone", lang,
                      slot=booking_mod.format_slot(
                          datetime.fromisoformat(pending["start"]), lang),
                      service=pending["service"]), actions, None
        pending = {**pending, "kind": "confirm"}
        dbmod.set_pending(conn, conv["id"], pending)
        return _t("confirm_ask", lang, service=pending["service"],
                  slot=booking_mod.format_slot(
                      datetime.fromisoformat(pending["start"]), lang)), actions, None

    # ------------------------------------------------------------- llm chat

    def _system_prompt(self, cfg: dict) -> str:
        lines = [
            f"You are the AI receptionist for {cfg['name']} in {cfg['city']}.",
            "Reply in the SAME language as the customer: Urdu script if they write "
            "Urdu script, Roman Urdu if they write Roman Urdu, English if English.",
            "Keep replies short (1-3 sentences), warm and professional.",
            "Use ONLY the business info below. Never invent prices, timings or services.",
            "If you don't know something, say the owner will call them back.",
            "Never ask for CNIC, passwords, or card details.",
            "",
            "Services:",
        ]
        for s in cfg["services"]:
            lines.append(f"- {s['name']}: Rs {s['price_pkr']:,}, {s['duration_min']} min")
        lines.append("")
        lines.append("Hours:")
        for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            h = cfg["hours"][d]
            lines.append(f"- {d}: {'closed' if h == 'closed' else h['open'] + '-' + h['close']}")
        lines.append(f"Location: {cfg['location']}")
        if cfg.get("faqs"):
            lines.append("FAQs:")
            for f in cfg["faqs"]:
                lines.append(f"Q: {f['q']}\nA: {f['a']}")
        return "\n".join(lines)

    def _handle_chat(self, conn, conv_id: int, text: str, lang: str,
                     cfg: dict) -> tuple[str, list]:
        actions = ["llm_chat"]
        history = dbmod.recent_messages(conn, conv_id, limit=10)
        messages = [{"role": "system", "content": self._system_prompt(cfg)}]
        for m in history[:-1]:  # exclude the inbound message just stored
            role = "user" if m["direction"] == "in" else "assistant"
            body = m["body"]
            if m["kind"] == "audio" and m["direction"] == "in":
                body = f"[voice note transcript] {body}"
            messages.append({"role": role, "content": body})
        messages.append({"role": "user", "content": text})
        try:
            reply = self.llm_chat(messages)
        except groq_client.GroqRateLimited:
            actions.append("llm_rate_limited")
            return _t("busy", lang), actions, None
        except Exception:  # noqa: BLE001 - LLM failure degrades gracefully
            actions.append("llm_failed")
            return _t("busy", lang), actions, None
        return reply.strip(), actions, None

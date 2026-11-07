"""Conversational LLM Service for Custom Voice Agents.

Features:
- Primary: Groq Cloud (qwen/qwen3.8-27b) with ~80ms TTFT
- Fallback: OpenRouter free models (nvidia/nemotron-3.5-lightning:free)
- Generates bilingual output:
  1. 'roman_urdu': Natural conversational Roman Urdu with familiar English loanwords for UI chat display
  2. 'urdu_script': Native Nastaliq Urdu script with proper phonetic spelling for authentic Pakistani speech synthesis
- Configurable agent name, business domain, and operations overview
- Strict Zero-Hallucination Guardrail: Enforces user-defined fallback response when requested info is unknown
- Detects booking/order confirmation and produces structured transaction data for paper receipt generation
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
import httpx

log = logging.getLogger("llm_service")

# Auto-load .env
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            if _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def build_system_prompt(profile: dict) -> str:
    """Builds a dynamic, authentic Pakistani business prompt with zero-hallucination fallback rules."""
    agent_name = profile.get("agent_name") or profile.get("receptionist_name", "Zoya")
    biz_name = profile.get("name") or profile.get("business_name", "Hamara Business")
    category = profile.get("category", "General Service")
    description = profile.get("description", "Customer service and client consultations.")
    hours = profile.get("hours", "10:00 AM se 9:00 PM")
    location = profile.get("location", "Lahore, Pakistan")
    services = profile.get("services", [])
    fallback_response = profile.get(
        "fallback_response",
        "Main is baare mein abhi confirm nahi bata sakti ji, main management se pooch kar aap ko update karti hoon."
    )
    tone = profile.get("tone", "warm_punjabi")

    services_text = ""
    for s in services:
        services_text += f"- {s.get('name')}: Rs {s.get('price_pkr', 1500)} ({s.get('duration_min', 30)} mins)\n"

    tone_instruction = """
- Tone: Warm, hospitable Pakistani everyday conversational style (e.g. 'Ji haan ji', 'Bilkul ji', 'Koi masla hi nahi ji', 'Aap tashreef le aayein', 'Fikar na karein ji').
- NEVER use bookish or archaic textbook words like 'Khushamdeed', 'Tashkhees', 'Auqaat-e-kar', or 'Nisbat'.
- People in Pakistan naturally mix standard everyday English loanwords: appointment, booking, timing, charges, fees, checkup, slot, location, confirm, available, discount.
"""
    if tone == "professional_formal":
        tone_instruction = """
- Tone: Polite, courteous corporate Urdu (e.g. 'G bilkul', 'Theek hai ji', 'Zaroor', 'Aap tashreef le aayein').
- Professional yet casual and natural. NEVER use stiff poetic words like 'Khushamdeed'.
- Use standard business terms: appointment, timing, charges, confirmation, address.
"""
    elif tone == "modern_bilingual":
        tone_instruction = """
- Tone: Modern urban Pakistani conversational style (natural Urdu blended smoothly with standard English words like appointment, timing, charges, doctor, confirmed, slot, weekend).
- Casual, friendly, direct. No textbook formalities.
"""

    prompt = f"""You are {agent_name}, the front-desk phone receptionist for "{biz_name}" ({category}) located in {location}.

ABOUT OUR BUSINESS & OPERATIONS:
{description}

OPERATING HOURS:
{hours}

OUR VERIFIED SERVICES & PRICING (PKR):
{services_text if services_text else "- General Consultation & Services: Rs 1,500"}

CRITICAL PERSONA & LANGUAGE RULES:
1. Spoken Language & Dialect:
   {tone_instruction}
2. Phone Brevity:
   - Keep answers to 1 or 2 short, spoken telephone sentences (under 22 words).
   - Talk exactly like a friendly human answering the business phone in Pakistan.
3. STRICT ZERO-HALLUCINATION GUARDRAIL:
   - You ONLY know the business details, services, prices, and hours listed above.
   - If the caller asks for information, services, or products NOT listed above (for example: asking a clinic for pizza/burgers, or unverified discounts), you MUST NOT guess or invent answers.
   - Respond with this exact fallback: "{fallback_response}"
4. TRANSACTION & RECEIPT TRIGGER:
   - If the caller agrees to book an appointment, confirms a visit, or places an order, set "booking_confirmed": true and include confirmed item names.
5. STRICT JSON OUTPUT FORMAT (always provide both keys):
   {{
     "roman_urdu": "Natural everyday Roman Urdu for the screen (e.g. Ji haan ji bilkul, kal shaam 5 baje ka slot available hai. Main aap ki booking confirm kar doon?)",
     "urdu_script": "Same reply in 100% PURE Urdu Nastaliq script for authentic Pakistani speech synthesis. NEVER include ANY English Latin letters (A-Z, a-z). Transliterate all brand names, services, and numbers directly into Urdu script (e.g. سمائل کیئر for SmileCare, زویا for Zoya, اسکیلنگ for Scaling, پانچ بجے for 5 PM).",
     "booking_confirmed": false,
     "confirmed_items": []
   }}
"""
    return prompt.strip()


def _parse_bilingual_response(raw_text: str) -> tuple[str, str, dict]:
    """Parse JSON or fallback to text, returning (roman_urdu, urdu_script, metadata)."""
    from app.voice_service import normalize_urdu_phonetics_for_tts

    raw_text = raw_text.strip()
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            roman = data.get("roman_urdu", "").strip()
            urdu = data.get("urdu_script", "").strip()
            if roman:
                pure_urdu = normalize_urdu_phonetics_for_tts(urdu or roman)
                return roman, pure_urdu, data
    except Exception:
        pass
    pure_fallback = normalize_urdu_phonetics_for_tts(raw_text)
    return raw_text, pure_fallback, {}


async def generate_dynamic_greeting(profile: dict) -> tuple[str, str]:
    """Generates an authentic, conversational Pakistani phone greeting without 'Khushamdeed'."""
    agent_name = profile.get("agent_name") or profile.get("receptionist_name", "Zoya")
    biz_name = profile.get("name") or profile.get("business_name", "Hamara Business")
    category = profile.get("category", "Clinic")
    location = profile.get("location", "Lahore")

    # Transliterate business name and agent name to pure Urdu script to prevent American TTS accent
    from app.voice_service import normalize_urdu_phonetics_for_tts
    biz_urdu = normalize_urdu_phonetics_for_tts(biz_name)
    agent_urdu = normalize_urdu_phonetics_for_tts(agent_name)

    prompt = f"""Generate a warm, natural 1-sentence Pakistani phone greeting from {agent_name} for "{biz_name}" ({category}) in {location}.
Rules:
- NEVER say "Khushamdeed" or "Welcome". Real Pakistanis say: "Assalam-o-Alaikum ji! [Biz], [Name] baat kar rahi hoon. Ji batayein, kya madad kar sakti hoon?"
- Keep it under 18 words.
- In "urdu_script", write the business name as "{biz_urdu}" and agent name as "{agent_urdu}". Absolutely ZERO Latin letters (A-Z) allowed in urdu_script.
Output JSON:
{{
  "roman_urdu": "Assalam-o-Alaikum ji! {biz_name} se {agent_name} baat kar rahi hoon. Ji batayein, kis cheez mein help chahiye?",
  "urdu_script": "السلام علیکم جی! {biz_urdu} سے {agent_urdu} بات کر رہی ہوں۔ جی بتائیں، کس چیز میں مدد چاہیے؟"
}}"""

    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.65,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.post(GROQ_ENDPOINT, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    r, u, _ = _parse_bilingual_response(content)
                    if r and "khush" not in r.lower():
                        # Enforce pure Urdu script on u
                        u_pure = normalize_urdu_phonetics_for_tts(u)
                        return r, u_pure
        except Exception as e:
            log.warning("Dynamic greeting LLM failed: %s", e)

    # Authentic everyday Pakistani phone greeting fallback with pure Urdu script
    r = f"Assalam-o-Alaikum ji! {biz_name} se {agent_name} baat kar rahi hoon. Ji batayein, kis cheez mein help chahiye?"
    u = f"السلام علیکم جی! {biz_urdu} سے {agent_urdu} بات کر رہی ہوں۔ جی بتائیں، کس چیز میں مدد چاہیے؟"
    return r, u


async def generate_response(
    messages: list[dict], profile: dict
) -> tuple[str, str, dict]:
    """Generate conversational reply returning (roman_urdu, urdu_script, metadata)."""
    system_prompt = build_system_prompt(profile)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # 1. Primary: Groq Cloud (sub-100ms TTFT)
    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": full_messages,
                "temperature": 0.6,
                "max_tokens": 200,
                "response_format": {"type": "json_object"},
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(GROQ_ENDPOINT, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    return _parse_bilingual_response(content)
                else:
                    log.warning("Groq error %d: %s", res.status_code, res.text[:200])
        except Exception as e:
            log.warning("Groq call failed: %s", e)

    # 2. Fallback: OpenRouter Free Tier
    if OPENROUTER_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": OPENROUTER_MODEL,
                "messages": full_messages,
                "temperature": 0.6,
                "max_tokens": 200,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(OPENROUTER_ENDPOINT, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    return _parse_bilingual_response(content)
        except Exception as e:
            log.error("OpenRouter fallback failed: %s", e)

    # Last resort fallback response
    fb = profile.get(
        "fallback_response",
        "Main is baare mein abhi confirm nahi bata sakti ji, main management se pooch kar aap ko update karti hoon."
    )
    fb_urdu = "میں اس بارے میں ابھی کنفرم نہیں بتا سکتی جی، میں مینجمنٹ سے پوچھ کر آپ کو اپڈیٹ کرتی ہوں۔"
    return fb, fb_urdu, {}

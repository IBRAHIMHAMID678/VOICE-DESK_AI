"""Conversational LLM Service for Custom Voice Agents.

Features:
- Primary: Groq Cloud (qwen/qwen3.8-27b) with ~80ms TTFT
- Fallback: OpenRouter free models (nvidia/nemotron-3.5-lightning:free)
- Generates bilingual output:
  1. 'roman_urdu': Natural Roman Urdu with familiar English loanwords for UI display
  2. 'urdu_script': Native Urdu script for authentic Pakistani/Punjabi speech synthesis
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
    """Builds a dynamic, business-tailored prompt with zero-hallucination fallback rules."""
    agent_name = profile.get("agent_name") or profile.get("receptionist_name", "Representative")
    biz_name = profile.get("name", "Hamara Business")
    category = profile.get("category", "General Service")
    description = profile.get("description", "Customer service and client consultations.")
    hours = profile.get("hours", "10:00 AM se 9:00 PM")
    location = profile.get("location", "Pakistan")
    services = profile.get("services", [])
    fallback_response = profile.get(
        "fallback_response",
        "Main is baare mein abhi confirm nahi bata sakti ji, main management se pooch kar aap ko update karti hoon."
    )
    tone = profile.get("tone", "warm_punjabi")

    services_text = ""
    for s in services:
        services_text += f"- {s.get('name')}: Rs {s.get('price_pkr', 'Munasib')} ({s.get('duration_min', 30)} mins)\n"

    tone_instruction = "Use natural, respectful Pakistani hospitality with warmth ('Ji haan ji', 'Bilkul ji', 'Koi masla hi nahi ji', 'G zaroor')."
    if tone == "professional_formal":
        tone_instruction = "Maintain a courteous, highly professional, polished Urdu corporate tone ('G bilkul', 'Tashreef layen', 'Khush-aamdeed')."
    elif tone == "modern_bilingual":
        tone_instruction = "Speak in modern urban Pakistani conversational style (natural Urdu blended with standard English business terms like appointment, timing, discount, confirmed)."

    prompt = f"""You are {agent_name}, the front-desk representative and phone agent for "{biz_name}" ({category}) located in {location}.

ABOUT OUR BUSINESS & OPERATIONS:
{description}

OPERATING HOURS:
{hours}

OUR VERIFIED SERVICES & PRICING (PKR):
{services_text if services_text else "- General Consultation & Services: Rs 1,500"}

CRITICAL BEHAVIOR & PERSONA RULES:
1. Tone: {tone_instruction}
2. Brevity for Voice:
   - Keep replies to 1-2 concise, spoken sentences (under 24 words).
   - Talk like a real human on a telephone call, not an essay generator.
3. STRICT ZERO-HALLUCINATION GUARDRAIL:
   - You ONLY know the business details, services, prices, and hours listed above.
   - If the caller asks for information, products, policies, or medical/legal advice NOT mentioned above, DO NOT make up answers or guess.
   - Respond with this fallback: "{fallback_response}"
4. TRANSACTION & RECEIPT TRIGGER:
   - If the caller agrees to book an appointment, order an item, or confirms a service, set "booking_confirmed": true and include the item details.
5. STRICT JSON OUTPUT FORMAT:
   {{
     "roman_urdu": "Natural Roman Urdu reply for reading on screen",
     "urdu_script": "The exact same reply in proper Urdu script for native phonetic speech",
     "booking_confirmed": false,
     "confirmed_items": []
   }}
"""
    return prompt.strip()


def _parse_bilingual_response(raw_text: str) -> tuple[str, str, dict]:
    """Parse JSON or fallback to text, returning (roman_urdu, urdu_script, metadata)."""
    raw_text = raw_text.strip()
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            roman = data.get("roman_urdu", "").strip()
            urdu = data.get("urdu_script", "").strip()
            if roman:
                return roman, urdu or roman, data
    except Exception:
        pass
    return raw_text, raw_text, {}


async def generate_dynamic_greeting(profile: dict) -> tuple[str, str]:
    """Generates an authentic, dynamic greeting customized to the business and agent name."""
    agent_name = profile.get("agent_name") or profile.get("receptionist_name", "Representative")
    biz_name = profile.get("name", "Hamara Business")
    category = profile.get("category", "Service")
    location = profile.get("location", "Lahore")

    prompt = f"""Generate a lively, warm 1-sentence opening greeting from {agent_name} for "{biz_name}" ({category}) in {location}.
Output JSON:
{{
  "roman_urdu": "Salam ji! {biz_name} mein khush-aamdeed. Main {agent_name} baat kar rahi hoon, ji batayein kis cheez mein madad kar sakti hoon?",
  "urdu_script": "سلام جی! {biz_name} میں خوش آمدید۔ میں {agent_name} بات کر رہی ہوں، جی بتائیں کس چیز میں مدد کر سکتی ہوں؟"
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
                "temperature": 0.7,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.post(GROQ_ENDPOINT, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    r, u, _ = _parse_bilingual_response(content)
                    return r, u
        except Exception as e:
            log.warning("Dynamic greeting LLM failed: %s", e)

    # Fallback
    r = f"Salam ji! {biz_name} mein khush-aamdeed. Main {agent_name} baat kar raha hoon, ji kahiye kis tarah madad kar sakta hoon?"
    u = f"سلام جی! {biz_name} میں خوش آمدید۔ میں {agent_name} بات کر رہا ہوں، جی کہیے کس طرح مدد کر سکتا ہوں؟"
    return r, u


async def generate_response(
    messages: list[dict], profile: dict
) -> tuple[str, str, dict]:
    """Generate conversational reply returning (roman_urdu, urdu_script, metadata)."""
    system_prompt = build_system_prompt(profile)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # 1. Primary: Groq Cloud (~80ms TTFT)
    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": full_messages,
                "temperature": 0.65,
                "max_tokens": 160,
                "response_format": {"type": "json_object"},
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(GROQ_ENDPOINT, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    return _parse_bilingual_response(content)
                else:
                    log.warning("Groq error %s: %s", res.status_code, res.text[:200])
        except Exception as e:
            log.warning("Groq inference failed: %s, falling back to OpenRouter", e)

    # 2. Fallback: OpenRouter Free Models
    if OPENROUTER_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/IBRAHIMHAMID678/urdu-voice-receptionist",
                "X-Title": "Voice Agent Platform",
            }
            payload = {
                "model": OPENROUTER_MODEL,
                "messages": full_messages,
                "temperature": 0.6,
                "max_tokens": 160,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(OPENROUTER_ENDPOINT, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    return _parse_bilingual_response(content)
        except Exception as e:
            log.error("OpenRouter fallback failed: %s", e)

    # 3. Emergency static fallback
    r = "Ji bilkul ji, main samajh gaya. Kahiye kis din aur waqt appointment confirm kar doon?"
    u = "جی بالکل جی، میں سمجھ گیا۔ کہیے کس دن اور وقت اپائنٹمنٹ کنفرم کر دوں؟"
    return r, u, {}

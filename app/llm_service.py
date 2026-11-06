"""Ultra-fast Conversational LLM Service for Live Voice Calls.

Features:
- Primary: Groq Cloud (qwen/qwen3.8-27b) with ~80ms TTFT
- Fallback: OpenRouter free models (nvidia/nemotron-3.5-lightning:free)
- Generates bilingual output:
  1. 'roman_urdu': Natural Roman Urdu with English loanwords for UI display
  2. 'urdu_script': Native Urdu script for authentic Pakistani/Punjabi phonetic speech synthesis
- Natural Lahori / Punjabi warmth ('Ji haan ji', 'Bilkul ji', 'Koi masla hi nahi ji')
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


def build_system_prompt(business_profile: dict) -> str:
    """Builds an authentic, dynamic Pakistani Punjabi/Lahori receptionist prompt."""
    name = business_profile.get("name", "Hamara Clinic / Business")
    category = business_profile.get("category", "General Service")
    hours = business_profile.get("hours", "11:00 AM se 9:00 PM")
    location = business_profile.get("location", "Pakistan")
    services = business_profile.get("services", [])
    receptionist_name = business_profile.get("receptionist_name", "Ayesha")

    services_text = ""
    for s in services:
        services_text += f"- {s.get('name')}: Rs {s.get('price_pkr', 'Munasib')} ({s.get('duration_min', 30)} mins)\n"

    prompt = f"""You are {receptionist_name}, the warm, polite, native Pakistani front-desk receptionist for "{name}" ({category}) in {location}.
Operating Hours: {hours}

Our Services & Pricing:
{services_text if services_text else "- Consultation & Services: Rs 1,500"}

CRITICAL PERSONA & DIALECT RULES:
1. Warm Pakistani Punjabi & Lahori hospitality:
   - Use natural local markers: "Ji haan ji", "Bilkul ji", "Koi masla hi nahi ji", "Acha ji", "Khairiyat ji", "Zaroor ji".
   - Be genuinely friendly, respectful, and helpful.
2. Brevity:
   - Maximum 1 to 2 short sentences (under 22 words total). Never monologue.
3. Accurate Business Answers:
   - Only quote the exact services, prices, and hours listed above.
4. Output Format:
   - You MUST output a strict JSON object with EXACTLY two fields:
     {{
       "roman_urdu": "Short natural Roman Urdu reply for reading",
       "urdu_script": "The exact same reply in proper Urdu script for native phonetic speech"
     }}
"""
    return prompt.strip()


def _parse_bilingual_response(raw_text: str) -> tuple[str, str]:
    """Parse JSON or fallback to text."""
    raw_text = raw_text.strip()
    try:
        # Match JSON block or direct JSON
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            roman = data.get("roman_urdu", "").strip()
            urdu = data.get("urdu_script", "").strip()
            if roman:
                return roman, urdu or roman
    except Exception:
        pass
    return raw_text, raw_text


async def generate_dynamic_greeting(business_profile: dict) -> tuple[str, str]:
    """Generates an authentic, dynamic greeting customized to the business."""
    name = business_profile.get("name", "Hamara Clinic")
    category = business_profile.get("category", "Service")
    location = business_profile.get("location", "Lahore")

    prompt = f"""Generate a lively, warm 1-sentence greeting from Ayesha (receptionist) for "{name}" ({category}) in {location}.
Output JSON format:
{{
  "roman_urdu": "Salam ji! {name} mein khush-aamdeed. Main Ayesha baat kar rahi hoon, ji kahiye kis cheez mein madad kar sakti hoon?",
  "urdu_script": "سلام جی! {name} میں خوش آمدید۔ میں عائشہ بات کر رہی ہوں، جی کہیے کس چیز میں مدد کر سکتی ہوں؟"
}}"""

    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
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
                    return _parse_bilingual_response(content)
        except Exception as e:
            log.warning("Dynamic greeting LLM failed: %s", e)

    # Fallback
    r = f"Salam ji! {name} mein khush-aamdeed. Main Ayesha baat kar rahi hoon, ji batayein kis tarah madad kar sakti hoon?"
    u = f"سلام جی! {name} میں خوش آمدید۔ میں عائشہ بات کر رہی ہوں، جی بتائیں کس طرح مدد کر سکتی ہوں؟"
    return r, u


async def generate_response(
    messages: list[dict], business_profile: dict
) -> tuple[str, str]:
    """Generate conversational reply returning (roman_urdu, urdu_script)."""
    system_prompt = build_system_prompt(business_profile)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # 1. Primary: Groq Cloud
    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
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
                "X-Title": "Voice Receptionist Demo",
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
                else:
                    log.warning("OpenRouter error %s: %s", res.status_code, res.text[:200])
        except Exception as e:
            log.error("OpenRouter fallback failed: %s", e)

    # 3. Emergency static fallback
    r = "Ji bilkul ji, main samajh gayi. Kahiye kis din aur time appointment confirm kar doon?"
    u = "جی بالکل جی، میں سمجھ گئی۔ کہیے کس دن اور ٹائم اپائنٹمنٹ کنفرم کر دوں؟"
    return r, u

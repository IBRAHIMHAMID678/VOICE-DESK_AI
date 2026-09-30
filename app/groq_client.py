"""Groq API wrapper: Whisper STT + LLM chat with model fallbacks.

Models (verified working):
  STT:  whisper-large-v3-turbo -> whisper-large-v3
  Chat: openai/gpt-oss-120b -> openai/gpt-oss-20b -> qwen/qwen3-32b

The API key is read from the GROQ_API_KEY environment variable at call time.
It is never written to any file, log, or output.

FREE-TIER POLICY: on HTTP 429 (rate limit) the client raises GroqRateLimited
immediately and does NOT try fallback models — retrying would only burn more
quota. Transient errors (timeouts, 5xx) get up to 3 attempts with exponential
backoff. Callers must degrade gracefully (templated reply, deferred work).
"""
from __future__ import annotations

import os
import time
from typing import Callable, Iterable, TypeVar

STT_MODELS = ["whisper-large-v3-turbo", "whisper-large-v3"]
CHAT_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3-32b"]

T = TypeVar("T")


class GroqRateLimited(RuntimeError):
    """Raised when Groq returns HTTP 429. Never retry-loop on this."""


def _is_rate_limit(exc: Exception) -> bool:
    return (
        getattr(exc, "status_code", None) == 429
        or exc.__class__.__name__ == "RateLimitError"
    )


def _is_transient(exc: Exception) -> bool:
    """Timeouts and 5xx are worth a short backoff; 4xx (except 429) are not."""
    if getattr(exc, "status_code", None) in (500, 502, 503, 504):
        return True
    name = exc.__class__.__name__
    return any(k in name for k in ("Timeout", "Connection", "Connect"))


def _with_backoff(fn: Callable[[], T], desc: str) -> T:
    """Run fn; retry transient failures with exponential backoff (max 3 tries).
    Rate limits raise GroqRateLimited immediately — never retried."""
    delay = 1.0
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - classified below
            if _is_rate_limit(e):
                raise GroqRateLimited(f"Groq rate limit (429) on {desc}; not retrying.")
            last_err = e
            if not _is_transient(e) or attempt == 2:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"{desc} failed after retries: {last_err}")


def _client():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Export it in your environment or .env file."
        )
    from groq import Groq
    return Groq(api_key=key)


def transcribe_audio(audio_bytes: bytes, language_hint: str = "ur",
                     filename: str = "voice-note.ogg") -> str:
    """Transcribe voice-note bytes with Groq Whisper. Returns plain text."""
    if not audio_bytes:
        raise ValueError("empty audio bytes")
    client = _client()
    last_err: Exception | None = None
    for model in STT_MODELS:
        try:
            def _do(m=model):
                resp = client.audio.transcriptions.create(
                    file=(filename, audio_bytes),
                    model=m,
                    language=language_hint,
                    response_format="text",
                )
                return resp.strip() if isinstance(resp, str) else str(resp).strip()
            text = _with_backoff(_do, f"whisper/{model}")
            if text:
                return text
            last_err = RuntimeError(f"{model} returned empty transcription")
        except GroqRateLimited:
            raise
        except Exception as e:  # noqa: BLE001 - fall through to next model
            last_err = e
    raise RuntimeError(f"all Whisper models failed: {last_err}")


def chat(messages: list[dict], temperature: float = 0.4,
         max_tokens: int = 400) -> str:
    """One chat completion with model fallbacks. Returns the reply text."""
    client = _client()
    last_err: Exception | None = None
    for model in CHAT_MODELS:
        try:
            def _do(m=model):
                resp = client.chat.completions.create(
                    model=m,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return (resp.choices[0].message.content or "").strip()
            text = _with_backoff(_do, f"chat/{model}")
            if text:
                return text
            last_err = RuntimeError(f"{model} returned empty completion")
        except GroqRateLimited:
            raise
        except Exception as e:  # noqa: BLE001 - fall through to next model
            last_err = e
    raise RuntimeError(f"all chat models failed: {last_err}")


def iter_models(kind: str) -> Iterable[str]:
    return STT_MODELS if kind == "stt" else CHAT_MODELS

"""Per-business JSON config loader with strict validation.

Adding a client = drop a new validated JSON file into businesses/ — zero code changes.
The engine only ever reads business data from these configs; nothing is hardcoded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALLOWED_LANGUAGES = {"ur", "roman_urdu", "en"}
ALLOWED_VOICES = {"ur-PK-GulNawazNeural", "ur-PK-AsadNeural"}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ConfigValidationError(ValueError):
    """Raised when a business config JSON is missing or has invalid fields."""


def _need(cfg: dict, field: str, where: str) -> Any:
    if field not in cfg or cfg[field] in (None, ""):
        raise ConfigValidationError(f"{where}: missing required field '{field}'")
    return cfg[field]


def validate_config(cfg: dict) -> dict:
    """Validate a business config dict in place. Returns it. Raises ConfigValidationError."""
    where = f"business config '{cfg.get('id', '?')}'"
    _need(cfg, "id", where)
    _need(cfg, "name", where)
    _need(cfg, "city", where)

    lang = _need(cfg, "default_language", where)
    if lang not in ALLOWED_LANGUAGES:
        raise ConfigValidationError(
            f"{where}: default_language must be one of {sorted(ALLOWED_LANGUAGES)}, got '{lang}'"
        )

    services = _need(cfg, "services", where)
    if not isinstance(services, list) or not services:
        raise ConfigValidationError(f"{where}: 'services' must be a non-empty list")
    for i, s in enumerate(services):
        for f in ("name", "price_pkr", "duration_min"):
            if f not in s:
                raise ConfigValidationError(f"{where}: services[{i}] missing '{f}'")
        if not isinstance(s["price_pkr"], (int, float)) or s["price_pkr"] < 0:
            raise ConfigValidationError(f"{where}: services[{i}].price_pkr must be >= 0")
        if not isinstance(s["duration_min"], int) or s["duration_min"] <= 0:
            raise ConfigValidationError(f"{where}: services[{i}].duration_min must be a positive int")
        s.setdefault("keywords", [])

    hours = _need(cfg, "hours", where)
    if not isinstance(hours, dict):
        raise ConfigValidationError(f"{where}: 'hours' must be an object keyed by weekday")
    for d in WEEKDAYS:
        if d not in hours:
            raise ConfigValidationError(f"{where}: hours missing weekday '{d}'")
        h = hours[d]
        if h == "closed":
            continue
        if not isinstance(h, dict) or "open" not in h or "close" not in h:
            raise ConfigValidationError(f"{where}: hours.{d} must be 'closed' or {{open, close}}")
        for k in ("open", "close"):
            v = h[k]
            if not isinstance(v, str) or len(v) != 5 or v[2] != ":":
                raise ConfigValidationError(f"{where}: hours.{d}.{k} must be 'HH:MM', got '{v}'")

    _need(cfg, "location", where)

    faqs = cfg.get("faqs", [])
    if not isinstance(faqs, list):
        raise ConfigValidationError(f"{where}: 'faqs' must be a list")
    for i, f in enumerate(faqs):
        if "q" not in f or "a" not in f:
            raise ConfigValidationError(f"{where}: faqs[{i}] must have 'q' and 'a'")

    booking = _need(cfg, "booking", where)
    for f in ("slot_minutes", "max_advance_days", "require_name_phone"):
        if f not in booking:
            raise ConfigValidationError(f"{where}: booking missing '{f}'")

    _need(cfg, "after_hours_message", where)
    _need(cfg, "owner_phone", where)

    voice = _need(cfg, "tts_voice", where)
    if voice not in ALLOWED_VOICES:
        raise ConfigValidationError(
            f"{where}: tts_voice must be one of {sorted(ALLOWED_VOICES)}, got '{voice}'"
        )

    # Optional: WhatsApp Cloud API phone_number_id this config listens on.
    cfg.setdefault("whatsapp_phone_number_id", None)
    return cfg


def load_config_file(path: str | Path) -> dict:
    """Load and validate one business JSON file."""
    path = Path(path)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigValidationError(f"{path.name}: invalid JSON: {e}")
    if not isinstance(cfg, dict):
        raise ConfigValidationError(f"{path.name}: top-level JSON must be an object")
    validate_config(cfg)
    return cfg


def load_all_configs(businesses_dir: str | Path) -> dict[str, dict]:
    """Load every *.json in businesses_dir. Raises on the first invalid file."""
    businesses_dir = Path(businesses_dir)
    configs: dict[str, dict] = {}
    for path in sorted(businesses_dir.glob("*.json")):
        cfg = load_config_file(path)
        if cfg["id"] in configs:
            raise ConfigValidationError(f"duplicate business id '{cfg['id']}' in {path.name}")
        configs[cfg["id"]] = cfg
    if not configs:
        raise ConfigValidationError(f"no business configs found in {businesses_dir}")
    return configs

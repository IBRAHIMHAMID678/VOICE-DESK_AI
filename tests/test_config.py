"""Config loader validation: good configs load, broken ones fail clearly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config as config_mod
from tests.conftest import make_test_config, ROOT


def test_load_shipped_configs():
    configs = config_mod.load_all_configs(ROOT / "businesses")
    assert set(configs) == {"smilecare-dental", "dha-estates"}
    dental = configs["smilecare-dental"]
    assert dental["city"] == "Islamabad"
    assert dental["tts_voice"] == "ur-PK-GulNawazNeural"
    estates = configs["dha-estates"]
    assert estates["city"] == "DHA Lahore"
    assert estates["tts_voice"] == "ur-PK-AsadNeural"


def test_load_single_file(tmp_path):
    p = tmp_path / "biz.json"
    p.write_text(json.dumps(make_test_config()), encoding="utf-8")
    cfg = config_mod.load_config_file(p)
    assert cfg["id"] == "test-biz"


def _expect_error(cfg, fragment):
    with pytest.raises(config_mod.ConfigValidationError) as e:
        config_mod.validate_config(cfg)
    assert fragment in str(e.value)


def test_missing_field():
    cfg = make_test_config()
    del cfg["owner_phone"]
    _expect_error(cfg, "owner_phone")


def test_bad_language():
    cfg = make_test_config()
    cfg["default_language"] = "french"
    _expect_error(cfg, "default_language")


def test_bad_voice():
    cfg = make_test_config()
    cfg["tts_voice"] = "en-US-JennyNeural"
    _expect_error(cfg, "tts_voice")


def test_missing_weekday_hours():
    cfg = make_test_config()
    del cfg["hours"]["sun"]
    _expect_error(cfg, "hours missing weekday 'sun'")


def test_bad_hours_format():
    cfg = make_test_config()
    cfg["hours"]["mon"] = {"open": "10", "close": "21:00"}
    _expect_error(cfg, "hours.mon.open")


def test_empty_services():
    cfg = make_test_config()
    cfg["services"] = []
    _expect_error(cfg, "services")


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(config_mod.ConfigValidationError) as e:
        config_mod.load_config_file(p)
    assert "invalid JSON" in str(e.value)

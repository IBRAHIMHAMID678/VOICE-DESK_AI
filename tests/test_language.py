"""Language detection: Urdu script, Roman Urdu, English."""
from __future__ import annotations

from app.language import detect_language


def test_urdu_script():
    assert detect_language("آپ کی کلینک کہاں واقع ہے؟") == "ur"
    assert detect_language("کل شام 5 بجے اپائنٹمنٹ چاہیے") == "ur"


def test_roman_urdu():
    assert detect_language("aap ki clinic kahan hai") == "roman_urdu"
    assert detect_language("kal shaam 5 baje appointment chahiye") == "roman_urdu"
    assert detect_language("Salam, mujhe daant mein dard hai") == "roman_urdu"


def test_english():
    assert detect_language("where is your clinic located?") == "en"
    assert detect_language("I would like to book an appointment for tomorrow") == "en"
    assert detect_language("What are your consultation charges?") == "en"


def test_mixed_leans_roman_urdu():
    # More Roman-Urdu content words than English ones.
    assert detect_language("Salam, I want appointment kal 5 baje") == "roman_urdu"


def test_empty_defaults_to_roman_urdu():
    assert detect_language("") == "roman_urdu"
    assert detect_language(None) == "roman_urdu"

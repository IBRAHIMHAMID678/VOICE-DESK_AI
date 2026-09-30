"""Real language detection for Urdu (Arabic script), Roman Urdu, and English.

Strategy:
  1. If a meaningful share of alphabetic characters are in Arabic-script Unicode
     ranges -> 'ur' (Urdu written in Urdu script).
  2. Otherwise score the text against Roman-Urdu and English keyword lists plus
     Roman-Urdu character/shape heuristics -> 'roman_urdu' or 'en'.
"""
from __future__ import annotations

import re

# Arabic-script Unicode blocks (covers Urdu, incl. presentation forms).
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")

ROMAN_URDU_WORDS = {
    # pronouns / common function words
    "mein", "main", "mai", "tum", "aap", "ap", "hum", "woh", "wo", "yeh", "ye",
    "ka", "ki", "ke", "ko", "se", "ne", "par", "tak", "bhi", "bhee", "or", "aur",
    # verbs / auxiliaries
    "hai", "hain", "hoon", "hun", "hon", "tha", "thi", "the", "hoga", "hogi",
    "karna", "karen", "karein", "karega", "karo", "kiye", "kia", "kiya", "huwa",
    "chahiye", "chahye", "chahta", "chahti", "chahe", "chahein",
    "sakta", "sakti", "sakte", "skti", "mil", "mila", "milega", "jana", "aana",
    # question / discourse words
    "kya", "kia", "kyun", "kaise", "kese", "kahan", "kab", "kitna", "kitne",
    "kaun", "kon", "nahi", "nahin", "nhe", "nhi", "haan", "han", "jee", "ji",
    "theek", "thik", "acha", "acha", "shukriya", "meherbani", "khuda", "hafiz",
    "salam", "assalam", "walekum", "alaikum",
    # time / booking vocabulary
    "baje", "bajay", "waqt", "time", "din", "aaj", "aj", "kal", "parson",
    "subah", "dopahar", "dopehar", "shaam", "sham", "raat",
    "appointment", "book", "booking", "confirm",
    # misc very common
    "koi", "kuch", "sab", "bohat", "bohut", "zyada", "kam", "mera", "meri",
    "mere", "tera", "teri", "tere", "apna", "apni", "hamara", "hamari",
    "naam", "number", "phone", "mobile", "dard", "daant", "daanton", "bimaar",
    "dawa", "doctor", "daktar", "clinic", "fees", "pese", "paisa", "qimat",
}

ENGLISH_WORDS = {
    "the", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "a", "an", "and", "or", "but", "if", "then", "because", "when", "where",
    "what", "which", "who", "how", "do", "does", "did", "have", "has", "had",
    "will", "would", "can", "could", "should", "please", "thanks", "thank",
    "hello", "hi", "hey", "good", "morning", "evening", "appointment",
    "schedule", "available", "want", "need", "like", "know", "visit",
    "price", "cost", "much", "many", "today", "tomorrow", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
}

# Character n-gram-ish heuristics typical of Roman Urdu: doubled vowels,
# 'oo'/'ee' spellings, trailing 'h' emphatics, 'gh'/'kh' clusters.
_ROMAN_SHAPE_RES = [
    re.compile(r"\b\w*(aa|ee|oo)\w*\b"),          # doubled vowels: aana, deekh
    re.compile(r"\b\w*(gh|kh|chh|bh|dh|jh|ph|thh)\w*\b"),  # aspirates
]


def _word_hits(text: str, vocab: set[str]) -> int:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return 0
    return sum(1 for w in words if w in vocab)


def detect_language(text: str | None) -> str:
    """Return 'ur', 'roman_urdu', or 'en' for the given text."""
    if not text or not text.strip():
        return "roman_urdu"  # safest default for a Pakistan business

    letters = re.findall(r"[^\W\d_]", text, flags=re.UNICODE)
    if letters:
        arabic = sum(1 for ch in letters if _ARABIC_RE.match(ch))
        if arabic / len(letters) >= 0.25:
            return "ur"

    roman_hits = _word_hits(text, ROMAN_URDU_WORDS)
    english_hits = _word_hits(text, ENGLISH_WORDS)

    # Character-shape heuristics break ties toward Roman Urdu.
    shape_hits = sum(len(rx.findall(text.lower())) for rx in _ROMAN_SHAPE_RES)
    roman_score = roman_hits + 0.5 * shape_hits
    english_score = english_hits

    # "appointment"/"booking"/"time"/"book" counted for both sides above;
    # pure-English sentences still win clearly on function words.
    if english_score > roman_score:
        return "en"
    if roman_score > 0:
        return "roman_urdu"
    # No signal: if Latin letters present assume English, else Roman Urdu.
    return "en" if re.search(r"[a-zA-Z]", text) else "roman_urdu"

"""Frugality caches: transcript cache (SQLite) + TTS cache (disk, size-capped)."""
from __future__ import annotations

from app import cache as cache_mod
from app import db as dbmod


def test_transcript_cache_roundtrip(db_path):
    conn = dbmod.connect(db_path)
    try:
        assert cache_mod.get_transcript(conn, "abc123") is None
        cache_mod.save_transcript(conn, "abc123", "kal paanch baje")
        assert cache_mod.get_transcript(conn, "abc123") == "kal paanch baje"
        stats = cache_mod.transcript_cache_stats(conn)
        assert stats["rows"] == 1
    finally:
        conn.close()


def test_transcript_cache_prunes_to_cap(db_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "MAX_TRANSCRIPT_ROWS", 3)
    conn = dbmod.connect(db_path)
    try:
        for i in range(5):
            cache_mod.save_transcript(conn, f"sha{i}", f"text{i}")
        assert cache_mod.transcript_cache_stats(conn)["rows"] == 3
        # Newest survive.
        assert cache_mod.get_transcript(conn, "sha4") == "text4"
        assert cache_mod.get_transcript(conn, "sha0") is None
    finally:
        conn.close()


def test_tts_cache_roundtrip(tmp_path):
    c = cache_mod.TTSCache(tmp_path / "tts")
    assert c.get("salam", "ur-PK-GulNawazNeural") is None
    c.put("salam", "ur-PK-GulNawazNeural", b"MP3DATA")
    assert c.get("salam", "ur-PK-GulNawazNeural") == b"MP3DATA"
    # Different voice = different entry.
    assert c.get("salam", "ur-PK-AsadNeural") is None
    stats = c.stats()
    assert stats["files"] == 1 and stats["bytes"] == 7


def test_tts_cache_evicts_oldest_when_over_cap(tmp_path):
    c = cache_mod.TTSCache(tmp_path / "tts", max_bytes=20)
    c.put("one", "v", b"1234567890")     # 10 bytes
    c.put("two", "v", b"1234567890")     # 20 bytes total, at cap
    c.get("one", "v")                     # touch "one" -> most recently used
    c.put("three", "v", b"1234567890")   # 30 bytes -> evict least-recent ("two")
    assert c.get("one", "v") == b"1234567890"
    assert c.get("two", "v") is None
    assert c.get("three", "v") == b"1234567890"


def test_audio_sha256_stable():
    assert cache_mod.audio_sha256(b"abc") == cache_mod.audio_sha256(b"abc")
    assert cache_mod.audio_sha256(b"abc") != cache_mod.audio_sha256(b"abd")

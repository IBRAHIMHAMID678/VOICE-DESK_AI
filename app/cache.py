"""Frugality caches: avoid repeat paid/free-tier API calls.

- TranscriptCache: SQLite table keyed by sha256(audio bytes). The same voice
  note (or a re-sent one) is never transcribed twice.
- TTSCache: on-disk MP3 files keyed by sha256(voice + text), with a size cap
  and LRU eviction. Repeated phrases (greetings, confirmations, FAQ answers)
  are synthesized once and reused.

Both are consulted by the engine before any network call.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from app import db as dbmod


def audio_sha256(audio: bytes) -> str:
    return hashlib.sha256(audio).hexdigest()


def tts_key(text: str, voice: str) -> str:
    return hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()


# ---- transcript cache (SQLite) ---------------------------------------------

MAX_TRANSCRIPT_ROWS = 500


def get_transcript(conn: sqlite3.Connection, audio_sha: str) -> str | None:
    row = conn.execute(
        "SELECT text FROM transcript_cache WHERE audio_sha=?", (audio_sha,)
    ).fetchone()
    return row["text"] if row else None


def save_transcript(conn: sqlite3.Connection, audio_sha: str, text: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO transcript_cache (audio_sha, text, created_at)"
        " VALUES (?, ?, ?)",
        (audio_sha, text, dbmod.now_iso()),
    )
    # Prune oldest beyond the cap (cheap frugality: bounded table growth).
    # rowid ordering = insertion order (created_at has only 1s precision).
    conn.execute(
        "DELETE FROM transcript_cache WHERE audio_sha NOT IN ("
        " SELECT audio_sha FROM transcript_cache ORDER BY rowid DESC LIMIT ?)",
        (MAX_TRANSCRIPT_ROWS,),
    )
    conn.commit()


def transcript_cache_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT COUNT(*) AS n FROM transcript_cache").fetchone()
    return {"rows": row["n"], "max_rows": MAX_TRANSCRIPT_ROWS}


# ---- TTS cache (on-disk, size-capped, LRU) ----------------------------------

class TTSCache:
    """File cache for synthesized MP3 bytes. Keyed by (text, voice)."""

    def __init__(self, directory: str | Path, max_bytes: int = 50 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    def _path(self, text: str, voice: str) -> Path:
        return self.directory / f"{tts_key(text, voice)}.mp3"

    def get(self, text: str, voice: str) -> bytes | None:
        p = self._path(text, voice)
        if p.exists():
            p.touch()  # mark recently used for LRU
            return p.read_bytes()
        return None

    def put(self, text: str, voice: str, data: bytes) -> None:
        if not data:
            return
        p = self._path(text, voice)
        if not p.exists():
            p.write_bytes(data)
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        files = [(f.stat().st_mtime, f.stat().st_size, f)
                 for f in self.directory.glob("*.mp3")]
        total = sum(s for _, s, _ in files)
        if total <= self.max_bytes:
            return
        # Oldest-accessed (by mtime, refreshed on get) first.
        for _, size, f in sorted(files):
            f.unlink(missing_ok=True)
            total -= size
            if total <= self.max_bytes:
                break

    def stats(self) -> dict:
        files = list(self.directory.glob("*.mp3"))
        return {
            "files": len(files),
            "bytes": sum(f.stat().st_size for f in files),
            "max_bytes": self.max_bytes,
        }

"""Tests for Feature 4 — audio clip storage + silent-clip auto-cleanup.

Covers audio_energy, the store's clip lifecycle + cleanup, the engine's clip
persistence and ingest silence gate, and the six clip/storage/settings
endpoints. All hermetic: DBs and clips live under pytest's tmp_path, OpenAI-
touching methods are patched, and ~/.voxa/.env is never written.
"""
import io
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from voxa.config import config
from voxa.memory.engine import MemoryEngine
from voxa.memory.store import MemoryStore


# ── WAV helpers ───────────────────────────────────────────────────────────────

def _make_wav(frames: bytes, sample_rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(sample_rate)
        w.writeframes(frames)
    return buf.getvalue()


def _silent_wav(n: int = 16000) -> bytes:
    """A valid 16k mono WAV of all-zero (silent) PCM."""
    return _make_wav(b"\x00\x00" * n)


def _loud_wav(n: int = 16000) -> bytes:
    """A valid 16k mono WAV of a loud 440Hz sine."""
    t = np.arange(n)
    sig = (np.sin(2 * np.pi * 440 * t / 16000) * 20000).astype("<i2")
    return _make_wav(sig.tobytes())


def _chunk(wav: bytes, **over) -> dict:
    item = {
        "wav_bytes": wav,
        "source": "mic",
        "session_id": "sess1234",
        "timestamp": time.time(),
        "chunk_duration": 5.0,
    }
    item.update(over)
    return item


# ── 1. audio_energy ───────────────────────────────────────────────────────────

class TestAudioEnergy:
    def test_silent_wav_is_silent(self):
        from voxa.utils.audio_energy import is_silent, rms_energy
        wav = _silent_wav()
        assert rms_energy(wav) < 1.0
        assert is_silent(wav) is True

    def test_loud_wav_is_not_silent(self):
        from voxa.utils.audio_energy import is_silent, rms_energy
        wav = _loud_wav()
        assert rms_energy(wav) > 1000
        assert is_silent(wav) is False

    def test_unparseable_bytes_not_silent(self):
        # We never drop audio we can't measure (placeholder/corrupt chunk).
        from voxa.utils.audio_energy import is_silent, rms_energy
        assert rms_energy(b"RIFF....WAVEdata") == 0.0
        assert is_silent(b"RIFF....WAVEdata") is False


# ── 2. store migration idempotent ─────────────────────────────────────────────

class TestMigration:
    def test_init_db_idempotent(self, tmp_path):
        import sqlite3
        store = MemoryStore(db_path=tmp_path / "m.db")
        store._init_db()  # run a second time — must not error
        with sqlite3.connect(store.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memory_segments)").fetchall()]
        assert "audio_path" in cols


# ── 3. store clip lifecycle ───────────────────────────────────────────────────

class TestClipLifecycle:
    def test_save_store_list_get_delete(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        wav = _loud_wav(2000)

        path = store.save_clip(wav)
        assert path and Path(path).exists()
        # clips dir derives from the injected db_path parent.
        assert Path(path).parent == tmp_path / "clips"

        seg = store.store_segment(
            raw_transcript="hello there",
            filtered_text="hello there",
            summary="greeting",
            source="mic",
            session_id="sess0001",
            audio_path=path,
        )
        # to_dict carries audio_path
        assert seg.to_dict()["audio_path"] == path

        # from_row carries audio_path
        recent = store.get_recent()
        assert recent[0].audio_path == path

        clips = store.list_clips()
        assert len(clips) == 1
        assert clips[0]["id"] == seg.segment_id
        assert clips[0]["source"] == "mic"
        assert clips[0]["size_bytes"] > 0

        assert store.get_clip_path(seg.segment_id) == path

        assert store.delete_segment(seg.segment_id) is True
        assert not Path(path).exists()
        assert store.get_clip_path(seg.segment_id) is None
        assert store.list_clips() == []

    def test_delete_segment_missing_id(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        assert store.delete_segment(999) is False

    def test_clear_clips_keeps_transcript(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        path = store.save_clip(_loud_wav(2000))
        seg = store.store_segment(
            raw_transcript="keep me",
            filtered_text="keep me",
            audio_path=path,
        )
        removed = store.clear_clips()
        assert removed == 1
        assert not Path(path).exists()
        # Row survives; audio_path cleared.
        assert store.get_clip_path(seg.segment_id) is None
        recent = store.get_recent()
        assert any(s.segment_id == seg.segment_id for s in recent)
        assert recent[0].audio_path == ""


# ── 4. delete_older_than / clear_all unlink clip files ────────────────────────

class TestCleanupUnlinksFiles:
    def test_delete_older_than_unlinks(self, tmp_path):
        import sqlite3
        store = MemoryStore(db_path=tmp_path / "m.db")
        path = store.save_clip(_loud_wav(2000))
        seg = store.store_segment(raw_transcript="old", filtered_text="old", audio_path=path)
        old_ts = (datetime.now() - timedelta(days=99)).isoformat()
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE memory_segments SET timestamp=? WHERE id=?", (old_ts, seg.segment_id))

        assert store.delete_older_than(30) == 1
        assert not Path(path).exists()

    def test_clear_all_unlinks(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        path = store.save_clip(_loud_wav(2000))
        store.store_segment(raw_transcript="x", filtered_text="x", audio_path=path)
        store.clear_all()
        assert not Path(path).exists()


# ── 5. engine clip persistence ────────────────────────────────────────────────

class TestEngineClipPersistence:
    def _engine(self, tmp_path) -> MemoryEngine:
        e = MemoryEngine()
        e.store = MemoryStore(db_path=tmp_path / "m.db")
        return e

    def test_meaningful_chunk_writes_clip(self, tmp_path):
        e = self._engine(tmp_path)
        with patch.object(MemoryEngine, "_transcribe", return_value="let's meet friday"), \
             patch.object(MemoryEngine, "_filter_transcript", return_value={
                 "is_meaningful": True,
                 "filtered_text": "Let's meet Friday",
                 "summary": "meeting plan",
                 "tags": "",
             }), \
             patch.object(MemoryEngine, "_generate_embedding", return_value=None), \
             patch.object(config, "MEETING_SUGGESTIONS", False):
            e._process_chunk(_chunk(_loud_wav(2000)))

        clips = e.store.list_clips()
        assert len(clips) == 1
        assert clips[0]["audio_path"]
        assert Path(clips[0]["audio_path"]).exists()

    def test_non_meaningful_chunk_writes_no_clip(self, tmp_path):
        e = self._engine(tmp_path)
        with patch.object(MemoryEngine, "_transcribe", return_value="uh um yeah"), \
             patch.object(MemoryEngine, "_filter_transcript", return_value={
                 "is_meaningful": False, "filtered_text": "", "summary": "", "tags": "",
             }), \
             patch.object(MemoryEngine, "_generate_embedding", return_value=None):
            e._process_chunk(_chunk(_loud_wav(2000)))

        assert e.store.list_clips() == []
        # No clip file left on disk either.
        if e.store.clips_dir.exists():
            assert list(e.store.clips_dir.glob("*.wav")) == []


# ── 6. ingest_chunk silence gate ──────────────────────────────────────────────

class TestIngestSilenceGate:
    def test_silence_dropped_loud_queued(self, tmp_path):
        e = MemoryEngine()
        e.store = MemoryStore(db_path=tmp_path / "m.db")
        with patch.object(MemoryEngine, "_process_loop", lambda self: None):
            e.start(external_audio=True)
        try:
            assert e.ingest_chunk(_silent_wav(4000), "mic") is False  # dropped
            assert e.ingest_chunk(_loud_wav(4000), "mic") is True      # queued
        finally:
            e.stop()


# ── 7. endpoints via TestClient ───────────────────────────────────────────────

httpx = pytest.importorskip("httpx")


class TestClipEndpoints:
    def test_full_flow(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from voxa.server import create_api_server
        from voxa.memory.engine import memory_engine
        import voxa.config as vcfg

        store = MemoryStore(db_path=tmp_path / "m.db")
        wav = _loud_wav(3000)
        path = store.save_clip(wav)
        seg = store.store_segment(
            raw_transcript="hello world",
            filtered_text="hello world",
            summary="greeting",
            source="mic",
            session_id="sess0001",
            audio_path=path,
        )

        monkeypatch.setattr(memory_engine, "store", store)
        # Never write the real ~/.voxa/.env from the settings endpoint.
        monkeypatch.setattr(vcfg, "persist_env_setting", lambda k, v: True)

        keep_audio_saved = config.MEMORY_KEEP_AUDIO
        try:
            with TestClient(create_api_server()) as c:
                # GET clips
                r = c.get("/api/memory/clips")
                assert r.status_code == 200
                body = r.json()
                assert body["count"] == 1
                clip = body["clips"][0]
                assert clip["id"] == seg.segment_id
                assert clip["source"] == "mic"
                assert clip["size_bytes"] > 0
                assert "audio_path" not in clip

                # GET clip audio
                r = c.get(f"/api/memory/clip/{seg.segment_id}")
                assert r.status_code == 200
                assert r.headers["content-type"] == "audio/wav"
                assert r.content == wav

                # 404 for unknown clip
                assert c.get("/api/memory/clip/99999").status_code == 404

                # GET storage
                r = c.get("/api/memory/storage")
                s = r.json()
                for k in ("clips_count", "clips_size_mb", "db_size_mb", "keep_audio", "retention_days"):
                    assert k in s
                assert s["clips_count"] == 1

                # POST settings — keep_audio toggled off is reflected
                r = c.post("/api/memory/settings", json={"keep_audio": False})
                assert r.status_code == 200
                assert r.json()["keep_audio"] is False

                # DELETE clip
                r = c.delete(f"/api/memory/clip/{seg.segment_id}")
                assert r.json()["deleted"] is True
                assert c.get("/api/memory/clips").json()["count"] == 0

                # POST clips/clear (re-seed one clip first)
                p2 = store.save_clip(_loud_wav(1000))
                store.store_segment(raw_transcript="x", filtered_text="x", audio_path=p2)
                r = c.post("/api/memory/clips/clear")
                assert r.json()["success"] is True
                assert r.json()["deleted"] == 1
        finally:
            config.MEMORY_KEEP_AUDIO = keep_audio_saved

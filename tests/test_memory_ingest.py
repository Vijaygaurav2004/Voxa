"""Tests for external-audio mode: host app streams chunks into the memory engine."""
from unittest.mock import patch

from voxa.memory.engine import MemoryEngine


def _engine_no_processing() -> MemoryEngine:
    """A MemoryEngine whose background processing loop is a no-op (no API calls)."""
    e = MemoryEngine()
    return e


class TestExternalAudioMode:
    def test_external_start_opens_no_local_capture(self):
        e = _engine_no_processing()
        with patch.object(MemoryEngine, "_process_loop", lambda self: None):
            e.start(external_audio=True)
        try:
            assert e._capture is None          # no Python mic opened
            assert e.is_active is True
            assert e._external_audio is True
        finally:
            e.stop()

    def test_ingest_queues_when_running(self):
        e = _engine_no_processing()
        with patch.object(MemoryEngine, "_process_loop", lambda self: None):
            e.start(external_audio=True)
        try:
            assert e.ingest_chunk(b"RIFF....WAVEdata", "mic") is True
            assert e._process_queue.qsize() == 1
        finally:
            e.stop()

    def test_ingest_ignored_when_paused_or_stopped(self):
        e = _engine_no_processing()
        with patch.object(MemoryEngine, "_process_loop", lambda self: None):
            e.start(external_audio=True)
        e._paused = True
        assert e.ingest_chunk(b"x") is False       # paused
        e.stop()
        assert e.ingest_chunk(b"x") is False        # not running
        assert e.ingest_chunk(b"") is False         # empty


class TestIngestEndpoint:
    def test_ingest_endpoint_queues(self):
        from fastapi.testclient import TestClient
        from voxa.server import create_api_server
        from voxa.memory.engine import memory_engine

        with patch.object(type(memory_engine), "_process_loop", lambda self: None):
            memory_engine.start(external_audio=True)
            try:
                with TestClient(create_api_server()) as c:
                    r = c.post("/api/memory/ingest",
                               files={"audio": ("chunk.wav", b"RIFF....WAVEdata", "audio/wav")})
                    body = r.json()
                    assert body["success"] is True
                    assert body["queued"] is True
                    assert body["source"] == "mic"          # default source

                    # System audio (other participants) is tagged distinctly.
                    r2 = c.post("/api/memory/ingest",
                                data={"source": "system"},
                                files={"audio": ("chunk.wav", b"RIFF....WAVEdata", "audio/wav")})
                    assert r2.json()["source"] == "system"
            finally:
                memory_engine.stop()

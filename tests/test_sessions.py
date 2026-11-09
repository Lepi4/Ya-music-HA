"""Contract tests for the Rotor Session API adapter."""
import asyncio
import sys
from types import ModuleType
from types import SimpleNamespace as NS
import unittest

from test_recommendations import load_service


class SessionAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_next_and_feedback_use_session_methods(self):
        service_type = load_service()
        calls = []
        track = NS(id=101, title="Session track", artists=[], albums=[], duration_ms=60000, available=True)
        sequence = [NS(track=track)]
        first = NS(radio_session_id="session-1", batch_id="batch-1", sequence=sequence, terminated=False)
        second = NS(radio_session_id="session-1", batch_id="batch-2", sequence=[NS(track=NS(id=102, title="Next", artists=[], albums=[], duration_ms=60000, available=True))], terminated=False)
        class Client:
            def rotor_session_new(self, *args, **kwargs):
                calls.append(("new", args, kwargs)); return first
            def rotor_session_tracks(self, *args, **kwargs):
                calls.append(("tracks", args, kwargs)); return second
            def rotor_session_feedback(self, *args, **kwargs):
                calls.append(("feedback", args, kwargs)); return True
        async def executor(fn): return fn()
        service = service_type(NS(async_add_executor_job=executor), "media_player.test")
        music = ModuleType("yandex_music")
        class SessionEvent:
            def __init__(self, type_, timestamp, track_id=None, total_played_seconds=None):
                self.type, self.timestamp = type_, timestamp
                self.track_id, self.total_played_seconds = track_id, total_played_seconds
        music.SessionEvent = SessionEvent
        sys.modules["yandex_music"] = music
        async def get_client(): return Client()
        service.client = get_client

        created = await service.session_new(["user:onyourwave", "genre:rock"], queue=["99"])
        self.assertEqual(created["session_id"], "session-1")
        self.assertEqual(created["tracks"][0]["id"], "101")
        next_batch = await service.session_tracks("session-1", ["99", "101"])
        self.assertEqual(next_batch["batch"], "batch-2")
        await service.session_feedback("session-1", "trackStarted", "101", "batch-1")

        self.assertEqual([item[0] for item in calls], ["new", "tracks", "feedback"])
        self.assertEqual(calls[0][1], (["user:onyourwave", "genre:rock"],))
        self.assertEqual(calls[0][2]["queue"], ["99"])
        self.assertEqual(calls[1][1], ("session-1",))
        self.assertEqual(calls[1][2]["queue"], ["99", "101"])
        event = calls[2][1][1]
        self.assertEqual(event.type, "trackStarted")
        self.assertEqual(event.track_id, "101")
        self.assertEqual(calls[2][2]["batch_id"], "batch-1")

    async def test_missing_session_id_is_a_clear_error(self):
        service_type = load_service()
        class Client:
            def rotor_session_new(self, *args, **kwargs): return NS(radio_session_id=None, sequence=[])
        async def executor(fn): return fn()
        service = service_type(NS(async_add_executor_job=executor), "media_player.test")
        async def get_client(): return Client()
        service.client = get_client
        with self.assertRaises(RuntimeError):
            await service.session_new("user:onyourwave")


if __name__ == "__main__":
    unittest.main()

"""State-driven Rotor playback, without HA or physical speaker side effects."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS, ModuleType
import sys
import unittest
from unittest.mock import patch

from test_recommendations import load_service


class RadioTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        service_type = load_service()
        package = ModuleType("ym_radio_test")
        package.__path__ = []
        yandex = ModuleType("ym_radio_test.yandex")
        yandex.YandexMusicError = service_type.__init__.__globals__["YandexMusicError"]
        spec = importlib.util.spec_from_file_location("ym_radio_test.radio", Path(__file__).resolve().parents[1] / "custom_components/yandex_music_chaos/radio.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"ym_radio_test":package, "ym_radio_test.yandex":yandex, spec.name:module}):
            spec.loader.exec_module(module)
        self.Controller = module.RadioController
        self.ids = module.track_id
        self.calls, self.feedback, self.fetches = [], [], []
        self.states = {}
        self.fail_fetch = False
        self.fail_play = False
        self.fail_feedback = False
        self.overlap_only = False

        async def call(domain, action, data, **kwargs):
            if self.fail_play:
                raise RuntimeError("offline")
            self.calls.append((domain, action, data))

        async def batch(station, cursor):
            self.fetches.append((station, cursor))
            if self.fail_fetch:
                raise RuntimeError("upstream down")
            start = int(cursor or 1)
            ids = range(start, start + (1 if self.overlap_only else 5))
            return {"batch": f"batch-{cursor or 'first'}", "tracks": [
                {"id": str(i), "title": f"Track {i}", "duration": 60} for i in ids]}

        async def feedback(*args):
            if self.fail_feedback:
                raise RuntimeError("feedback unavailable")
            self.feedback.append(args)

        hass = NS(services=NS(async_call=call), states=NS(get=self.states.get))
        self.radio = self.Controller(NS(hass=hass, wave_batch=batch, wave_feedback=feedback))

    def state(self, ident, status="playing", pos=0):
        return NS(state=status, attributes={"media_content_id": ident, "media_position": pos, "media_duration": 60})

    async def event(self, entity, old, new):
        self.states[entity] = new
        await self.radio.handle_event(NS(data={"entity_id": entity, "old_state": old, "new_state": new}))

    async def started(self, entity="one"):
        s = self.radio.sessions[entity]
        await self.event(entity, self.state("", "idle"), self.state(s.current["id"]))

    async def ended(self, entity="one"):
        s = self.radio.sessions[entity]
        await self.event(entity, self.state(s.current["id"], pos=60), self.state("", "idle"))

    async def test_continues_beyond_first_five_without_browser_or_wrapping(self):
        await self.radio.start("one", "user:onyourwave")
        for _ in range(12):
            await self.started()
            await self.ended()
        played = [c[2]["media_content_id"] for c in self.calls]
        self.assertEqual(played, list(map(str, range(1, 14))))
        self.assertGreater(len(self.fetches), 1)
        finished = [f for f in self.feedback if f[1] == "trackFinished"]
        self.assertEqual(len(finished), 12)
        self.assertEqual(finished[0][3], "batch-first")
        self.assertEqual(finished[0][4], 60)
        self.assertTrue(all(c[2]["media_content_type"] == "track" for c in self.calls))

    async def test_speakers_have_independent_queues_and_context(self):
        await asyncio.gather(self.radio.start("one", "user:onyourwave"), self.radio.start("two", "track:55"))
        await self.started("one")
        await self.started("two")
        await self.radio.control("one", "next")
        self.assertEqual(self.radio.sessions["one"].index, 1)
        self.assertEqual(self.radio.sessions["two"].index, 0)
        self.assertEqual(self.calls[-1][2]["entity_id"], ["one"])
        self.assertEqual(self.radio.snapshot()["two"]["station"], "track:55")
        self.assertNotIn("_batch", self.radio.snapshot()["one"]["tracks"][0])

    async def test_single_feedback_start_skip_finish_and_late_events(self):
        await self.radio.start("one", "user:onyourwave")
        self.assertFalse(any(f[1] == "trackStarted" for f in self.feedback))
        await self.started()
        await self.started()
        await self.ended()
        await self.started()
        await self.event("one", self.state("1", pos=60), self.state("", "idle"))
        self.assertEqual(self.radio.sessions["one"].current["id"], "2")
        await self.radio.control("one", "next")
        self.assertEqual([f[1] for f in self.feedback], ["radioStarted", "trackStarted", "trackFinished", "trackStarted", "skip"])

    async def test_pause_and_explicit_stop_do_not_auto_advance(self):
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        await self.event("one", self.state("1", pos=10), self.state("1", "paused", 10))
        self.assertEqual(len(self.calls), 1)
        await self.radio.control("one", "stop")
        await self.event("one", self.state("1", pos=60), self.state("", "idle"))
        self.assertNotIn("one", self.radio.sessions)
        self.assertEqual(self.calls[-1][1], "media_stop")

    async def test_station_retaining_paused_metadata_at_end_continues(self):
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        await self.event("one", self.state("1", pos=59), self.state("1", "paused", 60))
        self.assertEqual(self.radio.sessions["one"].current["id"], "2")

    async def test_external_playback_during_wait_cancels_retry(self):
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        self.radio.sessions["one"].waiting = True
        await self.event("one", self.state("1", pos=60), self.state("999"))
        await self.radio.retry_waiting()
        self.assertNotIn("one", self.radio.sessions)
        self.assertEqual(len(self.calls), 1)

    async def test_external_playback_takes_ownership(self):
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        await self.event("one", self.state("1", pos=10), self.state("999"))
        self.assertNotIn("one", self.radio.sessions)
        self.assertEqual(len(self.calls), 1)

    async def test_duplicate_batches_do_not_loop_and_retry_is_bounded(self):
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        self.overlap_only = True
        for _ in range(4):
            await self.radio.control("one", "next")
            await self.started()
        with self.assertRaises(RuntimeError):
            await self.radio.control("one", "next")
        for _ in range(10):
            await self.radio.retry_waiting()
        self.assertEqual(self.radio.sessions["one"].index, 4)
        self.assertEqual(self.radio.sessions["one"].retries, 3)
        self.assertEqual(len(self.calls), 5)
        self.assertLess(len(self.fetches), 20)
        self.assertTrue(self.radio.sessions["one"].error)

    async def test_network_failure_during_end_retries_then_recovers(self):
        await self.radio.start("one", "user:onyourwave")
        for _ in range(4):
            await self.started()
            await self.radio.control("one", "next")
        await self.started()
        s = self.radio.sessions["one"]
        # Drain the prefetch to exercise the upstream failure at the boundary.
        del s.tracks[s.index + 1:]
        self.fail_fetch = True
        await self.ended()
        self.assertTrue(s.waiting)
        self.fail_fetch = False
        await self.radio.retry_waiting()
        self.assertFalse(s.waiting)
        self.assertEqual(s.current["id"], "6")
        self.assertEqual(len([f for f in self.feedback if f[1] == "trackFinished"]), 1)

    async def test_failed_play_keeps_cursor_and_reports_no_started_track(self):
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        self.fail_play = True
        with self.assertRaises(RuntimeError):
            await self.radio.control("one", "next")
        self.assertEqual(self.radio.sessions["one"].current["id"], "1")
        self.assertTrue(self.radio.sessions["one"].waiting)
        self.fail_play = False
        await self.radio.retry_waiting()
        self.assertEqual(self.radio.sessions["one"].current["id"], "2")
        self.assertEqual(len([f for f in self.feedback if f[1] == "trackStarted"]), 1)

    async def test_feedback_failure_does_not_stop_playback(self):
        self.fail_feedback = True
        await self.radio.start("one", "user:onyourwave")
        await self.started()
        await self.ended()
        self.assertEqual(self.radio.sessions["one"].current["id"], "2")
        self.assertTrue(self.radio.sessions["one"].feedback_error)

    async def test_track_ids_and_unload(self):
        self.assertEqual(self.ids("https://music.yandex.ru/album/12/track/34?x=1"), "34")
        self.assertEqual(self.ids("34:12"), "34")
        self.assertEqual(self.ids("media_player.shield"), "")
        await self.radio.start("one", "user:onyourwave")
        self.radio.close()
        self.assertEqual(self.radio.snapshot(), {})


if __name__ == "__main__":
    unittest.main()

"""Exercise delayed external receivers without real devices or credentials."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

import test_radio as radio_tests


class DirectOutputTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.helper = radio_tests.RadioTest()
        await self.helper.asyncSetUp()
        self.radio = self.helper.radio
        self.service = self.radio.service
        self.hass = self.service.hass
        self.station = NS(entity_id="one", source_list=["Station", "External"], sync_enabled=False,
                          sync_sources={"External":{"entity_id":"media_player.receiver"}})
        self.hass.data = {"entity_components":{"media_player":NS(entities=[self.station])}}
        self.helper.states["one"] = self.helper.state("", "idle")
        self.helper.states["media_player.receiver"] = self.helper.state("", "idle")
        package = ModuleType("ym_output_test")
        package.__path__ = []
        radio = ModuleType("ym_output_test.radio")
        radio.position = self.radio.finish.__globals__["position"]
        radio.track_id = self.helper.ids
        yandex = ModuleType("ym_output_test.yandex")
        yandex.YandexMusicError = self.radio.play.__globals__["YandexMusicError"]
        spec = importlib.util.spec_from_file_location("ym_output_test.outputs", Path(__file__).resolve().parents[1] / "custom_components/yandex_music_chaos/outputs.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"ym_output_test":package, "ym_output_test.radio":radio,
                                     "ym_output_test.yandex":yandex, spec.name:module}):
            spec.loader.exec_module(module)
        self.outputs = self.service.outputs = module.DirectOutputs(self.service)
        self.service.radio = self.radio
        self.urls = []
        self.fail_url = False
        async def url(ident, prefer_mp3=False):
            self.assertTrue(prefer_mp3)
            if self.fail_url:
                raise RuntimeError("URL resolution failed")
            self.urls.append(ident)
            return f"https://cdn.example/{ident}.mp3"
        self.service.direct_url = url
        dependency = ModuleType("custom_components.yandex_station.core.yandex_station")
        dependency.SOURCE_STATION = "Station"
        self.dependency = dependency
        self.tracks = [{"id":str(i),"duration":60,"title":f"Track {i}","artists":"Artist"} for i in range(1,4)]

    async def select(self):
        with patch.dict(sys.modules, {self.dependency.__name__:self.dependency}):
            await self.outputs.select("one", "External", True)
        self.helper.calls.clear()

    def state(self, ident="1", status="playing", pos=0):
        return NS(state=status, attributes={"media_content_id":f"https://cdn.example/{ident}.mp3" if ident else "",
                                           "media_position":pos,"media_duration":60,"volume_level":.35})

    async def event(self, old, new):
        self.helper.states["media_player.receiver"] = new
        event = NS(data={"entity_id":"media_player.receiver","old_state":old,"new_state":new})
        await self.radio.handle_event(event)
        await self.outputs.handle_event(event)

    async def test_late_receiver_ignores_station_end_and_waits_for_its_own_eof(self):
        await self.select()
        await self.outputs.playlist("one", self.tracks, 0)
        await self.helper.event("one",self.helper.state("1",pos=59),self.helper.state("1","paused",60))
        self.assertEqual(len(self.helper.calls),1)
        await self.event(self.state("","idle"),self.state(pos=0))
        await self.helper.event("one",self.helper.state("1",pos=60),self.helper.state("2"))
        await self.event(self.state(pos=55),self.state(pos=56))
        self.assertEqual(len(self.helper.calls),1)
        await self.event(self.state(pos=60),self.state("","idle"))
        self.assertEqual(len(self.helper.calls),2)
        self.assertEqual(self.helper.calls[-1][2]["entity_id"],["media_player.receiver"])
        self.assertEqual(self.helper.calls[-1][2]["media_content_id"],"https://cdn.example/2.mp3")

    async def test_radio_uses_receiver_and_continues_beyond_five(self):
        await self.select()
        await self.radio.start("one","user:onyourwave")
        for i in range(1,9):
            ident=str(i)
            await self.event(self.state("","idle"),self.state(ident))
            await self.helper.event("one",self.helper.state(ident,pos=59),self.helper.state(ident,"paused",60))
            self.assertEqual(self.radio.sessions["one"].current["id"],ident)
            await self.event(self.state(ident,pos=60),self.state("","idle"))
        self.assertEqual(self.radio.sessions["one"].current["id"],"9")
        self.assertTrue(all(c[2]["entity_id"]==["media_player.receiver"] for c in self.helper.calls))

    async def test_current_rotor_session_continuation_uses_receiver_feedback(self):
        await self.select()
        calls=[]
        async def first(seed,queue):
            calls.append(("new",seed))
            return {"session_id":"session-1","batch":"first","tracks":[{"id":str(i),"duration":60} for i in range(1,6)]}
        async def more(session,queue):
            calls.append(("more",session))
            return {"session_id":session,"batch":"next","tracks":[{"id":str(i),"duration":60} for i in range(int(queue[-1]),int(queue[-1])+5)]}
        async def feedback(*args): calls.append(("feedback",args[1]))
        self.service.session_new,self.service.session_tracks,self.service.session_feedback=first,more,feedback
        await self.outputs.start_radio("one","user:onyourwave")
        for i in range(1,9):
            await self.event(self.state("","idle"),self.state(str(i)))
            await self.event(self.state(str(i),pos=60),self.state("","idle"))
        self.assertEqual(self.radio.sessions["one"].current["id"],"9")
        self.assertIn(("more","session-1"),calls)
        self.assertEqual(calls.count(("feedback","trackFinished")),8)
        self.assertTrue(all(c[2]["entity_id"]==["media_player.receiver"] for c in self.helper.calls))

    async def test_pause_at_end_and_elapsed_time_alone_do_not_advance(self):
        await self.select()
        await self.outputs.playlist("one",self.tracks,0)
        await self.event(self.state("","idle"),self.state())
        await self.event(self.state(pos=59),self.state(status="paused",pos=60))
        await self.radio.retry_waiting()
        self.assertEqual(len(self.helper.calls),1)
        self.assertEqual(self.outputs.routes["one"].index,0)

    async def test_startup_idle_late_events_external_replacement_and_stop(self):
        await self.select()
        await self.outputs.playlist("one",self.tracks,0)
        await self.event(self.state("old"),self.state("","idle"))
        self.assertEqual(len(self.helper.calls),1)
        await self.event(self.state("","idle"),self.state())
        await self.event(self.state(pos=60),self.state("999"))
        self.assertFalse(self.outputs.routes["one"].active)
        await self.event(self.state(pos=60),self.state("","idle"))
        self.assertEqual(len(self.helper.calls),1)
        await self.outputs.playlist("one",self.tracks,0)
        await self.event(self.state("","idle"),self.state())
        await self.outputs.command("one","stop",{})
        await self.event(self.state(pos=60),self.state("","idle"))
        self.assertEqual(self.helper.calls[-1][1],"media_stop")
        self.assertEqual(len([c for c in self.helper.calls if c[1]=="play_media"]),2)

    async def test_controls_use_actual_receiver_and_do_not_touch_station(self):
        await self.select()
        for action,body in [("volume_set",{"level":.43}),("seek",{"position":42}),("pause",{}),("mute",{"muted":True})]:
            await self.outputs.command("one",action,body)
        self.assertTrue(all(c[2]["entity_id"]==["media_player.receiver"] for c in self.helper.calls))
        self.assertEqual(self.helper.calls[0][2]["volume_level"],.43)
        self.assertEqual(self.helper.calls[1][2]["seek_position"],42)

    async def test_active_station_is_paused_before_direct_source_selection(self):
        self.helper.states["one"] = self.helper.state("1")
        with patch.dict(sys.modules, {self.dependency.__name__:self.dependency}):
            await self.outputs.select("one", "External", True)
        self.assertEqual([c[1] for c in self.helper.calls], ["media_pause", "select_source"])
        self.assertTrue(all(c[2]["entity_id"] == ["one"] for c in self.helper.calls))
        self.assertEqual(self.outputs.routes["one"].entity_id, "media_player.receiver")

    async def test_rejects_busy_receiver_before_pausing_station_and_duplicate_owner(self):
        self.helper.states["one"] = self.helper.state("1")
        self.helper.states["media_player.receiver"] = self.state("999")
        with self.assertRaisesRegex(RuntimeError,"другой контент"):
            await self.select()
        self.assertEqual(self.helper.calls,[])
        self.helper.states["one"] = self.helper.state("","idle")
        self.helper.states["media_player.receiver"] = self.state("","idle")
        await self.select()
        second=NS(**{**vars(self.station),"entity_id":"two"})
        self.hass.data["entity_components"]["media_player"].entities.append(second)
        with self.assertRaisesRegex(RuntimeError,"другой Станции"):
            await self.outputs.select("two","External",True)

    async def test_url_failure_keeps_previous_queue_and_sync_conflict_is_rejected(self):
        await self.select()
        await self.outputs.playlist("one",self.tracks,0)
        self.fail_url = True
        with self.assertRaises(RuntimeError):
            await self.outputs.command("one","next",{})
        self.assertEqual(self.outputs.routes["one"].index,0)
        self.station.sync_enabled = True
        self.fail_url = False
        with self.assertRaisesRegex(RuntimeError,"синхронизация"):
            await self.outputs.command("one","next",{})
        self.assertEqual(len(self.helper.calls),1)

    async def test_late_cast_discovery_is_available_but_android_remote_is_not(self):
        cast=NS(entity_id="media_player.cast",platform=NS(platform_name="cast"))
        remote=NS(entity_id="media_player.remote",platform=NS(platform_name="androidtv_remote"))
        self.station.sync_sources["Remote"]={"entity_id":remote.entity_id}
        self.station.source_list.append("Remote")
        self.hass.data["entity_components"]["media_player"].entities.extend([cast,remote])
        self.helper.states[cast.entity_id]=self.state("","off")
        choices=self.outputs.choices("one")
        self.assertIn({"source":cast.entity_id,"entity_id":cast.entity_id},choices)
        self.assertFalse(any(c['entity_id']==remote.entity_id for c in choices))
        with patch.dict(sys.modules, {self.dependency.__name__:self.dependency}):
            await self.outputs.select("one",cast.entity_id,True)
        self.assertEqual(self.outputs.routes["one"].entity_id,cast.entity_id)
        await self.outputs.release("one")
        with self.assertRaisesRegex(RuntimeError,"пульт Android TV"):
            await self.outputs.select("one","Remote",True)

    async def test_late_heos_discovery_can_be_selected_without_native_source(self):
        heos = NS(entity_id="media_player.kholl_4", platform=NS(platform_name="heos"))
        self.hass.data["entity_components"]["media_player"].entities.append(heos)
        self.helper.states[heos.entity_id] = self.state("", "paused")
        self.assertIn({"source": heos.entity_id, "entity_id": heos.entity_id}, self.outputs.choices("one"))
        with patch.dict(sys.modules, {self.dependency.__name__:self.dependency}):
            await self.outputs.select("one", heos.entity_id, True)
        await self.outputs.playlist("one", self.tracks, 0)
        self.assertEqual(self.helper.calls[-2][1], "clear_playlist")
        self.assertEqual(self.helper.calls[-1][2]["entity_id"], [heos.entity_id])
        self.assertEqual(self.helper.calls[-1][2]["media_content_id"], "https://cdn.example/1.mp3")

    async def test_failed_station_pause_keeps_route_unchanged(self):
        await self.select()
        heos = NS(entity_id="media_player.kholl_4", platform=NS(platform_name="heos"))
        self.hass.data["entity_components"]["media_player"].entities.append(heos)
        self.helper.states[heos.entity_id] = self.state("", "idle")
        self.helper.states["one"] = self.helper.state("1")
        self.helper.fail_play = True
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await self.outputs.select("one", heos.entity_id, True)
        self.assertEqual(self.outputs.routes["one"].entity_id, "media_player.receiver")

    async def test_heos_queue_slot_is_not_stream_identity_and_eof_uses_transport(self):
        receiver=NS(entity_id="media_player.receiver",platform=NS(platform_name="heos"))
        self.hass.data["entity_components"]["media_player"].entities.append(receiver)
        await self.select()
        await self.outputs.playlist("one",self.tracks,0)
        raw=NS(state="playing",attributes={"media_content_id":"1","media_title":"Url Stream"})
        self.helper.states[receiver.entity_id]=raw
        route=self.outputs.routes["one"]
        self.assertFalse(self.outputs.matches(route,raw))
        verified=self.state(pos=58)
        async def transport(_route):return verified
        self.outputs.heos_state=transport
        await self.outputs.poll_heos()
        projected=self.outputs.project("one",{})
        self.assertEqual(projected["media_id"],"1")
        self.assertEqual(projected["title"],"Track 1")
        self.assertEqual(projected["position"],58)
        self.assertTrue(projected["transport_polling"])
        self.assertTrue(route.observed)
        # A raw HEOS event with the same slot ID must not end our track.
        await self.event(raw,NS(state="idle",attributes={"media_content_id":"1"}))
        self.assertEqual(route.index,0)
        verified=self.state(pos=60)
        await self.outputs.poll_heos()
        verified=NS(state="playing",attributes={"media_content_id":""})
        await self.outputs.poll_heos()
        self.assertEqual(route.transport_state.attributes["media_position"],60)
        verified=self.state(status="idle",pos=60)
        await self.outputs.poll_heos()
        self.assertEqual(route.index,1)
        self.assertEqual(self.helper.calls[-1][2]["media_content_id"],"https://cdn.example/2.mp3")
        # A different URL in slot 1 is unrelated content, not our next song.
        verified=self.state("2",pos=3)
        await self.outputs.poll_heos()
        verified=self.state("999",pos=4)
        await self.outputs.poll_heos()
        self.assertFalse(route.active)
        self.assertEqual(self.outputs.project("one",{})["media_id"],"")

    async def test_heos_reads_group_leader_uri_and_position(self):
        receiver=NS(entity_id="media_player.receiver",platform=NS(platform_name="heos"))
        leader=NS(entity_id="media_player.leader",platform=NS(platform_name="heos"),
                  _player=NS(ip_address="192.0.2.2"))
        self.hass.data["entity_components"]["media_player"].entities.extend([receiver,leader])
        await self.select()
        self.helper.states[receiver.entity_id]=NS(state="playing",attributes={
            "media_content_id":"1","group_members":[leader.entity_id,receiver.entity_id]})
        calls=[]
        class Response:
            def __init__(self,body):self.body=body
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
            def raise_for_status(self):pass
            async def read(self):
                return self.body
        class Session:
            def post(self,url,**kwargs):
                calls.append((url,kwargs))
                if 'GetTransportInfo' in kwargs['data']:
                    return Response(b'<root><CurrentTransportState>STOPPED</CurrentTransportState></root>')
                return Response(b'<root><TrackURI>https://cdn.example/1.mp3</TrackURI><RelTime>00:01:02</RelTime><TrackDuration>00:03:04</TrackDuration></root>')
        client=ModuleType("homeassistant.helpers.aiohttp_client")
        client.async_get_clientsession=lambda hass:Session()
        aiohttp=ModuleType("aiohttp")
        aiohttp.ClientTimeout=lambda **kwargs:kwargs
        with patch.dict(sys.modules,{client.__name__:client,"aiohttp":aiohttp}):
            state=await self.outputs.heos_state(self.outputs.routes["one"])
        self.assertIn("192.0.2.2:60006",calls[0][0])
        self.assertIn("GetPositionInfo",calls[0][1]["data"])
        self.assertEqual(state.attributes["media_content_id"],"https://cdn.example/1.mp3")
        self.assertEqual(state.attributes["media_position"],62)
        self.assertEqual(state.attributes["media_duration"],184)
        self.assertEqual(state.state,"idle", "The leader's STOPPED overrides the member's stale playing state")
        await self.outputs.playlist("one",self.tracks,0)
        self.assertEqual(self.helper.calls[-2][1],"clear_playlist")
        self.assertEqual(self.helper.calls[-2][2]["entity_id"],[leader.entity_id])

    async def test_removed_direct_route_never_falls_back_to_audible_station(self):
        await self.select()
        await self.radio.start("one","user:onyourwave")
        session=self.radio.sessions["one"]
        self.outputs.routes.clear()
        with self.assertRaisesRegex(RuntimeError,"запуск на Станции отменён"):
            await self.radio.play(session,1)
        self.assertEqual(len(self.helper.calls),1)
        self.assertEqual(self.helper.calls[0][2]["entity_id"],["media_player.receiver"])

    async def test_project_reports_receiver_metadata_and_release_only_stops_owned_content(self):
        await self.select()
        await self.outputs.playlist("one",self.tracks,0)
        self.helper.states["media_player.receiver"] = self.state(pos=4)
        row=self.outputs.project("one",{"entity_id":"one","name":"Station"})
        self.assertEqual(row["position"],4)
        self.assertEqual(row["media_id"],"1")
        self.assertEqual(row["input_source"],"External")
        self.assertTrue(row["direct_output"])
        self.helper.states["media_player.receiver"] = self.state("999")
        await self.outputs.release("one",stop=True)
        self.assertEqual(len(self.helper.calls),1)
        self.assertEqual(self.outputs.routes,{})

    async def test_receiver_progress_uses_its_own_timestamp_and_stop_resumes_safely(self):
        await self.select()
        await self.outputs.playlist("one",self.tracks,0)
        state=self.state(pos=4)
        state.attributes["media_position_updated_at"]=datetime.now(timezone.utc)-timedelta(seconds=5)
        self.helper.states["media_player.receiver"]=state
        row=self.outputs.project("one",{"entity_id":"one"})
        self.assertGreaterEqual(row["position"],9)
        self.assertLess(row["position"],10)
        await self.outputs.command("one","stop",{})
        await self.outputs.command("one","play",{})
        self.assertTrue(self.outputs.routes["one"].active)


if __name__ == "__main__":
    unittest.main()

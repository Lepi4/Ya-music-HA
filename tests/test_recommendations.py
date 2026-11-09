"""Exercise recommendation normalization without requiring a HA installation."""
import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch


def load_service():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "yandex_music_chaos"
    package = ModuleType("ym_test_component")
    package.__path__ = [str(root)]
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    music = ModuleType("yandex_music")
    music.Client = object
    class SessionEvent:
        def __init__(self, type_, timestamp, track_id=None, total_played_seconds=None):
            self.type, self.timestamp = type_, timestamp
            self.track_id, self.total_played_seconds = track_id, total_played_seconds
    music.SessionEvent = SessionEvent
    stubs = {"ym_test_component": package, "homeassistant": ModuleType("homeassistant"),
             "homeassistant.core": core, "yandex_music": music, "aiohttp": ModuleType("aiohttp")}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("ym_test_component.yandex", root / "yandex.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.YandexMusicService


class RecommendationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_wave_settings_use_api_options_and_preserve_other_settings(self):
        moods = [SimpleNamespace(value="calm", name="A localized API label"), SimpleNamespace(value="all", name="Any")]
        rows = [SimpleNamespace(settings2=SimpleNamespace(mood_energy="all", diversity="discover", language="russian"),
                                station=SimpleNamespace(restrictions2=SimpleNamespace(mood_energy=SimpleNamespace(possible_values=moods))))]
        calls = []
        client = SimpleNamespace(rotor_station_info=lambda station: rows,
                                 rotor_station_settings2=lambda *args, **kw: calls.append((args, kw)) or True)
        async def executor(fn): return fn()
        service = load_service()(SimpleNamespace(async_add_executor_job=executor), "media_player.test")
        async def get_client(): return client
        service.client = get_client
        result = await service.set_wave_mood("calm")
        self.assertEqual(result["moods"][0]["name"], "A localized API label")
        self.assertEqual(calls[0], (("user:onyourwave",), {"mood_energy":"calm", "diversity":"discover", "language":"russian"}))
        with self.assertRaises(RuntimeError):
            await service.set_wave_mood("invented")
        self.assertEqual(len(calls), 1)

    async def test_empty_likes_does_not_request_empty_track_ids(self):
        async def executor(fn): return fn()
        def forbidden_tracks(**kwargs): raise AssertionError("tracks([]) must never reach the API")
        client = SimpleNamespace(users_likes_tracks=lambda **kwargs: SimpleNamespace(tracks_ids=[]), tracks=forbidden_tracks)
        service = load_service()(SimpleNamespace(async_add_executor_job=executor), "media_player.test")
        async def get_client(): return client
        async def account(): return {"uid":"test"}
        service.client = get_client
        service.account = account
        self.assertEqual(await service.liked_tracks(), [])

    async def test_audiobooks_excludes_soundtracks_and_unrelated_podcasts(self):
        book = SimpleNamespace(id=31,title="Book",type="audiobook",meta_type="podcast",artists=[],track_count=10)
        soundtrack = SimpleNamespace(id=32,title="Audiobook soundtrack",type=None,meta_type="music")
        podcast = SimpleNamespace(id=33,title="Audiobooks discussion",type="podcast",meta_type="podcast")
        client = SimpleNamespace(
            users_likes_albums=lambda **kwargs: [SimpleNamespace(album=book)],
            search=lambda *args,**kwargs: SimpleNamespace(podcasts=SimpleNamespace(results=[soundtrack,podcast,book],per_page=20,total=3)),
        )
        async def executor(fn): return fn()
        service = load_service()(SimpleNamespace(async_add_executor_job=executor), "media_player.test")
        async def get_client(): return client
        async def account(): return {"uid":"test"}
        service.client = get_client
        service.account = account
        result = await service.audiobooks()
        self.assertEqual([item["id"] for shelf in result["shelves"] for item in shelf["items"]], ["31","31"])
        self.assertIsNone(result["next_page"])

    async def test_dynamic_shelves_personal_playlist_album_and_single_flight(self):
        service_type = load_service()
        calls = []
        landing = {"blocks": [
            {"id": "personal", "title": "A changing title from API", "entities": [
                {"type": "personal-playlist", "data": {"data": {
                    "kind": 1000, "owner": {"uid": 7}, "title": "Generated today",
                    "trackCount": 40, "cover": {"uri": "images.example/%%"}}}}]},
            {"id": "albums", "title": "Another API title", "entities": [
                {"type": "album", "data": {"id": 90, "title": "Album", "coverUri": "images.example/a/%%",
                                          "artists": [{"name": "Artist"}]}}]},
            {"id": "empty", "entities": []},
        ]}
        def get(url, params):
            calls.append((url, params))
            return landing
        client = SimpleNamespace(base_url="https://api.example", request=SimpleNamespace(get=get))
        async def executor(fn):
            await asyncio.sleep(0)
            return fn()
        service = service_type(SimpleNamespace(async_add_executor_job=executor), "media_player.test")
        async def get_client():
            return client
        service.client = get_client
        first, second = await asyncio.gather(service.recommendations(), service.recommendations())
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("eitherUserId", calls[0][1])
        self.assertEqual([s["title"] for s in first], ["A changing title from API", "Another API title"])
        self.assertEqual(first[0]["items"][0]["uid"], "7")
        self.assertEqual(first[0]["items"][0]["kind"], "1000")
        self.assertEqual(first[1]["items"][0]["type"], "album")
        self.assertEqual(first[1]["items"][0]["cover"], "https://images.example/a/400x400")
        landing["blocks"][0]["title"] = "Refreshed by Yandex"
        service._recommendations_cache = None
        refreshed = await service.recommendations()
        self.assertEqual(refreshed[0]["title"], "Refreshed by Yandex")


if __name__ == "__main__":
    unittest.main()

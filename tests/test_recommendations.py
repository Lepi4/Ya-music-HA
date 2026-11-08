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
    stubs = {"ym_test_component": package, "homeassistant": ModuleType("homeassistant"),
             "homeassistant.core": core, "yandex_music": music, "aiohttp": ModuleType("aiohttp")}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("ym_test_component.yandex", root / "yandex.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.YandexMusicService


class RecommendationsTest(unittest.IsolatedAsyncioTestCase):
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

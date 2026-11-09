"""Regional routing and semantic genre hierarchy without modifying seeds."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_recommendations import load_service

spec = importlib.util.spec_from_file_location("ym_genres", Path(__file__).resolve().parents[1] / "custom_components/yandex_music_chaos/genres.py")
genres = importlib.util.module_from_spec(spec)
spec.loader.exec_module(genres)


class GenreTest(unittest.TestCase):
    def test_regional_variants_override_api_parent(self):
        for slug, title, parent in [
            ("israelirock", "Израильский рок", "allrock"),
            ("turkishalternative", "Турецкая альтернативная музыка", "alternative"),
            ("rusrap", "Русский рэп", "rap"),
            ("latin-jazz", "Латиноамериканский джаз", ""),
            ("kpop", "K-Pop", "pop"),
            ("unknown-national-genre", "Турецкий джаз", "jazz"),
            ("tatar", "Татарская музыка", "folk"),
            ("uzbekfolk", "Узбекская народная музыка", "folk"),
            ("uzfolk", "Узбекская народная", "folk"),
        ]:
            with self.subTest(slug=slug):
                self.assertEqual(genres.genre_path(slug, title, parent), ("ethnic", ""))

    def test_regular_genres_keep_api_parent(self):
        for slug, parent in [("posthardcore", "alternative"), ("disco", "pop"), ("vocal", "classicalmusic")]:
            self.assertEqual(genres.genre_path(slug, "", parent)[0], parent)

    def test_microgenres_use_semantic_families(self):
        self.assertEqual(genres.genre_path("boogie-woogie", "Буги-вуги")[0], "dance")
        self.assertEqual(genres.genre_path("raw-black-metal"), ("metal", "Блэк-метал"))
        self.assertEqual(genres.genre_path("deep-house"), ("electronics", "Хаус"))
        self.assertEqual(genres.genre_path("psychedelic-rock"), ("allrock", "Психоделический и прогрессивный"))
        for slug in ["trance", "experimental-rock", "classic-rock"]:
            self.assertNotEqual(genres.genre_path(slug)[0], "ethnic")


class GenreCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def test_regional_catalog_is_not_truncated_and_keeps_playback_seeds(self):
        rows = [SimpleNamespace(id=SimpleNamespace(type="genre", tag=f"turkish-{i}"),
                                id_for_from=f"genre-turkish-{i}", name=f"Турецкая музыка {i}",
                                parent_id=SimpleNamespace(tag="allrock")) for i in range(65)]
        client = SimpleNamespace(rotor_stations_dashboard=lambda: SimpleNamespace(stations=rows[:2]),
                                 rotor_stations_list=lambda language: rows)
        async def executor(fn): return fn()
        service = load_service()(SimpleNamespace(async_add_executor_job=executor), "media_player.test")
        async def get_client(): return client
        service.client = get_client
        catalog = await service.rotor_stations()
        self.assertEqual(len(catalog), 65)
        self.assertTrue(all(s["genre_parent"] == "ethnic" for s in catalog))
        self.assertEqual(catalog[-1]["seed"], "genre:turkish-64")


if __name__ == "__main__":
    unittest.main()

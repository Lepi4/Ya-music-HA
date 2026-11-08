import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "yandex_music_chaos"


class StaticContractTest(unittest.TestCase):
    def test_manifest_and_translations_are_valid(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "yandex_music_chaos")
        self.assertIn("config", strings)
        self.assertIn("user", strings["config"]["step"])

    def test_backend_is_parseable_and_does_not_serve_package_root(self):
        for path in (INTEGRATION / "__init__.py", INTEGRATION / "api.py", INTEGRATION / "yandex.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(' / "www"', init)
        self.assertNotIn("Path(__file__).parent\n", init)

    def test_panel_contains_outputs_and_volume_contract(self):
        panel = (INTEGRATION / "www" / "panel.js").read_text(encoding="utf-8")
        for marker in ("ym-station", "ym-volume", "volume_set", '"seek"', "data-station", "is_yandex_station", "ym-sources-dialog"):
            self.assertIn(marker, panel)
        self.assertNotIn("access_token", panel)


if __name__ == "__main__":
    unittest.main()

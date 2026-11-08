import functools
import http.server
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InstallerTest(unittest.TestCase):
    def test_network_upgrade_preserves_config_and_old_integration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "ha"
            config.mkdir()
            (config / "configuration.yaml").write_text("# preserve me\n")
            target = config / "custom_components" / "yandex_music_chaos"
            target.mkdir(parents=True)
            (target / "old.txt").write_text("previous release")
            archive = root / "release.zip"
            with zipfile.ZipFile(archive, "w") as package:
                for path in (ROOT / "custom_components" / "yandex_music_chaos").rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        package.write(path, path.relative_to(ROOT / "custom_components" / "yandex_music_chaos"))
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                result = subprocess.run([sys.executable, str(ROOT / "scripts" / "install.py"),
                                         "--config", str(config), "--archive-url",
                                         f"http://127.0.0.1:{server.server_port}/release.zip"], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertTrue((target / "www" / "panel.js").is_file())
                self.assertEqual((config / "configuration.yaml").read_text(), "# preserve me\n")
                backups = list(target.parent.glob(".yandex_music_chaos-backup-*"))
                self.assertEqual(len(backups), 1)
                self.assertEqual((backups[0] / "old.txt").read_text(), "previous release")
                # An invalid archive must be rejected before the existing installation is moved.
                with zipfile.ZipFile(archive, "w") as package:
                    package.writestr("../escape.txt", "unsafe")
                rejected = subprocess.run(result.args, capture_output=True)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertFalse((root / "escape.txt").exists())
                self.assertTrue((target / "manifest.json").is_file())
                self.assertEqual(len(list(target.parent.glob(".yandex_music_chaos-backup-*"))), 1)
            finally:
                server.shutdown()
                server.server_close()

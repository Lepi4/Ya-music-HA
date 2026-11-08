"""Download and install a release into an explicitly selected HA config directory."""
import argparse
from datetime import datetime
import io
import json
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config", required=True, help="HA configuration directory, e.g. /config")
parser.add_argument("--version", default="v0.3.0")
parser.add_argument("--archive-url", help="Override the release archive URL")
args = parser.parse_args()
config = Path(args.config).expanduser().resolve(strict=True)
if not (config / "configuration.yaml").is_file():
    parser.error("The selected directory does not contain configuration.yaml")
url = args.archive_url or f"https://github.com/Lepi4/Ya-music-HA/releases/download/{args.version}/yandex_music_chaos.zip"
request = urllib.request.Request(url, headers={"User-Agent": "ha-yandex-music-installer"})
with urllib.request.urlopen(request, timeout=60) as response:
    payload = response.read(20 * 1024 * 1024 + 1)
if len(payload) > 20 * 1024 * 1024:
    raise SystemExit("Archive exceeds the 20 MiB limit")
components = config / "custom_components"
components.mkdir(exist_ok=True)
target = components / "yandex_music_chaos"
if target.is_symlink():
    raise SystemExit("Refusing to replace a symlink")
with tempfile.TemporaryDirectory(prefix=".ym-install-", dir=components) as temp:
    stage = Path(temp) / "yandex_music_chaos"
    stage.mkdir()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
            raise SystemExit("Expanded archive exceeds the 50 MiB limit")
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or any(":" in part for part in path.parts):
                raise SystemExit("Unsafe archive path")
            destination = stage.joinpath(*path.parts)
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(item))
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("domain") != "yandex_music_chaos":
        raise SystemExit("Wrong integration archive")
    backup = None
    if target.exists():
        backup = components / f".yandex_music_chaos-backup-{datetime.now():%Y%m%d-%H%M%S-%f}"
        target.rename(backup)
    try:
        stage.rename(target)
    except Exception:
        if backup is not None:
            backup.rename(target)
        raise
print(f"Installed {manifest['version']} into {target}")
if backup:
    print(f"Previous integration saved in {backup}")
print("Restart Home Assistant, then add or reload the Yandex Music Chaos integration.")

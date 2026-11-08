"""Build the Home Assistant integration archive without local data or caches."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
component = ROOT / "custom_components" / "yandex_music_chaos"
version = json.loads((component / "manifest.json").read_text(encoding="utf-8"))["version"]
output = ROOT / "dist"
output.mkdir(exist_ok=True)
archive = output / "yandex_music_chaos.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
    for path in sorted(component.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            package.write(path, path.relative_to(component))
    for name in ("LICENSE.md", "LICENSE-SCOPE.md"):
        package.write(ROOT / name, name)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / "SHA256SUMS").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
print(f"v{version}: {archive.name} ({archive.stat().st_size} bytes), sha256 {checksum}")

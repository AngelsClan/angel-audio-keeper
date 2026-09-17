"""Create deterministic NVDA add-on package and its checksum. No installation."""
import hashlib
from pathlib import Path
import py_compile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.0"

def build():
    source = ROOT / "addon"
    with tempfile.TemporaryDirectory() as temporary:
        for index, path in enumerate(source.rglob("*.py")):
            py_compile.compile(str(path), cfile=str(Path(temporary) / f"{index}.pyc"), doraise=True)
    target = ROOT / "dist"
    target.mkdir(exist_ok=True)
    destination = target / f"AngelAudioKeeper-{VERSION}.nvda-addon"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (2026, 9, 17, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("LICENSE.txt", (2026, 9, 17, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, (ROOT / "LICENSE").read_bytes())
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert "manifest.ini" in archive.namelist()
        assert "doc/en/readme.html" in archive.namelist()
        for name in archive.namelist():
            original = ROOT / "LICENSE" if name == "LICENSE.txt" else source / name
            assert archive.read(name) == original.read_bytes(), name
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    print(destination)
    print(f"SHA256 {digest}")
    print(f"Bytes {destination.stat().st_size}")

if __name__ == "__main__":
    build()

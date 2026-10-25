"""Install a pinned official MOPAC archive without admin rights or extra packages."""
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile

VERSION = "23.2.5"
ROOT = Path(__file__).resolve().parent
RELEASE = f"https://github.com/openmopac/mopac/releases/download/v{VERSION}"
# SHA-256 digests published on the official GitHub release asset metadata.
ASSETS = {
    "Windows": {"name": f"mopac-{VERSION}-win.zip", "folder": f"mopac-{VERSION}-win",
                "sha256": "d55b19edb043b7b467863ddeaae0c7eabf6b90b7c223598b246626d180930771",
                "executable": "bin/mopac.exe"},
    "Linux": {"name": f"mopac-{VERSION}-linux.tar.gz", "folder": f"mopac-{VERSION}-linux",
              "sha256": "bc1a814aaf58451ab743efedd967a3ed3b26f61689f562dcc9339a5c4b1a9377",
              "executable": "bin/mopac"},
}


def asset_for_platform():
    system, machine = platform.system(), platform.machine().lower()
    if system not in ASSETS or machine not in ("amd64", "x86_64"):
        raise RuntimeError("MOPAC 자동 설치는 Windows/Linux x86-64를 지원합니다. "
                           "다른 환경은 MOPAC_EXE를 지정하거나 --no-engine으로 편집기만 실행하세요.")
    return ASSETS[system]


def managed_executable(root=ROOT):
    try:
        spec = asset_for_platform()
    except RuntimeError:
        return None
    return Path(root) / "_engines" / spec["folder"] / spec["executable"]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _installed(destination, spec):
    try:
        receipt = json.loads((destination / "installation.json").read_text(encoding="utf-8"))
        if receipt["archive_sha256"] != spec["sha256"] or receipt["version"] != VERSION:
            return False
        required = {spec["executable"], "LICENSE"}
        if not required.issubset(receipt["files"]):
            return False
        for name, expected in receipt["files"].items():
            path = (destination / name).resolve()
            if not path.is_relative_to(destination.resolve()) or sha256(path) != expected:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "MOPAC-Studio/3.1"})
    with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as out:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 100 * 1024 * 1024:
                raise RuntimeError("MOPAC 다운로드가 예상 크기를 초과했습니다.")
            out.write(chunk)


def _unpack(archive, destination):
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                path = (destination / info.filename).resolve()
                if not path.is_relative_to(destination.resolve()) or "\\" in info.filename:
                    raise RuntimeError("잘못된 MOPAC 압축 파일 경로입니다.")
            zf.extractall(destination)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(destination, filter="data")


def ensure_engine(root=ROOT):
    configured = os.environ.get("MOPAC_EXE", "").strip().strip('"')
    if configured:
        executable = Path(os.path.expandvars(configured)).expanduser().resolve()
        if not executable.is_file():
            raise RuntimeError(f"MOPAC_EXE의 실행 파일이 없습니다: {executable}")
        print(f"Using configured MOPAC: {executable}", flush=True)
        return executable
    spec = asset_for_platform()
    engines = Path(root).resolve() / "_engines"
    destination = engines / spec["folder"]
    executable = destination / spec["executable"]
    if _installed(destination, spec):
        print(f"MOPAC {VERSION} is ready (no download needed).", flush=True)
        return executable
    engines.mkdir(parents=True, exist_ok=True)
    url = f"{RELEASE}/{spec['name']}"
    print(f"Downloading official MOPAC {VERSION} ...", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="install-", dir=engines) as temporary:
            stage = Path(temporary)
            archive = stage / spec["name"]
            _download(url, archive)
            if sha256(archive) != spec["sha256"]:
                raise RuntimeError("MOPAC 다운로드 체크섬이 일치하지 않아 설치를 중단했습니다.")
            unpacked = stage / "unpacked"
            unpacked.mkdir()
            _unpack(archive, unpacked)
            incoming = unpacked / spec["folder"]
            if not (incoming / spec["executable"]).is_file() or not (incoming / "LICENSE").is_file():
                raise RuntimeError("MOPAC 실행 파일 또는 라이선스가 없는 배포본입니다.")
            files = {p.relative_to(incoming).as_posix(): sha256(p)
                     for folder in ("bin", "lib") if (incoming / folder).is_dir()
                     for p in (incoming / folder).rglob("*") if p.is_file()}
            files["LICENSE"] = sha256(incoming / "LICENSE")
            receipt = {"version": VERSION, "url": url, "archive_sha256": spec["sha256"], "files": files}
            (incoming / "installation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            if destination.exists():
                # Retain a damaged/old installation rather than deleting user files.
                backup = engines / (spec["folder"] + ".previous-" + uuid.uuid4().hex[:8])
                if destination.parent.resolve() != engines or backup.parent.resolve() != engines:
                    raise RuntimeError("MOPAC 설치 경로를 확인할 수 없습니다.")
                destination.rename(backup)
            incoming.rename(destination)
    except (OSError, urllib.error.URLError, zipfile.BadZipFile, tarfile.TarError) as error:
        raise RuntimeError("공식 MOPAC 다운로드/설치에 실패했습니다. 인터넷 연결을 확인하고 "
                           "다시 실행하거나 --no-engine으로 편집기만 사용하세요. " + str(error)) from error
    print(f"Installed MOPAC {VERSION}: {executable}", flush=True)
    return executable


if __name__ == "__main__":
    try:
        ensure_engine()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

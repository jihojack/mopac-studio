"""Create a private Python environment and start the local application.

This entry point uses only the Python standard library, so it also works before
the application dependencies have been installed.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def environment_python():
    return ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_environment():
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError("Python 3.11~3.13 (64-bit)이 필요합니다. Python 3.11을 권장합니다.")
    if sys.maxsize <= 2**32:
        raise RuntimeError("64-bit Python을 설치하세요.")
    interpreter = environment_python()
    if not interpreter.is_file():
        print("Creating .venv ...", flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
    stamp = ENV / ".mopac-studio-requirements.sha256"
    expected = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    installed = stamp.read_text(encoding="ascii").strip() if stamp.is_file() else ""
    modules_ok = False
    if installed == expected:
        check = subprocess.run(
            [str(interpreter), "-c", "import flask, flask_cors, rdkit, pubchempy, requests, numpy"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        modules_ok = check.returncode == 0
    if not modules_ok:
        print("Installing dependencies from requirements.txt ...", flush=True)
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
                       cwd=ROOT, check=True)
        stamp.write_text(expected + "\n", encoding="ascii")
    return interpreter


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install and start MOPAC Studio locally")
    parser.add_argument("--setup-only", action="store_true", help="Install dependencies without starting the app")
    parser.add_argument("--background", action="store_true", help="Run the app without a persistent console")
    args = parser.parse_args(argv)
    try:
        interpreter = ensure_environment()
        if args.setup_only:
            print("Installation complete. Run Start.bat or python launcher.py.")
            return 0
        entry = ROOT / ("background_server.py" if args.background else "app.py")
        if args.background:
            options = {}
            if os.name == "nt":
                interpreter = interpreter.with_name("pythonw.exe")
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                options["start_new_session"] = True
            subprocess.Popen([str(interpreter), str(entry)], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
            print("MOPAC Studio started. Its browser tab will open automatically.")
            return 0
        return subprocess.call([str(interpreter), str(entry)], cwd=ROOT)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Installation/start failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

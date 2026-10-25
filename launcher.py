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

from engine_setup import ensure_engine

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


def ensure_desktop_environment(interpreter):
    if os.name != 'nt':
        raise RuntimeError('독립 앱 창 자동 설치는 Windows를 지원합니다. 다른 환경은 브라우저 모드를 사용하세요.')
    requirements = ROOT / 'requirements-desktop.txt'
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = ENV / '.mopac-studio-desktop.sha256'
    installed = stamp.read_text(encoding='ascii').strip() if stamp.is_file() else ''
    if installed == expected:
        check = subprocess.run([str(interpreter), '-c', 'import webview'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if check.returncode == 0:
            return
    print('Installing desktop window support ...', flush=True)
    subprocess.run([str(interpreter), '-m', 'pip', 'install', '-r', str(requirements)], cwd=ROOT, check=True)
    stamp.write_text(expected + '\n', encoding='ascii')


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install and start MOPAC Studio locally")
    parser.add_argument("--setup-only", action="store_true", help="Install dependencies without starting the app")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--background", action="store_true", help="Run the app without a persistent console")
    mode.add_argument('--desktop', action='store_true', help='Open a native Windows app window without browser tabs')
    parser.add_argument("--no-engine", action="store_true", help="Skip MOPAC installation for editor-only/offline use")
    args = parser.parse_args(argv)
    try:
        interpreter = ensure_environment()
        if not args.no_engine:
            ensure_engine(ROOT)
        if args.desktop:
            ensure_desktop_environment(interpreter)
        if args.setup_only:
            print("Installation complete. Run Start.bat or python launcher.py.")
            return 0
        entry = ROOT / ('desktop_app.py' if args.desktop else "background_server.py" if args.background else "app.py")
        if args.background or args.desktop:
            options = {}
            if os.name == "nt":
                interpreter = interpreter.with_name("pythonw.exe")
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                options["start_new_session"] = True
            if args.desktop:
                with open(ROOT / 'desktop_run.log', 'a', encoding='utf-8') as log:
                    subprocess.Popen([str(interpreter), str(entry)], cwd=ROOT,
                                     stdout=log, stderr=log, **options)
                print('MOPAC Studio desktop window started.')
            else:
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

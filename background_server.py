# -*- coding: utf-8 -*-
"""Run MOPAC Studio without a visible console window.

This is intended to be launched with pythonw.exe from the background batch file.
Console output is redirected to app_run.log so startup and request logs are still
available when the server is running headless.
"""
import os
import sys
import threading
import webbrowser

import app as app_module


app = app_module.app


HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "app_run.log")
PORT = app_module.select_available_port()


def _redirect_output():
    log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    return log


if __name__ == "__main__":
    _redirect_output()
    app_module.start_idle_shutdown_monitor(timeout_s=90)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    print(f"\n  MOPAC Studio background -> http://127.0.0.1:{PORT}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)

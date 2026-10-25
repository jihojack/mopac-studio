"""Native Windows/WebView2 window hosting the same local application."""
import os
import sys
import threading

from werkzeug.serving import make_server
from app import app, SERVER_STATE, SERVER_STATE_LOCK


def report_startup_error(message):
    print(message, file=sys.stderr)
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'MOPAC Studio', 0x10)


def main(webview_module=None):
    if webview_module is None:
        try:
            import webview as webview_module
        except ImportError:
            report_startup_error('앱 창 패키지가 없습니다. Start-Desktop.bat를 실행하세요.')
            return 1
    server = make_server('127.0.0.1', 0, app, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        webview_module.settings['ALLOW_DOWNLOADS'] = True
        window = webview_module.create_window(
            'MOPAC Studio', f'http://127.0.0.1:{server.server_port}',
            width=1440, height=960, min_size=(1000, 680), background_color='#0e1116',
            confirm_close=True, text_select=True)

        def can_close():
            with SERVER_STATE_LOCK:
                active = SERVER_STATE['active_calculations']
            if active:
                window.create_confirmation_dialog('계산 진행 중', '계산이 진행 중입니다. 계산이 끝난 뒤 종료하세요.')
                return False

        window.events.closing += can_close
        webview_module.start(gui='edgechromium' if os.name == 'nt' else None,
                             localization={'global.quitConfirmation': '앱을 종료할까요? 저장하지 않은 편집 내용은 사라집니다.',
                                           'global.ok': '확인', 'global.cancel': '취소'})
        return 0
    except Exception as error:
        report_startup_error('앱 창을 열 수 없습니다. Windows WebView2 Runtime을 확인하세요. '
                             '브라우저 모드는 Start.bat로 실행할 수 있습니다. ' + str(error))
        return 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


if __name__ == '__main__':
    raise SystemExit(main())

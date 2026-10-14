"""Run the Tidewater tests from the command line.

    python run_tests.py            # headless; prints results, exit code 1 on failure
    python run_tests.py --show     # open tests.html in your browser instead

Serves this folder on a local port, opens tests.html in headless Edge or Chrome
(set TIDEWATER_BROWSER to use another Chromium-based browser) and waits for the
page to post its results back. No packages to install.
"""
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 300  # seconds for the whole suite


def find_browser():
    if os.environ.get('TIDEWATER_BROWSER'):
        return os.environ['TIDEWATER_BROWSER']
    candidates = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge', 'msedge', 'chrome'):
        if shutil.which(name):
            return shutil.which(name)
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    results = None
    done = threading.Event()

    def do_POST(self):
        if self.path != '/report':
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        Handler.results = json.loads(body)
        self.send_response(204)
        self.end_headers()
        Handler.done.set()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')  # always test the current file
        super().end_headers()

    def log_message(self, *args):
        pass


def main():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=HERE))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_address[1]}/tests.html'

    if '--show' in sys.argv:
        print(f'Tests running at {url}  (Ctrl+C to stop)')
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            return 0

    browser = find_browser()
    if not browser:
        print('No Edge or Chrome found. Set TIDEWATER_BROWSER, or run with --show to use your default browser.')
        return 2
    profile = tempfile.mkdtemp(prefix='tidewater-tests-')
    proc = subprocess.Popen([browser, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                             '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                             f'--user-data-dir={profile}', '--window-size=1280,1000', url + '?ci'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        finished = Handler.done.wait(TIMEOUT)
    finally:
        proc.kill()
        proc.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    if not finished:
        print(f'Timed out after {TIMEOUT}s waiting for results.')
        return 1

    results = Handler.results
    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name'].replace('›', '>')}  ({r.get('ms', 0)} ms)")
        if not r['ok']:
            for line in str(r['err']).splitlines():
                print('      ' + line)
    failed = sum(not r['ok'] for r in results)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

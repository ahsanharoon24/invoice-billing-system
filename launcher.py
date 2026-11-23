"""Launcher — starts the server and opens the web UI in the browser automatically.

run.bat calls this script so the user never has to deal with a CLI window:
the browser opens by itself and the software is ready.
"""
import os
import sys
import threading
import time
import urllib.request
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from app import app, init_db, seed_admin, auto_backup_if_due

init_db()
seed_admin()
auto_backup_if_due()


def _run_server():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


threading.Thread(target=_run_server, daemon=True).start()

# wait until the server is ready, then open the browser
for _ in range(80):
    try:
        urllib.request.urlopen('http://localhost:5000/login', timeout=1)
        break
    except Exception:
        time.sleep(0.25)

webbrowser.open('http://localhost:5000')

print('=' * 56)
print('  Invoice & Billing Management System')
print('  Opening in your browser: http://localhost:5000')
print('  Office PCs: http://<this-PC-IP>:5000')
print('  To stop the server, close this window.')
print('=' * 56)

# keep the main thread alive (server runs in a daemon thread)
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass

"""Gunicorn entry point for production deployment.

Run:  gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app
(Nginx proxies to this port.)

This also sets up the database / admin seed / auto-backup at import time —
the same job launcher.py does for local use.
"""
import os

# production: secret key comes from the environment
if not os.environ.get('SECRET_KEY'):
    print('WARNING: SECRET_KEY environment variable is not set - using the default. '
          'Set Environment=SECRET_KEY=... in the systemd service.')

from app import app, init_db, seed_admin, auto_backup_if_due  # noqa: E402

init_db()
seed_admin()
auto_backup_if_due()

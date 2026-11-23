"""Database helpers — SQLite connection, schema init, audit logging."""
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'invoices.db')
# --- Serverless (Vercel) support: only /tmp is writable -----------------
if os.environ.get('VERCEL'):
    import shutil as _shutil
    DB_PATH = '/tmp/invoices.db'
    _src = os.path.join(BASE_DIR, 'invoices.db')
    if not os.path.exists(DB_PATH) and os.path.exists(_src):
        _shutil.copyfile(_src, DB_PATH)

SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')


def get_db():
    """Open a connection with row access + foreign keys on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 5000')  # multi-worker SQLite safety
    return conn


def init_db():
    """Create tables if missing and seed defaults."""
    with open(SCHEMA_PATH, encoding='utf-8') as f:
        schema = f.read()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema)


def audit(user, action, entity='', entity_id=None, details=''):
    """Write an audit log row (best-effort, never breaks the caller)."""
    try:
        with get_db() as conn:
            conn.execute(
                'INSERT INTO audit_log (user_id, username, action, entity, entity_id, details) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (user.get('id') if user else None,
                 user.get('username') if user else 'system',
                 action, entity, entity_id, details[:2000]))
    except Exception:
        pass


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

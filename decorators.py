"""Shared auth decorators + permission helpers (no circular imports)."""
from functools import wraps

from flask import redirect, request, session, url_for, flash

from db import get_db

ROLES = {'admin': 'Administrator', 'billing_officer': 'Billing Officer', 'viewer': 'Viewer'}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE id = ? AND is_active = 1',
                                (session['user_id'],)).fetchone()
        if not user:
            session.clear()
            return redirect(url_for('login'))
        session['user'] = dict(user)
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = session.get('user') or {}
            if user.get('role') not in roles:
                flash('You do not have permission to open this page.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return deco


def can_edit():
    """Admin + Billing Officer can create/edit invoices, clients, payments."""
    return (session.get('user') or {}).get('role') in ('admin', 'billing_officer')


def current_user():
    return session.get('user')


def current_uid():
    u = session.get('user')
    return u.get('id') if u else None

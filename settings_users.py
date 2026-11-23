"""Company Settings + User Management."""
import os

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from decorators import login_required, role_required
from db import get_db, audit, now

bp = Blueprint('settings', __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')


# ==================================================================
# Company settings
# ==================================================================
@bp.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def settings_page():
    if request.method == 'POST':
        with get_db() as conn:
            conn.execute(
                '''UPDATE company_settings SET company_name=?, address=?, phone=?, email=?,
                   ntn=?, strn=?, bank_name=?, account_title=?, account_number=?, iban=?,
                   gst_percent=?, invoice_prefix=?, invoice_start_number=?,
                   authorized_signatory=?, invoice_footer=?, updated_at=? WHERE id=1''',
                (request.form.get('company_name', '').strip(),
                 request.form.get('address', '').strip(),
                 request.form.get('phone', '').strip(),
                 request.form.get('email', '').strip(),
                 request.form.get('ntn', '').strip(),
                 request.form.get('strn', '').strip(),
                 request.form.get('bank_name', '').strip(),
                 request.form.get('account_title', '').strip(),
                 request.form.get('account_number', '').strip(),
                 request.form.get('iban', '').strip(),
                 float(request.form.get('gst_percent') or 0),
                 request.form.get('invoice_prefix', 'CC').strip() or 'CC',
                 int(request.form.get('invoice_start_number') or 1),
                 request.form.get('authorized_signatory', '').strip(),
                 request.form.get('invoice_footer', '').strip(),
                 now()))
        # logo / signature uploads
        for field, col in (('logo', 'logo_path'), ('signature', 'signature_path')):
            f = request.files.get(field)
            if f and f.filename:
                ext = os.path.splitext(f.filename)[1].lower()
                if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                    flash(f'{field} must be an image file.', 'error')
                    continue
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                name = f'{col}_{now().replace(":", "").replace(" ", "_")}{ext}'
                path = os.path.join(UPLOAD_DIR, name)
                f.save(path)
                with get_db() as conn:
                    conn.execute(f'UPDATE company_settings SET {col} = ?, updated_at = ? WHERE id = 1',
                                 (f'uploads/{name}', now()))
        audit(session['user'], 'settings_update', 'settings', 1, 'Company settings updated')
        flash('Company settings saved.', 'success')
        return redirect(url_for('settings.settings_page'))

    with get_db() as conn:
        s = conn.execute('SELECT * FROM company_settings WHERE id = 1').fetchone()
    return render_template('settings.html', s=s)


# ==================================================================
# User management (admin only)
# ==================================================================
@bp.route('/users')
@login_required
@role_required('admin')
def user_list():
    with get_db() as conn:
        users = conn.execute('SELECT * FROM users ORDER BY id').fetchall()
    return render_template('users.html', users=users)


@bp.route('/users/add', methods=['POST'])
@login_required
@role_required('admin')
def user_add():
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role') if request.form.get('role') in ('admin', 'billing_officer', 'viewer') else 'viewer'
    if not username or not full_name or len(password) < 6:
        flash('Username, full name and a 6+ character password are required.', 'error')
        return redirect(url_for('settings.user_list'))
    with get_db() as conn:
        if conn.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone():
            flash('This username already exists.', 'error')
            return redirect(url_for('settings.user_list'))
        conn.execute('INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)',
                     (username, generate_password_hash(password), full_name, role))
    audit(session['user'], 'user_add', 'user', None, f'{username} ({role})')
    flash(f'User "{full_name}" added.', 'success')
    return redirect(url_for('settings.user_list'))


@bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def user_toggle(user_id):
    if user_id == session['user']['id']:
        flash('You cannot deactivate your own account.', 'error')
        return redirect(url_for('settings.user_list'))
    with get_db() as conn:
        u = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not u:
            abort(404)
        conn.execute('UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?',
                     (0 if u['is_active'] else 1, now(), user_id))
    audit(session['user'], 'user_toggle', 'user', user_id, f"{u['username']} -> active={u['is_active']}")
    flash('User status changed.', 'success')
    return redirect(url_for('settings.user_list'))


@bp.route('/users/<int:user_id>/password', methods=['POST'])
@login_required
@role_required('admin')
def user_password(user_id):
    new_pw = request.form.get('new_password', '')
    if len(new_pw) < 6:
        flash('Password must be at least 6 characters.', 'error')
        return redirect(url_for('settings.user_list'))
    with get_db() as conn:
        conn.execute('UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?',
                     (generate_password_hash(new_pw), now(), user_id))
    audit(session['user'], 'user_password_reset', 'user', user_id, 'password reset by admin')
    flash('User password reset.', 'success')
    return redirect(url_for('settings.user_list'))

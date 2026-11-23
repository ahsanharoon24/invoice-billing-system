"""Invoice & Billing Management System — main application (generic demo)."""
import os
import shutil
import zipfile
from datetime import datetime, timedelta

from flask import (Flask, redirect, render_template, request, session,
                   url_for, flash, send_file, abort)

from werkzeug.security import check_password_hash, generate_password_hash

import db
import utils
from db import get_db, init_db, audit, now
from decorators import login_required, role_required, can_edit, ROLES

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clean-capital-billing-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB uploads (logo/signature/backup)

_WRITABLE = '/tmp' if os.environ.get('VERCEL') else db.BASE_DIR
BACKUP_DIR = os.path.join(_WRITABLE, 'backups')
UPLOAD_DIR = os.path.join(_WRITABLE, 'uploads') if os.environ.get('VERCEL') else os.path.join(db.BASE_DIR, 'static', 'uploads')
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==================================================================
# Auth routes
# ==================================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and user['is_active'] and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['user'] = dict(user)
            audit(session['user'], 'login', 'user', user['id'], f"{user['full_name']} logged in")
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Wrong username or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    audit(session.get('user'), 'logout', 'user', session.get('user_id'))
    session.clear()
    return redirect(url_for('login'))


@app.route('/password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        user = session.get('user')
        with get_db() as conn:
            db_user = conn.execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone()
        if not check_password_hash(db_user['password_hash'], old):
            flash('Old password is wrong.', 'error')
        elif len(new) < 6:
            flash('New password must be at least 6 characters.', 'error')
        elif new != confirm:
            flash('New password and confirm password do not match.', 'error')
        else:
            with get_db() as conn:
                conn.execute('UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?',
                             (generate_password_hash(new), now(), user['id']))
            audit(user, 'password_change', 'user', user['id'])
            flash('Password changed successfully.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('change_password.html')


# ==================================================================
# Dashboard
# ==================================================================
@app.route('/')
@login_required
def dashboard():
    with get_db() as conn:
        total_clients = conn.execute(
            'SELECT COUNT(*) c FROM clients WHERE is_deleted = 0').fetchone()['c']
        active_clients = conn.execute(
            'SELECT COUNT(*) c FROM clients WHERE is_deleted = 0 AND status = "active"').fetchone()['c']
        total_invoices = conn.execute(
            'SELECT COUNT(*) c FROM invoices WHERE is_deleted = 0 AND status != "draft"').fetchone()['c']

        m = utils.this_month()
        cur_month = conn.execute(
            'SELECT COALESCE(SUM(total_amount), 0) s, COALESCE(SUM(gst_amount), 0) g '
            'FROM invoices WHERE billing_month = ? AND is_deleted = 0 AND status != "cancelled" AND status != "draft"',
            (m,)).fetchone()
        current_month_billing = cur_month['s']
        current_month_gst = cur_month['g']

        paid_tot = conn.execute(
            'SELECT COALESCE(SUM(amount), 0) s FROM payments').fetchone()['s']
        outstanding = conn.execute(
            'SELECT COALESCE(SUM(i.total_amount), 0) - (SELECT COALESCE(SUM(p.amount), 0) FROM payments p '
            'JOIN invoices iv ON p.invoice_id = iv.id WHERE iv.is_deleted = 0) AS s '
            'FROM invoices i WHERE i.is_deleted = 0 AND i.status != "cancelled" AND i.status != "draft"').fetchone()['s']

        recent = conn.execute(
            'SELECT i.*, c.client_name FROM invoices i JOIN clients c ON c.id = i.client_id '
            'WHERE i.is_deleted = 0 ORDER BY i.id DESC LIMIT 10').fetchall()

        # clients tab: active vs inactive (limit 10 each for the dashboard view)
        active_client_rows = conn.execute(
            'SELECT id, client_name, company_name, phone, location, monthly_service_charges '
            'FROM clients WHERE is_deleted = 0 AND status = "active" '
            'ORDER BY client_name LIMIT 10').fetchall()
        inactive_client_rows = conn.execute(
            'SELECT id, client_name, company_name, phone, location, monthly_service_charges '
            'FROM clients WHERE is_deleted = 0 AND status = "inactive" '
            'ORDER BY client_name LIMIT 10').fetchall()
        inactive_clients_count = conn.execute(
            'SELECT COUNT(*) c FROM clients WHERE is_deleted = 0 AND status = "inactive"'
        ).fetchone()['c']

        status_counts = {}
        for st in ('draft', 'issued', 'partially_paid', 'paid', 'cancelled'):
            status_counts[st] = conn.execute(
                'SELECT COUNT(*) c FROM invoices WHERE status = ? AND is_deleted = 0', (st,)).fetchone()['c']

    return render_template('dashboard.html',
                           total_clients=total_clients, active_clients=active_clients,
                           total_invoices=total_invoices, current_month_billing=current_month_billing,
                           current_month_gst=current_month_gst, paid_tot=paid_tot,
                           outstanding=outstanding, recent=recent, status_counts=status_counts,
                           active_client_rows=active_client_rows,
                           inactive_client_rows=inactive_client_rows,
                           inactive_clients_count=inactive_clients_count,
                           month_label=utils.month_label, format_pkr=utils.format_pkr,
                           effective_status=utils.effective_status)


# ==================================================================
# Backup system
# ==================================================================
def create_backup(conn=None):
    """Zip the SQLite DB into backups/ with timestamp. Returns file path or None."""
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_path = os.path.join(BACKUP_DIR, f'backup_{ts}.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(db.DB_PATH, arcname='invoices.db')
        return zip_path
    except Exception:
        return None


def auto_backup_if_due():
    """Keep a daily auto-backup; prune to the last 30 files."""
    try:
        files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith('backup_') and f.endswith('.zip'))
        if files:
            last = os.path.getmtime(os.path.join(BACKUP_DIR, files[-1]))
            if datetime.now().timestamp() - last < 86400:
                return  # backup less than 24h old
        create_backup()
        files = sorted(os.listdir(BACKUP_DIR))
        while len(files) > 30:  # keep last 30 backups
            os.remove(os.path.join(BACKUP_DIR, files[0]))
            files = files[1:]
    except Exception:
        pass


@app.route('/backup', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def backup_page():
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'create':
            path = create_backup()
            if path:
                audit(session['user'], 'backup_create', 'backup', None, os.path.basename(path))
                flash(f'Backup created: {os.path.basename(path)}', 'success')
            else:
                flash('Backup failed.', 'error')
        elif action == 'restore':
            file = request.files.get('backup_file')
            if file and file.filename.endswith('.zip'):
                tmp = os.path.join(BACKUP_DIR, '_restore_tmp.zip')
                file.save(tmp)
                try:
                    # safety backup of current DB before overwriting
                    create_backup()
                    with zipfile.ZipFile(tmp) as zf:
                        zf.extract('invoices.db', db.BASE_DIR + '_restore')
                    shutil.copy(os.path.join(db.BASE_DIR + '_restore', 'invoices.db'), db.DB_PATH)
                    shutil.rmtree(db.BASE_DIR + '_restore', ignore_errors=True)
                    audit(session['user'], 'backup_restore', 'backup', None, file.filename)
                    flash('Database restored. Please login again.', 'success')
                    session.clear()
                    return redirect(url_for('login'))
                except Exception as e:
                    flash(f'Restore failed: {e}', 'error')
                finally:
                    os.remove(tmp) if os.path.exists(tmp) else None
            else:
                flash('Please select a valid .zip backup file.', 'error')
    backups = sorted(os.listdir(BACKUP_DIR), reverse=True)
    backup_info = []
    for b in backups:
        p = os.path.join(BACKUP_DIR, b)
        backup_info.append({'name': b, 'size': os.path.getsize(p),
                            'time': datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')})
    return render_template('backup.html', backups=backup_info)


@app.route('/backup/download/<name>')
@login_required
@role_required('admin')
def backup_download(name):
    if '..' in name or not name.startswith('backup_'):
        abort(400)
    p = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(p):
        abort(404)
    audit(session['user'], 'backup_download', 'backup', None, name)
    return send_file(p, as_attachment=True)


# ==================================================================
# Audit log (admin)
# ==================================================================
@app.route('/audit')
@login_required
@role_required('admin')
def audit_log():
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM audit_log ORDER BY id DESC LIMIT 200').fetchall()
    return render_template('audit.html', rows=rows)


# ==================================================================
# Blueprints
# ==================================================================
from clients import bp as clients_bp
from invoices import bp as invoices_bp
from reports import bp as reports_bp
from settings_users import bp as settings_bp

app.register_blueprint(clients_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(settings_bp)


# ==================================================================
# Context helpers + startup
# ==================================================================
@app.context_processor
def inject_globals():
    settings = {}
    try:
        with get_db() as conn:
            row = conn.execute('SELECT * FROM company_settings WHERE id = 1').fetchone()
            settings = dict(row) if row else {}
    except Exception:
        pass
    return dict(ROLES=ROLES, can_edit=can_edit(), settings=settings)


@app.template_filter('pkr')
def pkr_filter(value):
    return utils.format_pkr(value)


@app.template_filter('month')
def month_filter(value):
    return utils.month_label(value)


def seed_admin():
    """Create the default admin account on first run."""
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            conn.execute(
                'INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)',
                ('admin', generate_password_hash('admin123'), 'Administrator', 'admin'))
            print('=' * 60)
            print('  DEFAULT LOGIN CREATED:')
            print('    Username: admin')
            print('    Password: admin123')
            print('  (Login ke baad password change kar lein!)')
            print('=' * 60)


if __name__ == '__main__':
    init_db()
    seed_admin()
    auto_backup_if_due()
    # 0.0.0.0 so any PC on the office network can access via browser
    app.run(host='0.0.0.0', port=5000, debug=False)
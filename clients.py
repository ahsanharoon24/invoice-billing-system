"""Client Management — add, edit, view, search, deactivate, profile with history."""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from decorators import login_required, role_required, can_edit, current_user, current_uid
from db import get_db, audit, now
import utils

bp = Blueprint('clients', __name__)


@bp.route('/clients')
@login_required
def client_list():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    page = max(int(request.args.get('page', 1)), 1)
    per_page = 20

    sql = 'SELECT * FROM clients WHERE is_deleted = 0'
    args = []
    if q:
        sql += (' AND (client_name LIKE ? OR company_name LIKE ? OR phone LIKE ? '
                'OR contact_person LIKE ? OR location LIKE ?)')
        like = f'%{q}%'
        args += [like, like, like, like, like]
    if status in ('active', 'inactive'):
        sql += ' AND status = ?'
        args.append(status)

    with get_db() as conn:
        total = conn.execute(sql.replace('SELECT *', 'SELECT COUNT(*) c', 1), args).fetchone()['c']
        rows = conn.execute(sql + ' ORDER BY client_name LIMIT ? OFFSET ?',
                            args + [per_page, (page - 1) * per_page]).fetchall()

    pages = max(1, (total + per_page - 1) // per_page)
    return render_template('clients/list.html', clients=rows, q=q, status=status,
                           page=page, pages=pages, total=total,
                           format_pkr=utils.format_pkr)


@bp.route('/clients/add', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'billing_officer')
def client_add():
    if request.method == 'POST':
        data = _client_form(request)
        with get_db() as conn:
            cur = conn.execute(
                '''INSERT INTO clients
                   (client_name, company_name, contact_person, phone, email, address,
                    location, ntn, strn, contract_start_date, contract_end_date,
                    monthly_service_charges, default_units, default_per_unit_charges,
                    bank_details, notes, status, created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (data['client_name'], data['company_name'], data['contact_person'],
                 data['phone'], data['email'], data['address'], data['location'],
                 data['ntn'], data['strn'], data['contract_start_date'],
                 data['contract_end_date'], data['monthly_service_charges'],
                 data['default_units'], data['default_per_unit_charges'],
                 data['bank_details'], data['notes'], data['status'], session_uid()))
            client_id = cur.lastrowid
        audit(session_user(), 'client_add', 'client', client_id, data['client_name'])
        flash(f"Client '{data['client_name']}' added successfully.", 'success')
        return redirect(url_for('clients.client_profile', client_id=client_id))
    return render_template('clients/form.html', client=None)


@bp.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'billing_officer')
def client_edit(client_id):
    with get_db() as conn:
        client = conn.execute('SELECT * FROM clients WHERE id = ? AND is_deleted = 0',
                              (client_id,)).fetchone()
        if not client:
            flash('Client not found.', 'error')
            return redirect(url_for('clients.client_list'))
        if request.method == 'POST':
            data = _client_form(request)
            conn.execute(
                '''UPDATE clients SET client_name=?, company_name=?, contact_person=?,
                   phone=?, email=?, address=?, location=?, ntn=?, strn=?,
                   contract_start_date=?, contract_end_date=?, monthly_service_charges=?,
                   default_units=?, default_per_unit_charges=?, bank_details=?, notes=?,
                   status=?, updated_at=? WHERE id=?''',
                (data['client_name'], data['company_name'], data['contact_person'],
                 data['phone'], data['email'], data['address'], data['location'],
                 data['ntn'], data['strn'], data['contract_start_date'],
                 data['contract_end_date'], data['monthly_service_charges'],
                 data['default_units'], data['default_per_unit_charges'],
                 data['bank_details'], data['notes'], data['status'], now(), client_id))
            audit(session_user(), 'client_edit', 'client', client_id, data['client_name'])
            flash('Client updated successfully.', 'success')
            return redirect(url_for('clients.client_profile', client_id=client_id))
    return render_template('clients/form.html', client=client)


@bp.route('/clients/<int:client_id>')
@login_required
def client_profile(client_id):
    with get_db() as conn:
        client = conn.execute('SELECT * FROM clients WHERE id = ? AND is_deleted = 0',
                              (client_id,)).fetchone()
        if not client:
            flash('Client not found.', 'error')
            return redirect(url_for('clients.client_list'))
        invoices = conn.execute(
            'SELECT * FROM invoices WHERE client_id = ? AND is_deleted = 0 ORDER BY id DESC',
            (client_id,)).fetchall()
        # totals
        billed = sum(i['total_amount'] for i in invoices if i['status'] != 'cancelled')
        paid = 0
        for i in invoices:
            p = conn.execute('SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id = ?',
                             (i['id'],)).fetchone()['s']
            paid += p
        outstanding = billed - paid
    return render_template('clients/profile.html', client=client, invoices=invoices,
                           billed=billed, paid=paid, outstanding=outstanding,
                           format_pkr=utils.format_pkr, month_label=utils.month_label,
                           effective_status=utils.effective_status)


@bp.route('/clients/<int:client_id>/deactivate', methods=['POST'])
@login_required
@role_required('admin')
def client_deactivate(client_id):
    """Soft-deactivate: never delete a client that has invoices."""
    with get_db() as conn:
        client = conn.execute('SELECT * FROM clients WHERE id = ?', (client_id,)).fetchone()
        if not client:
            abort(404)
        invoices = conn.execute('SELECT COUNT(*) c FROM invoices WHERE client_id = ? AND is_deleted = 0',
                                (client_id,)).fetchone()['c']
        new_status = 'inactive' if client['status'] == 'active' else 'active'
        conn.execute('UPDATE clients SET status = ?, updated_at = ? WHERE id = ?',
                     (new_status, now(), client_id))
        audit(session_user(), 'client_status', 'client', client_id,
              f"{client['client_name']} -> {new_status} ({invoices} invoices)")
    flash(f"Client '{client['client_name']}' is now {new_status}.", 'success')
    return redirect(url_for('clients.client_profile', client_id=client_id))


@bp.route('/clients/<int:client_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def client_delete(client_id):
    """Safe delete: only permanently deletes clients that have NO invoices.
    Clients with invoices can never be deleted."""
    with get_db() as conn:
        client = conn.execute('SELECT * FROM clients WHERE id = ? AND is_deleted = 0',
                              (client_id,)).fetchone()
        if not client:
            flash('Client not found.', 'error')
            return redirect(url_for('clients.client_list'))
        invoices = conn.execute(
            'SELECT COUNT(*) c FROM invoices WHERE client_id = ? AND is_deleted = 0',
            (client_id,)).fetchone()['c']
        if invoices > 0:
            flash(f'Cannot delete — this client has {invoices} invoice(s). '
                  f'Use Deactivate to keep the history.', 'error')
            return redirect(url_for('clients.client_profile', client_id=client_id))
        conn.execute('DELETE FROM clients WHERE id = ?', (client_id,))
    audit(session_user(), 'client_delete', 'client', client_id, client['client_name'])
    flash(f"Client '{client['client_name']}' deleted permanently.", 'success')
    return redirect(url_for('clients.client_list'))


def _client_form(request):
    def f(k, default=''):
        return request.form.get(k, default).strip()
    return {
        'client_name': f('client_name'),
        'company_name': f('company_name'),
        'contact_person': f('contact_person'),
        'phone': f('phone'),
        'email': f('email'),
        'address': f('address'),
        'location': f('location'),
        'ntn': f('ntn'),
        'strn': f('strn'),
        'contract_start_date': f('contract_start_date'),
        'contract_end_date': f('contract_end_date'),
        'monthly_service_charges': float(f('monthly_service_charges', '0') or 0),
        'default_units': float(f('default_units', '0') or 0),
        'default_per_unit_charges': float(f('default_per_unit_charges', '0') or 0),
        'bank_details': f('bank_details'),
        'notes': f('notes'),
        'status': f('status') if f('status') in ('active', 'inactive') else 'active',
    }


def session_user():
    from flask import session
    return session.get('user')


def session_uid():
    from flask import session
    u = session.get('user')
    return u.get('id') if u else None


from flask import abort  # noqa: E402

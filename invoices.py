"""Invoice Management — create, calculate, number, search, print, next-month, payments."""
import sqlite3
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for)

from decorators import login_required, role_required, current_user, current_uid
from db import get_db, audit, now
import utils

bp = Blueprint('invoices', __name__)


def _settings(conn):
    return conn.execute('SELECT * FROM company_settings WHERE id = 1').fetchone()


def _uid():
    u = session.get('user')
    return u.get('id') if u else None


def _uname():
    u = session.get('user')
    return u.get('username') if u else ''


# ==================================================================
# Invoice list + search
# ==================================================================
@bp.route('/invoices')
@login_required
def invoice_list():
    q = request.args.get('q', '').strip()
    month = request.args.get('month', '').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    status = request.args.get('status', '').strip()
    client_id = request.args.get('client_id', '').strip()
    page = max(int(request.args.get('page', 1)), 1)
    per_page = 25

    sql = ('SELECT i.*, c.client_name, c.company_name FROM invoices i '
           'JOIN clients c ON c.id = i.client_id WHERE i.is_deleted = 0')
    args = []
    if q:
        sql += (' AND (i.invoice_number LIKE ? OR c.client_name LIKE ? '
                'OR c.company_name LIKE ? OR c.phone LIKE ?)')
        like = f'%{q}%'
        args += [like, like, like, like]
    if month:
        sql += ' AND i.billing_month = ?'
        args.append(month)
    if date_from:
        sql += ' AND i.invoice_date >= ?'
        args.append(date_from)
    if date_to:
        sql += ' AND i.invoice_date <= ?'
        args.append(date_to)
    if status in ('draft', 'issued', 'partially_paid', 'paid', 'cancelled'):
        sql += ' AND i.status = ?'
        args.append(status)
    if client_id.isdigit():
        sql += ' AND i.client_id = ?'
        args.append(int(client_id))

    with get_db() as conn:
        total = conn.execute(sql.replace('SELECT i.*, c.client_name, c.company_name', 'SELECT COUNT(*) c', 1),
                             args).fetchone()['c']
        rows = conn.execute(sql + ' ORDER BY i.id DESC LIMIT ? OFFSET ?',
                            args + [per_page, (page - 1) * per_page]).fetchall()
        paid_map = {}
        for r in rows:
            paid_map[r['id']] = conn.execute(
                'SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id = ?',
                (r['id'],)).fetchone()['s']

    pages = max(1, (total + per_page - 1) // per_page)
    return render_template('invoices/list.html', invoices=rows, q=q, month=month,
                           date_from=date_from, date_to=date_to, status=status,
                           page=page, pages=pages, total=total, paid_map=paid_map,
                           format_pkr=utils.format_pkr, month_label=utils.month_label,
                           effective_status=utils.effective_status)


# ==================================================================
# Create invoice
# ==================================================================
@bp.route('/invoices/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'billing_officer')
def invoice_new():
    conn = get_db()
    settings = _settings(conn)
    clients = conn.execute(
        'SELECT id, client_name, company_name FROM clients WHERE is_deleted = 0 '
        'ORDER BY client_name').fetchall()
    conn.close()

    preselected = request.args.get('client_id', '')
    prefill = None
    if preselected.isdigit():
        with get_db() as c:
            prefill = c.execute('SELECT * FROM clients WHERE id = ? AND is_deleted = 0',
                                (int(preselected),)).fetchone()

    if request.method == 'POST':
        return _save_invoice(None)

    return render_template('invoices/form.html', invoice=None, clients=clients,
                           settings=settings, prefill=prefill,
                           default_month=utils.this_month(),
                           today=date.today().isoformat(),
                           format_pkr=utils.format_pkr)


def _save_invoice(invoice_id):
    """Shared save logic for create (invoice_id=None) and edit."""
    form = request.form
    client_id = int(form.get('client_id') or 0)
    billing_month = (form.get('billing_month') or '').strip()
    invoice_date = (form.get('invoice_date') or '').strip()
    service_desc = (form.get('service_description') or '').strip()
    units = float(form.get('units') or 0)
    per_unit = float(form.get('per_unit_charges') or 0)
    monthly = float(form.get('monthly_service_charges') or 0)
    other = float(form.get('other_charges') or 0)
    gst_pct = float(form.get('gst_percent') or 0)
    start_date = (form.get('start_date') or '').strip()
    end_date = (form.get('end_date') or '').strip()
    status = form.get('status') if form.get('status') in ('draft', 'issued') else 'draft'
    notes = (form.get('notes') or '').strip()

    if not client_id or not billing_month or not invoice_date:
        flash('Client, Billing Month and Invoice Date are required.', 'error')
        return redirect(url_for('invoices.invoice_new'))
    if not (service_desc or units or per_unit or monthly):
        flash('Service description or charges are required.', 'error')
        return redirect(url_for('invoices.invoice_new'))

    calc = utils.calc_invoice(units, per_unit, monthly, other, gst_pct)

    with get_db() as conn:
        client = conn.execute('SELECT * FROM clients WHERE id = ? AND is_deleted = 0',
                              (client_id,)).fetchone()
        if not client:
            flash('Client not found.', 'error')
            return redirect(url_for('invoices.invoice_new'))
        settings = _settings(conn)

        # ----- duplicate protection: same client + billing month -----
        if invoice_id is None:
            dup = conn.execute(
                'SELECT invoice_number FROM invoices WHERE client_id = ? AND billing_month = ? '
                'AND status != "cancelled" AND is_deleted = 0', (client_id, billing_month)).fetchone()
            if dup:
                flash(f'Duplicate invoice blocked! This client already has an invoice for {utils.month_label(billing_month)} '
                      f'({dup["invoice_number"]}).', 'error')
                return redirect(url_for('invoices.invoice_new', client_id=client_id))

        prefix = settings['invoice_prefix'] or 'CC'
        year = billing_month[:4]

        if invoice_id is None:
            # transaction-safe numbering + insert
            conn.execute('BEGIN IMMEDIATE')
            try:
                number, seq = utils.next_invoice_number(conn, prefix, year)
                cur = conn.execute(
                    '''INSERT INTO invoices
                       (invoice_number, invoice_date, billing_month, client_id,
                        service_description, units, per_unit_charges,
                        monthly_service_charges, other_charges, subtotal,
                        gst_percent, gst_amount, total_amount, start_date, end_date,
                        status, notes, company_name, company_address, company_phone,
                        company_email, company_ntn, company_strn, bank_name,
                        account_title, account_number, iban, authorized_signatory,
                        created_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (number, invoice_date, billing_month, client_id,
                     service_desc, units, per_unit, monthly, other,
                     calc['subtotal'], gst_pct, calc['gst_amount'], calc['total_amount'],
                     start_date, end_date, status, notes,
                     settings['company_name'], settings['address'], settings['phone'],
                     settings['email'], settings['ntn'], settings['strn'],
                     settings['bank_name'], settings['account_title'],
                     settings['account_number'], settings['iban'],
                     settings['authorized_signatory'], _uid()))
                new_id = cur.lastrowid
                conn.commit()
            except sqlite3.IntegrityError as e:
                conn.rollback()
                flash(f'Invoice could not be saved (duplicate number/month?): {e}', 'error')
                return redirect(url_for('invoices.invoice_new', client_id=client_id))
            audit(session.get('user'), 'invoice_create', 'invoice', new_id,
                  f'{number} | {client["client_name"]} | {utils.month_label(billing_month)} | {calc["total_amount"]}')
            flash(f'Invoice {number} created.', 'success')
            return redirect(url_for('invoices.invoice_view', invoice_id=new_id))
        else:
            # ----- edit: only if no payments recorded yet -----
            existing = conn.execute('SELECT * FROM invoices WHERE id = ? AND is_deleted = 0',
                                    (invoice_id,)).fetchone()
            if not existing:
                flash('Invoice not found.', 'error')
                return redirect(url_for('invoices.invoice_list'))
            has_payments = conn.execute('SELECT 1 FROM payments WHERE invoice_id = ? LIMIT 1',
                                        (invoice_id,)).fetchone()
            if has_payments:
                flash('This invoice already has payments — you cannot edit the amount. '
                      f'Cancel the invoice and create a new one.', 'error')
                return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))
            conn.execute(
                '''UPDATE invoices SET invoice_date=?, billing_month=?, client_id=?,
                   service_description=?, units=?, per_unit_charges=?, monthly_service_charges=?,
                   other_charges=?, subtotal=?, gst_percent=?, gst_amount=?, total_amount=?,
                   start_date=?, end_date=?, status=?, notes=?, updated_at=?
                   WHERE id=?''',
                (invoice_date, billing_month, client_id, service_desc, units, per_unit,
                 monthly, other, calc['subtotal'], gst_pct, calc['gst_amount'],
                 calc['total_amount'], start_date, end_date, status, notes, now(), invoice_id))
            audit(session.get('user'), 'invoice_edit', 'invoice', invoice_id,
                  f'{existing["invoice_number"]} | total {calc["total_amount"]}')
            flash(f'Invoice {existing["invoice_number"]} updated.', 'success')
            return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))


# ==================================================================
# View / edit / print
# ==================================================================
@bp.route('/invoices/<int:invoice_id>')
@login_required
def invoice_view(invoice_id):
    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ? AND is_deleted = 0',
                           (invoice_id,)).fetchone()
        if not inv:
            flash('Invoice not found.', 'error')
            return redirect(url_for('invoices.invoice_list'))
        client = conn.execute('SELECT * FROM clients WHERE id = ?', (inv['client_id'],)).fetchone()
        payments = conn.execute('SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date',
                                (invoice_id,)).fetchall()
        paid = sum(p['amount'] for p in payments)
    return render_template('invoices/view.html', inv=inv, client=client,
                           payments=payments, paid=paid, remaining=inv['total_amount'] - paid,
                           format_pkr=utils.format_pkr, month_label=utils.month_label,
                           amount_in_words=utils.amount_in_words,
                           effective_status=utils.effective_status)


@bp.route('/invoices/<int:invoice_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'billing_officer')
def invoice_edit(invoice_id):
    if request.method == 'POST':
        return _save_invoice(invoice_id)
    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ? AND is_deleted = 0',
                           (invoice_id,)).fetchone()
        if not inv:
            flash('Invoice not found.', 'error')
            return redirect(url_for('invoices.invoice_list'))
        has_payments = conn.execute('SELECT 1 FROM payments WHERE invoice_id = ? LIMIT 1',
                                    (invoice_id,)).fetchone()
        if has_payments:
            flash('This invoice has payments — editing is not allowed.', 'error')
            return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))
        settings = _settings(conn)
        clients = conn.execute(
            'SELECT id, client_name, company_name FROM clients WHERE is_deleted = 0 '
            'ORDER BY client_name').fetchall()
        prefill = conn.execute('SELECT * FROM clients WHERE id = ?', (inv['client_id'],)).fetchone()
    return render_template('invoices/form.html', invoice=inv, clients=clients,
                           settings=settings, prefill=prefill,
                           default_month=utils.this_month(),
                           today=date.today().isoformat(),
                           format_pkr=utils.format_pkr)


@bp.route('/invoices/<int:invoice_id>/print')
@login_required
def invoice_print(invoice_id):
    """A4 professional print layout — browser Print / Save as PDF."""
    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ? AND is_deleted = 0',
                           (invoice_id,)).fetchone()
        if not inv:
            flash('Invoice not found.', 'error')
            return redirect(url_for('invoices.invoice_list'))
        client = conn.execute('SELECT * FROM clients WHERE id = ?', (inv['client_id'],)).fetchone()
        settings = _settings(conn)
    return render_template('invoices/print.html', inv=inv, client=client,
                           settings_logo=settings['logo_path'],
                           settings_signature=settings['signature_path'],
                           settings_footer=settings['invoice_footer'],
                           format_pkr=utils.format_pkr, month_label=utils.month_label,
                           amount_in_words=utils.amount_in_words,
                           effective_status=utils.effective_status)


# ==================================================================
# Next month invoice (1-click)
# ==================================================================
@bp.route('/invoices/<int:invoice_id>/next', methods=['POST'])
@login_required
@role_required('admin', 'billing_officer')
def invoice_next_month(invoice_id):
    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ? AND is_deleted = 0',
                           (invoice_id,)).fetchone()
        if not inv:
            flash('Invoice not found.', 'error')
            return redirect(url_for('invoices.invoice_list'))
        next_m = utils.next_month(inv['billing_month'])
        dup = conn.execute(
            'SELECT invoice_number FROM invoices WHERE client_id = ? AND billing_month = ? '
            'AND status != "cancelled" AND is_deleted = 0',
            (inv['client_id'], next_m)).fetchone()
        if dup:
            flash(f'This client already has an invoice for {utils.month_label(next_m)} '
                  f'({dup["invoice_number"]}). A duplicate cannot be created.', 'error')
            return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))

        settings = _settings(conn)
        start_d, end_d = utils.month_range(next_m)
        today = date.today().isoformat()

        conn.execute('BEGIN IMMEDIATE')
        try:
            number, seq = utils.next_invoice_number(conn, settings['invoice_prefix'] or 'CC', next_m[:4])
            cur = conn.execute(
                '''INSERT INTO invoices
                   (invoice_number, invoice_date, billing_month, client_id,
                    service_description, units, per_unit_charges,
                    monthly_service_charges, other_charges, subtotal,
                    gst_percent, gst_amount, total_amount, start_date, end_date,
                    status, notes, company_name, company_address, company_phone,
                    company_email, company_ntn, company_strn, bank_name,
                    account_title, account_number, iban, authorized_signatory,
                    created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (number, today, next_m, inv['client_id'],
                 inv['service_description'], inv['units'], inv['per_unit_charges'],
                 inv['monthly_service_charges'], inv['other_charges'], inv['subtotal'],
                 inv['gst_percent'], inv['gst_amount'], inv['total_amount'],
                 start_d, end_d, 'draft', '',
                 settings['company_name'], settings['address'], settings['phone'],
                 settings['email'], settings['ntn'], settings['strn'],
                 settings['bank_name'], settings['account_title'],
                 settings['account_number'], settings['iban'],
                 settings['authorized_signatory'], _uid()))
            new_id = cur.lastrowid
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('New invoice could not be created (duplicate).', 'error')
            return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))
    audit(session.get('user'), 'invoice_next_month', 'invoice', new_id,
          f'{inv["invoice_number"]} -> {number} ({utils.month_label(next_m)})')
    flash(f'Next month invoice {number} created as draft — review and issue it.', 'success')
    return redirect(url_for('invoices.invoice_edit', invoice_id=new_id))


# ==================================================================
# Cancel / delete
# ==================================================================
@bp.route('/invoices/<int:invoice_id>/cancel', methods=['POST'])
@login_required
@role_required('admin', 'billing_officer')
def invoice_cancel(invoice_id):
    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,)).fetchone()
        if not inv:
            abort(404)
        conn.execute('UPDATE invoices SET status = "cancelled", updated_at = ? WHERE id = ?',
                     (now(), invoice_id))
    audit(session.get('user'), 'invoice_cancel', 'invoice', invoice_id, inv['invoice_number'])
    flash(f'Invoice {inv["invoice_number"]} cancelled.', 'success')
    return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))


@bp.route('/invoices/<int:invoice_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def invoice_delete(invoice_id):
    """Soft delete (admin only)."""
    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,)).fetchone()
        if not inv:
            abort(404)
        conn.execute('UPDATE invoices SET is_deleted = 1, updated_at = ? WHERE id = ?',
                     (now(), invoice_id))
    audit(session.get('user'), 'invoice_delete', 'invoice', invoice_id, inv['invoice_number'])
    flash(f'Invoice {inv["invoice_number"]} deleted.', 'success')
    return redirect(url_for('invoices.invoice_list'))


# ==================================================================
# Payments
# ==================================================================
@bp.route('/invoices/<int:invoice_id>/payment', methods=['POST'])
@login_required
@role_required('admin', 'billing_officer')
def payment_add(invoice_id):
    amount = float(request.form.get('amount') or 0)
    payment_date = (request.form.get('payment_date') or date.today().isoformat()).strip()
    method = request.form.get('method') if request.form.get('method') in ('bank', 'cash') else 'cash'
    reference = (request.form.get('reference_number') or '').strip()
    notes = (request.form.get('notes') or '').strip()

    if amount <= 0:
        flash('Payment amount must be more than zero.', 'error')
        return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))

    with get_db() as conn:
        inv = conn.execute('SELECT * FROM invoices WHERE id = ? AND is_deleted = 0',
                           (invoice_id,)).fetchone()
        if not inv or inv['status'] == 'cancelled':
            flash('Invoice is not valid.', 'error')
            return redirect(url_for('invoices.invoice_list'))
        paid = conn.execute('SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id = ?',
                            (invoice_id,)).fetchone()['s']
        if paid + amount > inv['total_amount'] + 0.01:
            flash(f'Payment cannot be more than the invoice total ({utils.format_pkr(inv["total_amount"])}).',
                  'error')
            return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))
        cur = conn.execute(
            'INSERT INTO payments (invoice_id, payment_date, amount, method, reference_number, notes, created_by) '
            'VALUES (?,?,?,?,?,?,?)',
            (invoice_id, payment_date, amount, method, reference, notes, _uid()))
        new_paid = paid + amount
        new_status = 'paid' if new_paid >= inv['total_amount'] - 0.01 else 'partially_paid'
        conn.execute('UPDATE invoices SET status = ?, updated_at = ? WHERE id = ?',
                     (new_status, now(), invoice_id))
    audit(session.get('user'), 'payment_add', 'invoice', invoice_id,
          f'{inv["invoice_number"]} | {utils.format_pkr(amount)} | {method}')
    flash(f'Payment of {utils.format_pkr(amount)} recorded.', 'success')
    return redirect(url_for('invoices.invoice_view', invoice_id=invoice_id))


@bp.route('/payments')
@login_required
def payment_list():
    q = request.args.get('q', '').strip()
    sql = ('SELECT p.*, i.invoice_number, i.total_amount, c.client_name '
           'FROM payments p JOIN invoices i ON i.id = p.invoice_id '
           'JOIN clients c ON c.id = i.client_id WHERE i.is_deleted = 0')
    args = []
    if q:
        sql += ' AND (i.invoice_number LIKE ? OR c.client_name LIKE ?)'
        like = f'%{q}%'
        args += [like, like]
    with get_db() as conn:
        rows = conn.execute(sql + ' ORDER BY p.id DESC LIMIT 200', args).fetchall()
        total = sum(r['amount'] for r in rows)
    return render_template('invoices/payments.html', payments=rows, q=q, total=total,
                           format_pkr=utils.format_pkr)

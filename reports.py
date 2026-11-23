"""Reports — monthly billing, client-wise, outstanding, GST, invoice register."""
from flask import Blueprint, render_template, request

from decorators import login_required
from db import get_db
import utils

bp = Blueprint('reports', __name__)

REPORT_TYPES = {
    'monthly': 'Monthly Billing Report',
    'client': 'Client-wise Billing Report',
    'outstanding': 'Outstanding Receivables Report',
    'gst': 'GST Report',
    'register': 'Invoice Register',
}


@bp.route('/reports')
@login_required
def reports():
    rtype = request.args.get('type', 'monthly')
    if rtype not in REPORT_TYPES:
        rtype = 'monthly'
    month = request.args.get('month', '').strip()
    client_id = request.args.get('client_id', '').strip()
    status = request.args.get('status', '').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()

    with get_db() as conn:
        clients = conn.execute(
            'SELECT id, client_name FROM clients WHERE is_deleted = 0 ORDER BY client_name').fetchall()

        where = ' WHERE i.is_deleted = 0 AND i.status != "cancelled" AND i.status != "draft"'
        args = []
        if month:
            where += ' AND i.billing_month = ?'
            args.append(month)
        if client_id.isdigit():
            where += ' AND i.client_id = ?'
            args.append(int(client_id))
        if status in ('issued', 'partially_paid', 'paid', 'overdue'):
            where += ' AND i.status = ?'
            args.append(status)
        if date_from:
            where += ' AND i.invoice_date >= ?'
            args.append(date_from)
        if date_to:
            where += ' AND i.invoice_date <= ?'
            args.append(date_to)

        rows, grand_total, grand_gst = [], 0, 0
        title = REPORT_TYPES[rtype]

        if rtype == 'monthly':
            rows = conn.execute(
                f'SELECT billing_month, COUNT(*) AS invoices, '
                f'COALESCE(SUM(total_amount),0) AS total, COALESCE(SUM(gst_amount),0) AS gst '
                f'FROM invoices i{where} GROUP BY billing_month ORDER BY billing_month DESC',
                args).fetchall()
            grand_total = sum(r['total'] for r in rows)
            grand_gst = sum(r['gst'] for r in rows)

        elif rtype == 'client':
            rows = conn.execute(
                f'SELECT c.id AS client_id, c.client_name, COUNT(i.id) AS invoices, '
                f'COALESCE(SUM(i.total_amount),0) AS total, COALESCE(SUM(i.gst_amount),0) AS gst '
                f'FROM invoices i JOIN clients c ON c.id = i.client_id{where} '
                f'GROUP BY c.id, c.client_name ORDER BY total DESC',
                args).fetchall()
            grand_total = sum(r['total'] for r in rows)
            grand_gst = sum(r['gst'] for r in rows)

        elif rtype == 'outstanding':
            rows = conn.execute(
                f'SELECT c.id AS client_id, c.client_name, c.phone, '
                f'COUNT(i.id) AS invoices, COALESCE(SUM(i.total_amount),0) AS billed, '
                f'(SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN invoices iv '
                f'ON p.invoice_id = iv.id WHERE iv.client_id = c.id AND iv.is_deleted = 0) AS paid '
                f'FROM invoices i JOIN clients c ON c.id = i.client_id{where} '
                f'GROUP BY c.id, c.client_name, c.phone HAVING billed > paid ORDER BY billed - paid DESC',
                args).fetchall()
            grand_total = sum(max(r['billed'] - r['paid'], 0) for r in rows)

        elif rtype == 'gst':
            rows = conn.execute(
                f'SELECT billing_month, COUNT(*) AS invoices, COALESCE(SUM(total_amount),0) AS total, '
                f'COALESCE(SUM(gst_amount),0) AS gst FROM invoices i{where} '
                f'GROUP BY billing_month ORDER BY billing_month DESC',
                args).fetchall()
            grand_total = sum(r['total'] for r in rows)
            grand_gst = sum(r['gst'] for r in rows)

        else:  # register
            rows = conn.execute(
                f'SELECT i.invoice_number, i.invoice_date, i.billing_month, i.status, '
                f'i.subtotal, i.gst_amount, i.total_amount, c.client_name '
                f'FROM invoices i JOIN clients c ON c.id = i.client_id{where} '
                f'ORDER BY i.invoice_date DESC, i.id DESC LIMIT 1000',
                args).fetchall()
            grand_total = sum(r['total_amount'] for r in rows)
            grand_gst = sum(r['gst_amount'] for r in rows)

    return render_template('reports/reports.html', rtype=rtype, title=title,
                           rows=rows, clients=clients, month=month, client_id=client_id,
                           status=status, date_from=date_from, date_to=date_to,
                           grand_total=grand_total, grand_gst=grand_gst,
                           format_pkr=utils.format_pkr, month_label=utils.month_label,
                           effective_status=utils.effective_status, REPORT_TYPES=REPORT_TYPES)

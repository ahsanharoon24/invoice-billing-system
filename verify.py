"""Verify.py — ad-hoc end-to-end verification for the billing app.

Runs the full core flow (auth, clients, invoices, calculations, numbering,
duplicate protection, next-month, payments, reports, roles, backup, print)
against a THROWAWAY temporary database — real invoices.db is never touched.

Usage:  venv\\Scripts\\python verify.py
Exit code 0 = all checks passed.
"""
import os
import sys
import tempfile
import traceback

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

# --- point the app at a throwaway DB in the system temp dir ---
import db
fd, tmp_db = tempfile.mkstemp(prefix='hermes-verify-', suffix='.db')
os.close(fd)
os.remove(tmp_db)
db.DB_PATH = tmp_db

import app as appmod

RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond), detail))
    print(('PASS' if cond else 'FAIL'), '|', name, ('| ' + str(detail) if detail else ''))


def main():
    appmod.init_db()
    appmod.seed_admin()
    app = appmod.app
    app.config['TESTING'] = True
    c = app.test_client()

    # --- auth ---
    r = c.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    check('admin login redirects', r.status_code == 302)

    # --- client ---
    r = c.post('/clients/add', data={
        'client_name': 'Demo Client A', 'company_name': 'Demo Society',
        'contact_person': 'Mr. Ahmed', 'phone': '0300-1234567', 'email': 'e@t.com',
        'address': 'Demo Area', 'location': 'Lahore', 'ntn': '123', 'strn': '456',
        'contract_start_date': '2026-01-01', 'contract_end_date': '2026-12-31',
        'monthly_service_charges': '200000', 'default_units': '100',
        'default_per_unit_charges': '500', 'status': 'active'}, follow_redirects=False)
    check('client add redirects to profile', r.status_code == 302 and '/clients/1' in r.headers['Location'])

    # --- invoice (no GST) ---
    r = c.post('/invoices/new', data={
        'client_id': '1', 'billing_month': '2026-08', 'invoice_date': '2026-08-05',
        'service_description': 'Monthly Waste Management Service', 'units': '100',
        'per_unit_charges': '500', 'monthly_service_charges': '200000',
        'other_charges': '0', 'gst_percent': '0', 'status': 'issued'}, follow_redirects=False)
    check('invoice 1 created', r.status_code == 302 and '/invoices/1' in r.headers['Location'])

    import sqlite3
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    inv1 = conn.execute('SELECT * FROM invoices WHERE id=1').fetchone()
    check('invoice number INV-2026-0001', inv1['invoice_number'] == 'INV-2026-0001', inv1['invoice_number'])
    check('calc: 50000 + 200000 = subtotal 250000',
          inv1['subtotal'] == 250000 and inv1['total_amount'] == 250000,
          f"subtotal={inv1['subtotal']} total={inv1['total_amount']}")
    check('company snapshot preserved', inv1['company_name'] == 'Your Company (Pvt.) Ltd.')

    # --- duplicate protection ---
    r = c.post('/invoices/new', data={
        'client_id': '1', 'billing_month': '2026-08', 'invoice_date': '2026-08-05',
        'service_description': 'X', 'units': '1', 'per_unit_charges': '1',
        'monthly_service_charges': '1', 'other_charges': '0', 'gst_percent': '0',
        'status': 'issued'}, follow_redirects=True)
    check('duplicate blocked with message', b'Duplicate invoice blocked' in r.data)
    n = conn.execute('SELECT COUNT(*) c FROM invoices').fetchone()['c']
    check('still exactly 1 invoice', n == 1, f'count={n}')

    # --- next month invoice ---
    r = c.post('/invoices/1/next', follow_redirects=False)
    check('next-month redirects to edit of invoice 2',
          r.status_code == 302 and '/invoices/2/edit' in r.headers['Location'])
    inv2 = conn.execute('SELECT * FROM invoices WHERE id=2').fetchone()
    check('next month = 2026-09', inv2['billing_month'] == '2026-09', inv2['billing_month'])
    check('next invoice number INV-2026-0002', inv2['invoice_number'] == 'INV-2026-0002')
    check('next-month copies rates', inv2['units'] == 100 and inv2['per_unit_charges'] == 500)
    check('next-month is draft', inv2['status'] == 'draft')
    check('old invoice untouched', inv1['status'] == 'issued')

    # --- GST invoice ---
    c.post('/invoices/new', data={
        'client_id': '1', 'billing_month': '2026-10', 'invoice_date': '2026-10-05',
        'service_description': 'GST test', 'units': '100', 'per_unit_charges': '500',
        'monthly_service_charges': '200000', 'other_charges': '5000',
        'gst_percent': '18', 'status': 'issued'}, follow_redirects=False)
    inv3 = conn.execute('SELECT * FROM invoices WHERE id=3').fetchone()
    check('GST calc 255000 -> 45900 -> 300900',
          inv3['subtotal'] == 255000 and inv3['gst_amount'] == 45900 and inv3['total_amount'] == 300900,
          f"sub={inv3['subtotal']} gst={inv3['gst_amount']} tot={inv3['total_amount']}")

    # --- payments ---
    c.post('/invoices/3/payment', data={'amount': '300900', 'payment_date': '2026-08-20',
                                        'method': 'bank', 'reference_number': 'T1', 'notes': ''})
    check('full payment -> paid', conn.execute('SELECT status FROM invoices WHERE id=3').fetchone()['status'] == 'paid')
    c.post('/invoices/1/payment', data={'amount': '100000', 'payment_date': '2026-08-10',
                                        'method': 'cash', 'reference_number': '', 'notes': ''})
    check('partial payment -> partially_paid',
          conn.execute('SELECT status FROM invoices WHERE id=1').fetchone()['status'] == 'partially_paid')
    r = c.post('/invoices/1/payment', data={'amount': '9999999', 'payment_date': '2026-08-10',
                                            'method': 'cash', 'reference_number': '', 'notes': ''},
               follow_redirects=True)
    check('overpayment blocked', b'more than the invoice total' in r.data)

    # --- safe delete (0 invoices wale, admin-only) ---
    r = c.post('/clients/1/delete', follow_redirects=True)
    check('delete blocked for client WITH invoices', b'Cannot delete' in r.data)
    still = conn.execute('SELECT COUNT(*) c FROM clients WHERE id=1 AND is_deleted=0').fetchone()['c']
    check('client with invoices still exists', still == 1, f'count={still}')
    c.post('/clients/add', data={'client_name': 'Temp Client', 'status': 'active'})
    tmp_client_id = conn.execute('SELECT MAX(id) m FROM clients').fetchone()['m']
    r = c.post(f'/clients/{tmp_client_id}/delete', follow_redirects=False)
    check('delete allowed for client with 0 invoices',
          r.status_code == 302 and '/clients' in r.headers['Location'])
    gone = conn.execute('SELECT COUNT(*) c FROM clients WHERE id=?', (tmp_client_id,)).fetchone()['c']
    check('client permanently removed', gone == 0, f'count={gone}')

    # --- pages render ---
    for url in ['/', '/clients', '/clients/1', '/invoices', '/invoices?q=Demo',
                '/invoices/1', '/invoices/1/print', '/payments',
                '/reports?type=monthly', '/reports?type=client', '/reports?type=outstanding',
                '/reports?type=gst', '/reports?type=register']:
        r = c.get(url)
        check(f'page 200: {url}', r.status_code == 200, r.status_code)
    r = c.get('/invoices/1/print')
    check('print has amount in words', b'Rupees Two Lakh Fifty Thousand Only' in r.data)
    check('print has INVOICE header', b'INVOICE' in r.data)

    # --- role-based access ---
    c.post('/users/add', data={'full_name': 'Test Viewer', 'username': 'viewer1',
                               'password': 'viewer123', 'role': 'viewer'})
    vc = app.test_client()
    vc.post('/login', data={'username': 'viewer1', 'password': 'viewer123'})
    check('viewer sees dashboard', vc.get('/').status_code == 200)
    r = vc.get('/settings', follow_redirects=True)
    check('viewer blocked from settings', b'do not have permission' in r.data)
    r = vc.post('/clients/add', data={'client_name': 'HACK', 'status': 'active'}, follow_redirects=True)
    check('viewer blocked from adding client', b'do not have permission' in r.data)

    # --- backup ---
    r = c.post('/backup', data={'action': 'create'}, follow_redirects=True)
    check('backup created', b'Backup created' in r.data)
    backups = [f for f in os.listdir(os.path.join(db.BASE_DIR, 'backups')) if f.endswith('.zip')]
    check('backup file exists on disk', len(backups) >= 1, str(backups[-1:]))

    # --- utils ---
    import utils
    check('words: 250000', utils.amount_in_words(250000) == 'Rupees Two Lakh Fifty Thousand Only')
    check('words: crore', 'Crore' in utils.amount_in_words(10000000))
    check('pkr format lakh grouping', utils.format_pkr(1234567.5) == 'Rs. 12,34,567.50')

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print(f'\n==== {passed} passed, {failed} failed (of {len(RESULTS)}) ====')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        try:
            conn.close()  # release Windows file lock so temp DB can be removed
        except Exception:
            pass
        try:
            os.remove(tmp_db)
        except Exception:
            pass
    sys.exit(code)

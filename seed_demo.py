"""seed_demo.py — Sample 1 ke liye realistic demo data.

Run:  venv\\Scripts\\python seed_demo.py
Sirf pehli dafa chalao (ya jab nayi demo DB chahiye). Real app routes
use hoti hain, is liye invoice numbering / snapshots / calculations
bilkul production jaisi hi hain.

Demo login: admin / admin123
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from app import app, init_db, seed_admin
from db import get_db, now

# ---------------------------------------------------------------
# Demo company details (Settings menu se kabhi bhi badla ja sakta hai)
# ---------------------------------------------------------------
COMPANY = dict(
    company_name='Demo Enterprises (Pvt.) Ltd.',
    address='Office #12, First Floor, Main Boulevard, Gulberg III, Lahore, Pakistan',
    phone='+92 42 3575 0000',
    email='accounts@demoenterprises.pk',
    ntn='1234567-8',
    strn='9876543-2',
    bank_name='Meezan Bank Limited',
    account_title='Demo Enterprises (Pvt.) Ltd.',
    account_number='0101-1234567-89',
    iban='PK36 MEZN 0001 0101 1234 5678',
    gst_percent=16.0,
    invoice_prefix='INV',
    authorized_signatory='Rashid Mehmood',
    invoice_footer='Thank you for your business! Payment is due within 30 days.',
)

# ---------------------------------------------------------------
# Demo clients: (client_name, company, contact, phone, location, ntn,
#               monthly_charges, units, per_unit, status)
# ---------------------------------------------------------------
CLIENTS = [
    ('ABC Traders',        'ABC Traders (Pvt.) Ltd.',    'Ahmed Raza',    '0300-1234567', 'Gulberg III, Lahore',     '1111111-1', 25000, 120, 200, 'active'),
    ('Al-Noor General Store', 'Al-Noor Store',           'Imran Qureshi', '0321-7654321', 'Model Town, Lahore',      '2222222-2', 50000,   0,   0, 'active'),
    ('Crescent Textiles',  'Crescent Textile Mills',     'Khalid Bhatti', '0301-5556667', 'Jaranwala Road, Faisalabad', '3333333-3', 100000, 300, 150, 'active'),
    ('Ravi Builders',      'Ravi Builders & Developers', 'Sohail Khan',   '0333-4445556', 'DHA Phase 5, Lahore',     '4444444-4', 150000,  0,   0, 'active'),
    ('Zainab Boutique',    'Zainab Fashion House',       'Zainab Ali',    '0345-9876543', 'Liberty Market, Lahore',  '5555555-5', 35000,   0,   0, 'active'),
]

# ---------------------------------------------------------------
# Invoice plans: (client_index, month_offset, units, per_unit, monthly,
#                 other, status, payment_amount or None, payment_method)
#   month_offset: 0 = current month, -1 = pichla mahina
# ---------------------------------------------------------------
INVOICES = [
    # Current month — 2 paid, 1 partial, 1 issued, 1 draft
    (0,  0, 120, 200, 25000,    0, 'paid',      None, None),
    (1,  0,   0,   0, 50000,    0, 'paid',      None, None),
    (2,  0, 300, 150, 100000, 5000, 'partial',  150000, 'bank'),
    (3,  0,   0,   0, 150000,   0, 'issued',    None, None),
    (4,  0,   0,   0, 35000,    0, 'draft',     None, None),
    # Pichla mahina — report/dashboard ko purana data bhi chahiye
    (0, -1, 115, 200, 25000,    0, 'paid',      None, None),
    (1, -1,   0,   0, 50000,    0, 'paid',      None, None),
    (2, -1, 285, 150, 100000,   0, 'paid',      None, None),
    (3, -1,   0,   0, 150000,   0, 'issued',    None, None),
    (4, -1,   0,   0, 35000,    0, 'paid',      None, None),
]


def month_shift(offset):
    """Current month (YYYY-MM) plus/minus offset, dynamically."""
    from datetime import datetime
    from calendar import monthrange
    d = datetime.now()
    y, m = d.year, d.month + offset
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return f'{y:04d}-{m:02d}'


def first_of_month(month_str):
    return month_str + '-01'


def last_of_month(month_str):
    from datetime import datetime
    from calendar import monthrange
    y, m = month_str.split('-')
    return f'{y}-{m}-{monthrange(int(y), int(m))[1]}'


def main():
    init_db()
    seed_admin()

    client = app.test_client()

    # Login as admin
    r = client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert r.status_code == 302, 'admin login failed'

    # --- Company settings ---
    with get_db() as conn:
        sets = dict(COMPANY)
        cols = ', '.join(sets.keys())
        ph = ', '.join('?' for _ in sets)
        upd = ', '.join(f'{k} = ?' for k in sets)
        conn.execute(
            f'INSERT INTO company_settings (id, {cols}) VALUES (1, {ph}) '
            f'ON CONFLICT(id) DO UPDATE SET {upd}',
            [sets[k] for k in sets] + [sets[k] for k in sets])
        conn.execute("DELETE FROM invoice_sequences WHERE id = 1")
        conn.execute(
            "INSERT INTO invoice_sequences (id, prefix, year, last_number) "
            "VALUES (1, 'INV', '', 0)")

    # --- Clients ---
    for (name, company, contact, phone, loc, ntn, msc, units, pu, status) in CLIENTS:
        r = client.post('/clients/add', data={
            'client_name': name, 'company_name': company,
            'contact_person': contact, 'phone': phone, 'email': '',
            'location': loc, 'address': f'{loc}, Pakistan',
            'ntn': ntn, 'strn': '',
            'contract_start_date': '2026-01-01', 'contract_end_date': '',
            'monthly_service_charges': str(msc), 'default_units': str(units),
            'default_per_unit_charges': str(pu), 'status': status,
            'bank_details': '', 'notes': '',
        }, follow_redirects=False)
        assert r.status_code == 302, f'client add failed: {name}'

    # --- Invoices + payments ---
    for (ci, moff, units, pu, msc, other, status, pay_amt, pay_method) in INVOICES:
        month = month_shift(moff)
        inv_date = first_of_month(month)
        r = client.post('/invoices/new', data={
            'client_id': str(ci + 1), 'billing_month': month,
            'invoice_date': inv_date,
            'service_description': 'Monthly Service Charges',
            'units': str(units), 'per_unit_charges': str(pu),
            'monthly_service_charges': str(msc), 'other_charges': str(other),
            'gst_percent': str(COMPANY['gst_percent']), 'status': status,
        }, follow_redirects=False)
        assert r.status_code == 302 and '/invoices/' in r.headers.get('Location', ''), \
            f'invoice create failed: client {ci + 1} {month}'

        if pay_amt:
            inv_id = r.headers['Location'].rstrip('/').split('/')[-1]
            pay_date = last_of_month(month)
            r2 = client.post(f'/invoices/{inv_id}/payment', data={
                'amount': str(pay_amt), 'payment_date': pay_date,
                'method': pay_method, 'reference_number': 'DEMO-REF',
                'notes': 'Demo payment',
            }, follow_redirects=False)
            assert r2.status_code in (200, 302), f'payment failed: invoice {inv_id}'

    print('=' * 56)
    print('  Demo data ready!')
    print('  Login: admin / admin123')
    print('  Company: ' + COMPANY['company_name'])
    print('  5 clients, 10 invoices, payments — sab demo data')
    print('  Ab run.bat chala kar browser mein dekho:')
    print('  http://localhost:5000')
    print('=' * 56)


if __name__ == '__main__':
    main()

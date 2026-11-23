"""Business utilities: PKR formatting, amount in words, calculations, invoice numbering."""
import sqlite3
from datetime import datetime, date


# ------------------------------------------------------------------
# PKR number formatting (Pakistani lakh/crore grouping)
# ------------------------------------------------------------------
def format_pkr(amount):
    try:
        amount = round(float(amount or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0
    negative = amount < 0
    amount = abs(amount)
    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))
    if paise == 100:
        rupees += 1
        paise = 0
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ','.join(groups + [tail])
    result = 'Rs. ' + s + (f'.{paise:02d}' if paise else '.00')
    return ('-' + result) if negative else result


# ------------------------------------------------------------------
# Amount in words (PKR)
# ------------------------------------------------------------------
_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
         'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
         'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _two(n):
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + ((' ' + _ONES[n % 10]) if n % 10 else '')


def _three(n):
    h, r = n // 100, n % 100
    parts = []
    if h:
        parts.append(_ONES[h] + ' Hundred')
    if r:
        parts.append(_two(r))
    return ' '.join(parts)


def amount_in_words(amount):
    """e.g. 250000 -> 'Rupees Two Lakh Fifty Thousand Only'"""
    try:
        amount = round(float(amount or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0
    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))
    if paise == 100:
        rupees += 1
        paise = 0
    if rupees == 0 and paise == 0:
        return 'Zero Rupees Only'
    parts = []
    crore = rupees // 10000000
    lakh = (rupees % 10000000) // 100000
    thousand = (rupees % 100000) // 1000
    rest = rupees % 1000
    if crore:
        parts.append(_three(crore) + ' Crore')
    if lakh:
        parts.append(_two(lakh) + ' Lakh')
    if thousand:
        parts.append(_two(thousand) + ' Thousand')
    if rest:
        parts.append(_three(rest))
    words = 'Rupees ' + ' '.join(parts)
    if paise:
        words += ' and ' + _two(paise) + ' Paisa'
    return words + ' Only'


# ------------------------------------------------------------------
# Invoice calculations
# ------------------------------------------------------------------
def calc_invoice(units=0, per_unit=0, monthly=0, other=0, gst_percent=0):
    """Line Amount = Units x Per Unit Rate
       Subtotal    = Monthly Service Charges + Line Amount + Other Charges
       GST Amount  = Subtotal x GST% / 100
       Grand Total = Subtotal + GST Amount"""
    units = float(units or 0)
    per_unit = float(per_unit or 0)
    monthly = float(monthly or 0)
    other = float(other or 0)
    gst_percent = float(gst_percent or 0)
    line_amount = units * per_unit
    subtotal = monthly + line_amount + other
    gst_amount = round(subtotal * gst_percent / 100.0, 2)
    total = round(subtotal + gst_amount, 2)
    return {
        'line_amount': round(line_amount, 2),
        'subtotal': round(subtotal, 2),
        'gst_amount': gst_amount,
        'total_amount': total,
    }


# ------------------------------------------------------------------
# Invoice numbering — transaction-safe sequence (CC-2026-0001)
# ------------------------------------------------------------------
def next_invoice_number(conn, prefix, year):
    """Allocate the next invoice number. Must be called inside the
    same transaction as the invoice INSERT to stay race-free."""
    if not prefix:
        prefix = 'CC'
    row = conn.execute('SELECT prefix, year, last_number FROM invoice_sequences WHERE id = 1').fetchone()
    last = row['last_number'] if row else 0
    if row and row['year'] != year:
        last = 0  # new year restarts at 0001
    n = last + 1
    conn.execute(
        'INSERT INTO invoice_sequences (id, prefix, year, last_number) VALUES (1, ?, ?, ?) '
        'ON CONFLICT(id) DO UPDATE SET prefix = excluded.prefix, year = excluded.year, '
        'last_number = excluded.last_number',
        (prefix, year, n))
    return f'{prefix}-{year}-{n:04d}', n


# ------------------------------------------------------------------
# Date / month helpers
# ------------------------------------------------------------------
def month_label(month_str):
    """'2026-08' -> 'August 2026'"""
    try:
        return datetime.strptime(month_str, '%Y-%m').strftime('%B %Y')
    except (TypeError, ValueError):
        return month_str or ''


def this_month():
    return date.today().strftime('%Y-%m')


def next_month(month_str):
    """'2026-08' -> '2026-09'"""
    try:
        d = datetime.strptime(month_str, '%Y-%m')
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        return f'{y:04d}-{m:02d}'
    except (TypeError, ValueError):
        return this_month()


def month_range(month_str):
    """'2026-08' -> ('2026-08-01', '2026-08-31')"""
    try:
        d = datetime.strptime(month_str, '%Y-%m')
        first = d.strftime('%Y-%m-%d')
        if d.month == 12:
            last = date(d.year + 1, 1, 1)
        else:
            last = date(d.year, d.month + 1, 1)
        from datetime import timedelta
        last = (last - timedelta(days=1)).strftime('%Y-%m-%d')
        return first, last
    except (TypeError, ValueError):
        return '', ''


def effective_status(row):
    """Compute display status: overdue = issued/partially paid & 30+ days old."""
    status = row['status']
    if status in ('issued', 'partially_paid'):
        try:
            inv_date = datetime.strptime(row['invoice_date'], '%Y-%m-%d').date()
            if (date.today() - inv_date).days > 30:
                return 'overdue'
        except (TypeError, ValueError):
            pass
    return status


def payment_totals(conn, invoice_id):
    """(total_paid, remaining) for an invoice."""
    row = conn.execute(
        'SELECT COALESCE(SUM(amount), 0) AS paid FROM payments WHERE invoice_id = ?',
        (invoice_id,)).fetchone()
    return row['paid'], 0

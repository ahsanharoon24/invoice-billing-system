"""dbview.py — database viewer for the billing system.

Usage:
    venv\\Scripts\\python dbview.py            # all tables with counts + recent rows
    venv\\Scripts\\python dbview.py clients    # one table only
    venv\\Scripts\\python dbview.py invoices clients   # multiple tables

Read-only: this script never changes data.
"""
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'invoices.db')

# show only these tables (skip technical ones)
MAIN_TABLES = ['clients', 'invoices', 'payments', 'users', 'company_settings',
               'invoice_sequences', 'audit_log', 'invoice_items']


def fmt_row(row, keys, widths):
    cells = []
    for k in keys:
        v = row[k]
        if v is None:
            v = 'NULL'
        s = str(v)
        cells.append(s[:widths.get(k, 24)])
    return ' | '.join(cells)


def show_table(conn, table, max_rows=15):
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
        count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    except sqlite3.Error as e:
        print(f'  [error] {e}')
        return

    print('=' * 78)
    print(f'TABLE: {table}   (rows: {count})')
    print('=' * 78)
    if count == 0:
        print('  (empty)')
        print()
        return

    # nice display: first 6 columns + summary of the rest
    keys = cols[:6]
    widths = {k: max(len(k), 12) for k in keys}
    print('  ' + ' | '.join(k.ljust(widths[k]) for k in keys))
    print('  ' + '-' * 74)
    for row in conn.execute(f'SELECT * FROM {table} ORDER BY rowid DESC LIMIT {max_rows}'):
        print('  ' + fmt_row(row, keys, widths))
    if count > max_rows:
        print(f'  ... and {count - max_rows} more rows (limit {max_rows} shown)')
    # preview of remaining columns (if many)
    if len(cols) > 6:
        print(f'  [extra columns: {", ".join(cols[6:])}]')
    print()


def main():
    if not os.path.exists(DB_PATH):
        print(f'Database not found: {DB_PATH}')
        print('Run the server once with run.bat to create the database.')
        sys.exit(1)

    tables = [t for t in MAIN_TABLES if os.path.exists(DB_PATH)]
    wanted = sys.argv[1:]
    if wanted:
        tables = [t for t in wanted if t in MAIN_TABLES]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for t in tables:
            show_table(conn, t)
        # quick totals
        print('=' * 78)
        print('QUICK TOTALS')
        print('=' * 78)
        try:
            live_sql = "SELECT COUNT(*) FROM invoices WHERE is_deleted=0 AND status != 'draft' AND status != 'cancelled'"
            billed_sql = "SELECT COALESCE(SUM(total_amount),0) FROM invoices WHERE is_deleted=0 AND status != 'draft' AND status != 'cancelled'"
            n_clients = conn.execute('SELECT COUNT(*) FROM clients WHERE is_deleted=0').fetchone()[0]
            n_invoices = conn.execute('SELECT COUNT(*) FROM invoices WHERE is_deleted=0').fetchone()[0]
            n_live = conn.execute(live_sql).fetchone()[0]
            billed = conn.execute(billed_sql).fetchone()[0]
            paid = conn.execute('SELECT COALESCE(SUM(amount),0) FROM payments').fetchone()[0]
            seq = conn.execute('SELECT prefix, year, last_number FROM invoice_sequences WHERE id=1').fetchone()
            print(f'  Total clients     : {n_clients}')
            print(f'  Total invoices    : {n_invoices}')
            print(f'  Issued+paid total : {n_live}')
            print(f'  Total billed (Rs) : {billed:,.2f}')
            print(f'  Total paid (Rs)   : {paid:,.2f}')
            print(f'  Outstanding (Rs)  : {billed - paid:,.2f}')
            print(f'  Next invoice no   : {seq["prefix"]}-{seq["year"]}-{seq["last_number"] + 1:04d} (next) | current last: {seq["last_number"]}')
        except sqlite3.Error as e:
            print(f'  [error] {e}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()

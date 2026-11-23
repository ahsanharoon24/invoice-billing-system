-- Invoice & Billing Management System — SQLite schema (portfolio demo)
-- SQLite schema (production-ready, build-once design)

PRAGMA foreign_keys = ON;

-- ============================================================
-- USERS (login + roles)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer'
                  CHECK (role IN ('admin', 'billing_officer', 'viewer')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ============================================================
-- COMPANY SETTINGS (single row, id always 1)
-- ============================================================
CREATE TABLE IF NOT EXISTS company_settings (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    company_name          TEXT NOT NULL DEFAULT 'Your Company (Pvt.) Ltd.',
    logo_path             TEXT,
    address               TEXT NOT NULL DEFAULT '',
    phone                 TEXT NOT NULL DEFAULT '',
    email                 TEXT NOT NULL DEFAULT '',
    ntn                   TEXT NOT NULL DEFAULT '',
    strn                  TEXT NOT NULL DEFAULT '',
    bank_name             TEXT NOT NULL DEFAULT '',
    account_title         TEXT NOT NULL DEFAULT '',
    account_number        TEXT NOT NULL DEFAULT '',
    iban                  TEXT NOT NULL DEFAULT '',
    gst_percent           REAL NOT NULL DEFAULT 0,
    invoice_prefix        TEXT NOT NULL DEFAULT 'CC',
    invoice_start_number  INTEGER NOT NULL DEFAULT 1,
    authorized_signatory  TEXT NOT NULL DEFAULT '',
    signature_path        TEXT,
    invoice_footer        TEXT NOT NULL DEFAULT '',
    updated_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ============================================================
-- CLIENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS clients (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name             TEXT NOT NULL,
    company_name            TEXT NOT NULL DEFAULT '',
    contact_person          TEXT NOT NULL DEFAULT '',
    phone                   TEXT NOT NULL DEFAULT '',
    email                   TEXT NOT NULL DEFAULT '',
    address                 TEXT NOT NULL DEFAULT '',
    location                TEXT NOT NULL DEFAULT '',
    ntn                     TEXT NOT NULL DEFAULT '',
    strn                    TEXT NOT NULL DEFAULT '',
    contract_start_date     TEXT,
    contract_end_date       TEXT,
    monthly_service_charges REAL NOT NULL DEFAULT 0,
    default_units           REAL NOT NULL DEFAULT 0,
    default_per_unit_charges REAL NOT NULL DEFAULT 0,
    bank_details            TEXT NOT NULL DEFAULT '',
    notes                   TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'inactive')),
    is_deleted              INTEGER NOT NULL DEFAULT 0,
    created_by              INTEGER REFERENCES users(id),
    created_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_clients_name  ON clients(client_name);
CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);
CREATE INDEX IF NOT EXISTS idx_clients_company ON clients(company_name);

-- ============================================================
-- INVOICES
-- Invoice keeps a SNAPSHOT of company header + bank details so
-- historical invoices never change when settings change.
-- ============================================================
CREATE TABLE IF NOT EXISTS invoices (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number          TEXT NOT NULL UNIQUE,
    invoice_date            TEXT NOT NULL,
    billing_month           TEXT NOT NULL,            -- 'YYYY-MM'
    client_id               INTEGER NOT NULL REFERENCES clients(id),
    service_description     TEXT NOT NULL DEFAULT '',
    units                   REAL NOT NULL DEFAULT 0,
    per_unit_charges        REAL NOT NULL DEFAULT 0,
    monthly_service_charges REAL NOT NULL DEFAULT 0,
    other_charges           REAL NOT NULL DEFAULT 0,
    subtotal                REAL NOT NULL DEFAULT 0,
    gst_percent             REAL NOT NULL DEFAULT 0,
    gst_amount              REAL NOT NULL DEFAULT 0,
    total_amount            REAL NOT NULL DEFAULT 0,
    start_date              TEXT,
    end_date                TEXT,
    status                  TEXT NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'cancelled')),
    notes                   TEXT NOT NULL DEFAULT '',
    -- snapshot of company details at creation time
    company_name            TEXT NOT NULL DEFAULT '',
    company_address         TEXT NOT NULL DEFAULT '',
    company_phone           TEXT NOT NULL DEFAULT '',
    company_email           TEXT NOT NULL DEFAULT '',
    company_ntn             TEXT NOT NULL DEFAULT '',
    company_strn            TEXT NOT NULL DEFAULT '',
    bank_name               TEXT NOT NULL DEFAULT '',
    account_title           TEXT NOT NULL DEFAULT '',
    account_number          TEXT NOT NULL DEFAULT '',
    iban                    TEXT NOT NULL DEFAULT '',
    authorized_signatory    TEXT NOT NULL DEFAULT '',
    created_by              INTEGER REFERENCES users(id),
    created_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    is_deleted              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_invoices_client  ON invoices(client_id);
CREATE INDEX IF NOT EXISTS idx_invoices_month   ON invoices(billing_month);
CREATE INDEX IF NOT EXISTS idx_invoices_date    ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_status  ON invoices(status);
-- Duplicate protection: only ONE live invoice per client per billing month.
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_client_month
    ON invoices(client_id, billing_month)
    WHERE status != 'cancelled' AND is_deleted = 0;

-- ============================================================
-- INVOICE ITEMS (line-level details, optional multi-line support)
-- ============================================================
CREATE TABLE IF NOT EXISTS invoice_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description     TEXT NOT NULL DEFAULT '',
    units           REAL NOT NULL DEFAULT 0,
    per_unit_charges REAL NOT NULL DEFAULT 0,
    amount          REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_invoice ON invoice_items(invoice_id);

-- ============================================================
-- PAYMENTS (multiple payments per invoice allowed)
-- ============================================================
CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id       INTEGER NOT NULL REFERENCES invoices(id),
    payment_date     TEXT NOT NULL,
    amount           REAL NOT NULL CHECK (amount > 0),
    method           TEXT NOT NULL DEFAULT 'cash' CHECK (method IN ('bank', 'cash')),
    reference_number TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    created_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);

-- ============================================================
-- INVOICE NUMBER SEQUENCE (single row, transaction-safe)
-- ============================================================
CREATE TABLE IF NOT EXISTS invoice_sequences (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    prefix      TEXT NOT NULL,
    year        TEXT NOT NULL,
    last_number INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- AUDIT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    username   TEXT NOT NULL DEFAULT '',
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL DEFAULT '',
    entity_id  INTEGER,
    details    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- ============================================================
-- SEED DATA
-- ============================================================
INSERT OR IGNORE INTO company_settings (id, company_name, invoice_prefix, invoice_start_number)
VALUES (1, 'Your Company (Pvt.) Ltd.', 'INV', 1);

INSERT OR IGNORE INTO invoice_sequences (id, prefix, year, last_number)
VALUES (1, 'CC', '', 0);

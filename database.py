#!/usr/bin/env python3
"""
Database module for payment reconciliation system
"""
import sqlite3
from datetime import datetime
from contextlib import contextmanager

class ReconciliationDB:
    def __init__(self, db_path='reconciliation.db'):
        self.db_path = db_path
        self.init_database()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def init_database(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Payment Advices Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payment_advices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id TEXT UNIQUE,
                    email_from TEXT,
                    email_subject TEXT,
                    email_date TIMESTAMP,
                    invoice_number TEXT,
                    invoice_date DATE,
                    payment_date DATE,
                    transaction_date DATE,
                    payment_amount DECIMAL(15,2),
                    net_payment_amount DECIMAL(15,2),
                    bill_amount DECIMAL(15,2),
                    tds_amount DECIMAL(15,2),
                    bank_name TEXT,
                    bank_reference_number TEXT,
                    transaction_reference TEXT,
                    utr_number TEXT,
                    customer_name TEXT,
                    vendor_name TEXT,
                    pdf_filename TEXT,
                    pdf_data BLOB,
                    raw_text TEXT,
                    extracted_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'PENDING'
                )
            ''')

            # Warsoft Invoices Cache Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS warsoft_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id TEXT UNIQUE,
                    invoice_number TEXT UNIQUE,
                    customer_name TEXT,
                    invoice_date DATE,
                    sub_total DECIMAL(15,2),
                    cgst DECIMAL(15,2),
                    sgst DECIMAL(15,2),
                    igst DECIMAL(15,2),
                    total_amount DECIMAL(15,2),
                    balance_amount DECIMAL(15,2),
                    status TEXT,
                    fetched_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    warsoft_raw_json TEXT
                )
            ''')

            # Reconciliation Results Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reconciliation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_advice_id INTEGER,
                    warsoft_invoice_id INTEGER,
                    invoice_number TEXT,
                    match_status TEXT,
                    amount_match BOOLEAN,
                    amount_difference DECIMAL(15,2),
                    date_match BOOLEAN,
                    confidence_score DECIMAL(5,2),
                    discrepancy_notes TEXT,
                    reconciled_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reconciled_by TEXT,
                    FOREIGN KEY (payment_advice_id) REFERENCES payment_advices(id),
                    FOREIGN KEY (warsoft_invoice_id) REFERENCES warsoft_invoices(id)
                )
            ''')

            # Create indexes for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payment_invoice ON payment_advices(invoice_number)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payment_status ON payment_advices(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_warsoft_invoice_num ON warsoft_invoices(invoice_number)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_recon_status ON reconciliation_results(match_status)')

            print("✅ Database initialized successfully")

    def check_payment_advice_exists(self, invoice_number, payment_amount, email_subject):
        """Check if a payment advice already exists to prevent duplicates

        Args:
            invoice_number: Invoice number
            payment_amount: Payment amount
            email_subject: Email subject line

        Returns:
            True if exists, False otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count FROM payment_advices 
                WHERE invoice_number = ? 
                AND ABS(payment_amount - ?) < 1.0
                AND email_subject = ?
            ''', (invoice_number, payment_amount or 0, email_subject))

            result = cursor.fetchone()
            return result['count'] > 0

    def insert_payment_advice(self, payment_data):
        """Insert a new payment advice record (with duplicate check)"""
        # Check for duplicates first
        invoice_num = payment_data.get('invoice_number')
        payment_amt = payment_data.get('payment_amount')
        email_subj = payment_data.get('email_subject')

        if self.check_payment_advice_exists(invoice_num, payment_amt, email_subj):
            print(f"   ⏭️  Skipped duplicate: Invoice {invoice_num} - ₹{payment_amt} (already exists)")
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO payment_advices 
                (email_id, email_from, email_subject, email_date, invoice_number, 
                 invoice_date, payment_date, transaction_date, payment_amount, net_payment_amount, 
                 bill_amount, tds_amount, bank_name, bank_reference_number, transaction_reference, 
                 utr_number, customer_name, vendor_name, pdf_filename, pdf_data, raw_text, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                payment_data.get('email_id'),
                payment_data.get('email_from'),
                payment_data.get('email_subject'),
                payment_data.get('email_date'),
                payment_data.get('invoice_number'),
                payment_data.get('invoice_date'),
                payment_data.get('payment_date'),
                payment_data.get('transaction_date'),
                payment_data.get('payment_amount'),
                payment_data.get('net_payment_amount'),
                payment_data.get('bill_amount'),
                payment_data.get('tds_amount'),
                payment_data.get('bank_name'),
                payment_data.get('bank_reference_number'),
                payment_data.get('transaction_reference'),
                payment_data.get('utr_number'),
                payment_data.get('customer_name'),
                payment_data.get('vendor_name'),
                payment_data.get('pdf_filename'),
                payment_data.get('pdf_data'),
                payment_data.get('raw_text'),
                payment_data.get('status', 'PENDING')
            ))
            return cursor.lastrowid

    def insert_warsoft_invoice(self, invoice_data):
        """Insert or update Warsoft invoice record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO warsoft_invoices 
                (invoice_id, invoice_number, customer_name, invoice_date,
                 sub_total, cgst, sgst, igst, total_amount, balance_amount, status, warsoft_raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                invoice_data.get('invoice_id'),
                invoice_data.get('invoice_number'),
                invoice_data.get('customer_name'),
                invoice_data.get('invoice_date'),
                invoice_data.get('sub_total'),
                invoice_data.get('cgst'),
                invoice_data.get('sgst'),
                invoice_data.get('igst'),
                invoice_data.get('total_amount'),
                invoice_data.get('balance_amount'),
                invoice_data.get('status'),
                invoice_data.get('warsoft_raw_json')
            ))
            return cursor.lastrowid

    def insert_reconciliation_result(self, recon_data):
        """Insert reconciliation result"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO reconciliation_results 
                (payment_advice_id, warsoft_invoice_id, invoice_number, match_status,
                 amount_match, amount_difference, date_match, confidence_score,
                 discrepancy_notes, reconciled_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                recon_data.get('payment_advice_id'),
                recon_data.get('warsoft_invoice_id'),
                recon_data.get('invoice_number'),
                recon_data.get('match_status'),
                recon_data.get('amount_match'),
                recon_data.get('amount_difference'),
                recon_data.get('date_match'),
                recon_data.get('confidence_score'),
                recon_data.get('discrepancy_notes'),
                recon_data.get('reconciled_by', 'SYSTEM')
            ))
            return cursor.lastrowid

    def get_pending_payment_advices(self):
        """Get all pending payment advices"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM payment_advices WHERE status = "PENDING"')
            return cursor.fetchall()

    def get_warsoft_invoice_by_number(self, invoice_number):
        """Get Warsoft invoice by number"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM warsoft_invoices WHERE invoice_number = ?', (invoice_number,))
            return cursor.fetchone()

    def get_all_warsoft_invoices(self):
        """Get all Warsoft invoices (for in-memory caching)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM warsoft_invoices')
            return cursor.fetchall()

    def update_payment_status(self, payment_id, status):
        """Update payment advice status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE payment_advices SET status = ? WHERE id = ?', (status, payment_id))

    def get_reconciliation_summary(self):
        """Get reconciliation summary statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    match_status,
                    COUNT(*) as count,
                    SUM(CASE WHEN amount_match = 0 THEN 1 ELSE 0 END) as amount_mismatches,
                    SUM(ABS(amount_difference)) as total_difference
                FROM reconciliation_results
                GROUP BY match_status
            ''')
            return cursor.fetchall()

    def get_all_reconciliation_results(self, date_filter=None):
        """Get all reconciliation results for reporting

        Args:
            date_filter: Optional date string in 'YYYY-MM-DD' format to filter results by reconciliation date.
                        If None, returns all results.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            base_query = '''
                SELECT 
                    r.id as recon_id,
                    r.invoice_number,
                    r.match_status,
                    r.confidence_score,
                    r.amount_match,
                    r.amount_difference,
                    r.date_match,
                    r.discrepancy_notes,
                    r.reconciled_date,
                    p.email_from,
                    p.email_subject,
                    p.invoice_date as payment_invoice_date,
                    p.payment_date,
                    p.transaction_date,
                    p.payment_amount,
                    p.net_payment_amount,
                    p.bill_amount,
                    p.tds_amount,
                    p.bank_name,
                    p.bank_reference_number,
                    p.utr_number,
                    p.customer_name as payment_customer_name,
                    p.vendor_name,
                    w.customer_name as warsoft_customer_name,
                    w.invoice_date as warsoft_invoice_date,
                    w.total_amount as invoice_amount,
                    w.status as invoice_status
                FROM reconciliation_results r
                LEFT JOIN payment_advices p ON r.payment_advice_id = p.id
                LEFT JOIN warsoft_invoices w ON r.warsoft_invoice_id = w.id
            '''

            if date_filter:
                # Filter by date - only show results from the specified date
                query = base_query + '''
                    WHERE DATE(r.reconciled_date) = ?
                    ORDER BY r.reconciled_date DESC
                '''
                cursor.execute(query, (date_filter,))
            else:
                query = base_query + ' ORDER BY r.reconciled_date DESC'
                cursor.execute(query)

            return cursor.fetchall()

    def clear_reconciliation_results(self):
        """Clear all previous reconciliation results to start fresh"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM reconciliation_results')
            deleted_count = cursor.rowcount
            print(f"🗑️  Cleared {deleted_count} old reconciliation results")
            return deleted_count

    def clear_payment_advices(self):
        """Clear all previous payment advices to start fresh"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM payment_advices')
            deleted_count = cursor.rowcount
            print(f"🗑️  Cleared {deleted_count} old payment advices")
            return deleted_count

    def get_payment_advices_without_invoice_numbers(self, date_filter=None):
        """Get all payment advices where invoice number extraction failed or returned invalid format

        Valid formats are: EXT, HB, HBT with proper structure
        Examples: 23EXT2526/2834, 12HB99/456, 24HBT1234/567

        Args:
            date_filter: Optional date string in 'YYYY-MM-DD' format to filter results by email date.
                        If None, returns all results.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            base_query = '''
                SELECT 
                    id,
                    email_from,
                    email_subject,
                    email_date,
                    payment_date,
                    payment_amount,
                    net_payment_amount,
                    bill_amount,
                    tds_amount,
                    bank_name,
                    utr_number,
                    pdf_filename,
                    invoice_number,
                    status
                FROM payment_advices
                WHERE (
                    -- Completely missing invoice number
                    invoice_number IS NULL 
                    OR invoice_number = '' 
                    OR invoice_number = 'None'

                    -- Invalid/generic patterns that are clearly wrong
                    OR invoice_number IN ('Unknown', 'DOCUMENT', 'Invoice', 'N/A', 'NA', 'NIL')

                    -- Month patterns (clearly not invoice numbers)
                    OR (
                        invoice_number LIKE '%JAN%' 
                        OR invoice_number LIKE '%FEB%'
                        OR invoice_number LIKE '%MAR%'
                        OR invoice_number LIKE '%APR%'
                        OR invoice_number LIKE '%MAY%'
                        OR invoice_number LIKE '%JUN%'
                        OR invoice_number LIKE '%JUL%'
                        OR invoice_number LIKE '%AUG%'
                        OR invoice_number LIKE '%SEP%'
                        OR invoice_number LIKE '%OCT%'
                        OR invoice_number LIKE '%NOV%'
                        OR invoice_number LIKE '%DEC%'
                    )

                    -- Must contain valid pattern markers (EXT, HB, or HBT)
                    -- If it doesn't have these AND has more than 4 chars, it's invalid
                    OR (
                        LENGTH(invoice_number) > 4
                        AND invoice_number NOT LIKE '%EXT%'
                        AND invoice_number NOT LIKE '%HBT%'
                        AND invoice_number NOT LIKE '%HB/%'
                        AND invoice_number NOT LIKE '%HB%'
                    )

                    -- Too short to be valid (less than 5 characters)
                    OR LENGTH(invoice_number) < 5
                )
            '''

            if date_filter:
                # Filter by date - only show payment advices from the specified date
                query = base_query + '''
                    AND DATE(extracted_date) = ?
                    ORDER BY email_date DESC
                '''
                cursor.execute(query, (date_filter,))
            else:
                query = base_query + ' ORDER BY email_date DESC'
                cursor.execute(query)

            return cursor.fetchall()

    def get_payment_advice_by_invoice(self, invoice_number):
        """Get payment advice by invoice number"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM payment_advices WHERE invoice_number = ?', (invoice_number,))
            return cursor.fetchone()

    def get_reconciliation_by_invoice(self, invoice_number):
        """Get reconciliation result by invoice number"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    r.id, 
                    r.invoice_number, 
                    p.payment_amount, 
                    r.match_status, 
                    w.invoice_number as warsoft_invoice_number, 
                    w.total_amount as warsoft_total, 
                    r.amount_difference, 
                    r.discrepancy_notes, 
                    r.reconciled_date as reconciliation_date
                FROM reconciliation_results r
                LEFT JOIN payment_advices p ON r.payment_advice_id = p.id
                LEFT JOIN warsoft_invoices w ON r.warsoft_invoice_id = w.id
                WHERE r.invoice_number = ?
            ''', (invoice_number,))
            return cursor.fetchone()
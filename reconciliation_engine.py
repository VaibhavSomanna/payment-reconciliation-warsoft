#!/usr/bin/env python3
"""
Reconciliation Engine - Match payment advices with Warsoft invoices by invoice number
OPTIMIZED: Uses in-memory cache for fast invoice lookups (no API calls during reconciliation)
"""
from datetime import datetime
from fuzzywuzzy import fuzz
from database import ReconciliationDB
from warsoft_client import WarsoftClient


class ReconciliationEngine:
    def __init__(self, db=None, warsoft=None, auto_write_matched=True):
        self.db = db if db is not None else ReconciliationDB()
        self.warsoft = warsoft if warsoft is not None else WarsoftClient()
        self.auto_write_matched = auto_write_matched
        self.invoice_cache = {}  # In-memory cache for fast lookups

    def load_invoice_cache(self):
        """Load all Warsoft invoices from database into memory cache

        This should be called ONCE after syncing invoices from Warsoft.
        Makes reconciliation 50-100x faster by avoiding database lookups.
        """
        print("📥 Loading invoice cache into memory...")

        # Get all invoices from database using the optimized method
        invoices = self.db.get_all_warsoft_invoices()

        # Build in-memory lookup dictionary
        self.invoice_cache = {}
        for inv in invoices:
            invoice_dict = dict(inv)
            self.invoice_cache[invoice_dict['invoice_number']] = invoice_dict

        print(f"✅ Loaded {len(self.invoice_cache)} invoices into memory cache")
        return len(self.invoice_cache)

    def reconcile_payment(self, payment_advice):
        """Reconcile a single payment advice with Warsoft invoice

        OPTIMIZED: Uses in-memory cache (no DB/API calls per payment)
        """
        invoice_number = payment_advice['invoice_number']

        if not invoice_number:
            return self._create_result(
                payment_advice, None, 'NOT_FOUND',
                'No invoice number found in payment advice', 0
            )

        # Check in-memory cache (ultra-fast - no DB or API call!)
        warsoft_invoice = self.invoice_cache.get(invoice_number)

        if not warsoft_invoice:
            return self._create_result(
                payment_advice, None, 'NOT_FOUND',
                f'Invoice {invoice_number} not found in Warsoft (not in unpaid invoices)', 0
            )

        # Perform matching
        return self._match_payment_with_invoice(payment_advice, warsoft_invoice)

    def _match_payment_with_invoice(self, payment, invoice):
        """Match payment advice with invoice and check for discrepancies"""
        discrepancies = []
        confidence = 100.0

        # Amount matching - use bill_amount (gross invoice amount) to match with Zoho total
        # bill_amount = gross amount before TDS deduction (should match Zoho invoice total)
        # Falls back to payment_amount if bill_amount is not available
        payment_amount = float(payment.get('bill_amount') or payment.get('payment_amount') or 0)
        invoice_amount = float(invoice['total_amount'])
        amount_difference = abs(payment_amount - invoice_amount)
        amount_match = amount_difference <= 10.0  # Allow ₹10 difference for rounding

        if not amount_match:
            discrepancies.append(f"Amount mismatch: Payment ₹{payment_amount}, Invoice ₹{invoice_amount}")
            confidence -= 30

        # Invoice status check (Warsoft statuses: overdue, pending, unpaid, paid)
        invoice_status = invoice['status']
        already_paid = False

        if invoice_status not in ['overdue', 'pending', 'unpaid']:
            if invoice_status == 'paid':
                discrepancies.append(f"Invoice already marked as PAID in Warsoft")
                already_paid = True
                confidence -= 10
            else:
                discrepancies.append(f"Unexpected invoice status: {invoice_status}")
                confidence -= 15

        # Determine match status
        if confidence >= 80:
            match_status = 'MATCHED'
        elif confidence >= 50:
            match_status = 'PARTIAL_MATCH'
        else:
            match_status = 'UNMATCHED'

        # AUTO-WRITE TO WARSOFT: If perfect match and not already paid and feature enabled
        if self.auto_write_matched and match_status == 'MATCHED' and not already_paid and amount_match:
            invoice_number = invoice.get('invoice_number', '')
            
            # PRIORITY 1: Get customer_name and invoice_date from Warsoft invoice (more reliable)
            customer_name = invoice.get('customer_name', '')
            invoice_date = invoice.get('invoice_date', '')
            
            # FALLBACK: If not in Warsoft, try payment advice extraction
            if not customer_name:
                customer_name = payment.get('customer_name', 'Unknown Customer')
            if not invoice_date:
                invoice_date = payment.get('invoice_date', datetime.now().strftime('%Y-%m-%d'))
            
            # Get payment-specific fields (these come from payment advice)
            payment_amount_net = float(payment.get('net_payment_amount') or payment.get('payment_amount') or 0)
            tds_amount = float(payment.get('tds_amount') or 0)
            
            # For total_amount: prefer payment advice bill_amount, fallback to Warsoft total
            total_amount = float(payment.get('bill_amount') or invoice.get('total_amount') or payment_amount_net)
            
            # Payment dates (from payment advice)
            payment_date = payment.get('payment_date') or datetime.now().strftime('%Y-%m-%d')
            transaction_date = payment.get('transaction_date') or payment_date
            
            # Bank reference (from payment advice)
            bank_reference = payment.get('bank_reference_number') or payment.get('utr_number', 'N/A')
            
            # PDF filename (from payment advice)
            pdf_filename = payment.get('pdf_filename', 'payment_advice.pdf')

            print(f"\n   🔍 WARSOFT WRITE - DATA SOURCE:")
            print(f"   - Invoice Number: {invoice_number} (from Warsoft)")
            print(f"   - Customer Name: {customer_name} (from {'Warsoft Invoice' if invoice.get('customer_name') else 'Payment Advice'})")
            print(f"   - Invoice Date: {invoice_date} (from {'Warsoft Invoice' if invoice.get('invoice_date') else 'Payment Advice'})")
            print(f"   - Net Payment Amount: ₹{payment_amount_net} (from Payment Advice)")
            print(f"   - TDS Amount: ₹{tds_amount} (from Payment Advice)")
            print(f"   - Total Amount: ₹{total_amount} (from Payment Advice)")
            print(f"   - Transaction Date: {transaction_date} (from Payment Advice)")
            print(f"   - Bank Reference: {bank_reference} (from Payment Advice)")
            print(f"   - PDF Filename: {pdf_filename} (from Payment Advice)")
            print(f"   - Invoice Status: {invoice_status}\n")

            # Validate critical fields
            if not invoice_number:
                print("   ⚠️  Cannot write to Warsoft: Missing invoice number")
                discrepancies.append("⚠️ Cannot write: Missing invoice number")
            elif not customer_name or customer_name == 'Unknown Customer':
                print("   ⚠️  Warning: Customer name not found in Warsoft or Payment Advice")
                discrepancies.append("⚠️ Warning: Customer name missing")

            # Prepare payment data for Warsoft with ALL required fields
            warsoft_payment_data = {
                "client_name": customer_name,
                "invoice_number": invoice_number,
                "invoice_date": invoice_date,
                "amount": str(payment_amount_net) if payment_amount_net else "0",
                "tds": str(tds_amount) if tds_amount else "0",
                "file_name": pdf_filename,
                "file_location": "https://",  # Default file location
                "bank_reference": bank_reference,
                "total_amount": str(total_amount) if total_amount else "0",
                "transaction_date": transaction_date
            }

            # Write to Warsoft
            success = self.warsoft.write_payment_data(warsoft_payment_data)

            if success:
                discrepancies.append("✅ WRITTEN TO WARSOFT")
            else:
                discrepancies.append("⚠️ Failed to write to Warsoft")

        discrepancy_notes = '; '.join(discrepancies) if discrepancies else 'No discrepancies found'

        return self._create_result(
            payment, invoice, match_status, discrepancy_notes,
            confidence, amount_match, amount_difference
        )

    def _create_result(self, payment, invoice, match_status, notes, confidence,
                       amount_match=False, amount_diff=0):
        """Create reconciliation result object"""
        return {
            'payment_advice_id': payment.get('id'),
            'warsoft_invoice_id': invoice['id'] if invoice else None,
            'invoice_number': payment['invoice_number'],
            'match_status': match_status,
            'amount_match': amount_match,
            'amount_difference': amount_diff,
            'date_match': None,  # Date matching removed - match only on invoice number and amount
            'confidence_score': confidence,
            'discrepancy_notes': notes,
            'reconciled_by': 'SYSTEM'
        }

    def reconcile_all_pending(self):
        """Reconcile all pending payment advices"""
        print("🔄 Starting reconciliation process...")

        pending_payments = self.db.get_pending_payment_advices()
        print(f"📊 Found {len(pending_payments)} pending payment advices")

        results = []
        for payment in pending_payments:
            payment_dict = dict(payment)
            print(f"\n💰 Processing payment for invoice: {payment_dict.get('invoice_number', 'Unknown')}")

            result = self.reconcile_payment(payment_dict)
            result_id = self.db.insert_reconciliation_result(result)

            # Update payment status
            status_map = {
                'MATCHED': 'RECONCILED',
                'PARTIAL_MATCH': 'REVIEW_REQUIRED',
                'NOT_FOUND': 'NOT_FOUND',
                'UNMATCHED': 'UNMATCHED'
            }

            new_status = status_map.get(result['match_status'], 'PENDING')
            self.db.update_payment_status(payment_dict['id'], new_status)

            print(f"   Status: {result['match_status']}")
            print(f"   Confidence: {result['confidence_score']}%")
            print(f"   Notes: {result['discrepancy_notes']}")

            results.append(result)

        print(f"\n✅ Reconciliation complete: {len(results)} payments processed")
        return results

#!/usr/bin/env python3
"""
Reconciliation Engine - Match payment advices with Zoho invoices by invoice number
OPTIMIZED: Uses in-memory cache for fast invoice lookups (no API calls during reconciliation)
"""
from datetime import datetime
from fuzzywuzzy import fuzz
from database import ReconciliationDB
from zoho_client import ZohoClient


class ReconciliationEngine:
    def __init__(self, db=None, zoho=None, auto_mark_paid=True):
        self.db = db if db is not None else ReconciliationDB()
        self.zoho = zoho if zoho is not None else ZohoClient()
        self.auto_mark_paid = auto_mark_paid
        self.invoice_cache = {}  # In-memory cache for fast lookups

    def load_invoice_cache(self):
        """Load all Zoho invoices from database into memory cache

        This should be called ONCE after syncing invoices from Zoho.
        Makes reconciliation 50-100x faster by avoiding database lookups.
        """
        print("📥 Loading invoice cache into memory...")

        # Get all invoices from database using the optimized method
        invoices = self.db.get_all_zoho_invoices()

        # Build in-memory lookup dictionary
        self.invoice_cache = {}
        for inv in invoices:
            invoice_dict = dict(inv)
            self.invoice_cache[invoice_dict['invoice_number']] = invoice_dict

        print(f"✅ Loaded {len(self.invoice_cache)} invoices into memory cache")
        return len(self.invoice_cache)

    def reconcile_payment(self, payment_advice):
        """Reconcile a single payment advice with Zoho invoice

        OPTIMIZED: Uses in-memory cache (no DB/API calls per payment)
        """
        invoice_number = payment_advice['invoice_number']

        if not invoice_number:
            return self._create_result(
                payment_advice, None, 'NOT_FOUND',
                'No invoice number found in payment advice', 0
            )

        # Check in-memory cache (ultra-fast - no DB or API call!)
        zoho_invoice = self.invoice_cache.get(invoice_number)

        if not zoho_invoice:
            return self._create_result(
                payment_advice, None, 'NOT_FOUND',
                f'Invoice {invoice_number} not found in Zoho (not in synced invoices)', 0
            )

        # Perform matching
        return self._match_payment_with_invoice(payment_advice, zoho_invoice)

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

        # Invoice status check
        invoice_status = invoice['status']
        already_paid = False

        if invoice_status not in ['sent', 'overdue', 'partially_paid', 'draft']:
            if invoice_status == 'paid':
                discrepancies.append(f"Invoice already marked as PAID in Zoho")
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

        # AUTO-MARK AS PAID: If perfect match and not already paid and feature enabled
        if self.auto_mark_paid and match_status == 'MATCHED' and not already_paid and amount_match:
            # Try to get invoice_id from different possible field names
            invoice_id = invoice.get('invoice_id') or invoice.get('id')
            invoice_number = invoice.get('invoice_number')
            customer_id = invoice.get('customer_id')
            payment_date = payment.get('payment_date', datetime.now().strftime('%Y-%m-%d'))
            utr_number = payment.get('utr_number', '')

            # Use the invoice's balance amount (what's actually due)
            balance_due = float(invoice.get('balance_amount', payment_amount))

            print(f"\n   🔍 DEBUG INFO:")
            print(f"   - Invoice ID from cache: {invoice_id}")
            print(f"   - Customer ID: {customer_id}")
            print(f"   - Invoice Number: {invoice_number}")
            print(f"   - Payment Advice Amount: ₹{payment_amount}")
            print(f"   - Invoice Balance Due: ₹{balance_due}")
            print(f"   - Payment Date: {payment_date}")
            print(f"   - UTR Number: {utr_number}")
            print(f"   - Invoice Status: {invoice_status}")
            print(f"   - Available invoice keys: {list(invoice.keys())}\n")

            if not invoice_id:
                print(f"   ⚠️ Cannot auto-mark as paid: Missing invoice_id in cached invoice")
                discrepancies.append("⚠️ Cannot auto-mark: Missing invoice ID")
            elif not customer_id:
                print(f"   ⚠️ Cannot auto-mark as paid: Missing customer_id in cached invoice")
                discrepancies.append("⚠️ Cannot auto-mark: Missing customer ID")
            else:
                success = self.zoho.auto_mark_invoice_as_paid(
                    invoice_id=invoice_id,
                    invoice_number=invoice_number,
                    payment_amount=balance_due,
                    payment_date=payment_date,
                    utr_number=utr_number,
                    invoice_status=invoice_status,
                    customer_id=customer_id
                )

                if success:
                    discrepancies.append("✅ AUTO-MARKED AS PAID IN ZOHO")
                else:
                    discrepancies.append("⚠️ Failed to auto-mark as paid in Zoho")

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
            'zoho_invoice_id': invoice['id'] if invoice else None,
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

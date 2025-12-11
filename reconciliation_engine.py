#!/usr/bin/env python3
"""
Reconciliation Engine - Match payment advices with Warsoft invoices by invoice number
OPTIMIZED: Uses in-memory cache for fast invoice lookups (no API calls during reconciliation)
"""
from datetime import datetime
from fuzzywuzzy import fuzz
from database import ReconciliationDB
from warsoft_client import WarsoftClient
from blob_storage_client import BlobStorageClient


class ReconciliationEngine:
    def __init__(self, db=None, warsoft=None, auto_write_matched=True):
        self.db = db if db is not None else ReconciliationDB()
        self.warsoft = warsoft if warsoft is not None else WarsoftClient()
        self.blob_storage = BlobStorageClient()  # Add blob storage client
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

        # Amount matching - use bill_amount (gross invoice amount) to match with Warsoft total
        # bill_amount = gross amount before TDS deduction (should match invoice total)
        # Falls back to net_payment_amount if bill_amount is not available
        payment_amount = float(payment.get('bill_amount') or payment.get('net_payment_amount') or 0)
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
            
            # PRIORITY 1: Get customer_name from Warsoft invoice (more reliable)
            customer_name = invoice.get('customer_name', '')
            if not customer_name:
                customer_name = payment.get('customer_name', 'Unknown Customer')
            
            # SMART DATE LOGIC: Get invoice_date from Warsoft, determine transaction_date intelligently
            warsoft_invoice_date = invoice.get('invoice_date', '')
            
            # Collect all dates from payment advice
            payment_advice_dates = []
            if payment.get('invoice_date'):
                payment_advice_dates.append(payment.get('invoice_date'))
            if payment.get('payment_date'):
                payment_advice_dates.append(payment.get('payment_date'))
            if payment.get('transaction_date'):
                payment_advice_dates.append(payment.get('transaction_date'))
            
            # Remove duplicates
            payment_advice_dates = list(set([d for d in payment_advice_dates if d]))
            
            print(f"\n   📅 SMART DATE MATCHING:")
            print(f"   - Dates from payment advice: {payment_advice_dates}")
            print(f"   - Invoice date from Warsoft: {warsoft_invoice_date}")
            
            # Determine transaction_date: If Warsoft invoice_date matches one payment advice date,
            # the OTHER date is the transaction_date
            transaction_date = None
            invoice_date = warsoft_invoice_date
            
            if warsoft_invoice_date and warsoft_invoice_date in payment_advice_dates:
                # Remove the invoice_date, remaining date is transaction_date
                remaining_dates = [d for d in payment_advice_dates if d != warsoft_invoice_date]
                if remaining_dates:
                    transaction_date = remaining_dates[0]
                    print(f"   ✅ Smart match: Invoice date = {invoice_date}, Transaction date = {transaction_date}")
                else:
                    # Only one date found - use invoice date, set transaction date to today
                    transaction_date = datetime.now().strftime('%Y-%m-%d')
                    print(f"   ⚠️  Only one date found, using invoice={invoice_date}, transaction=today ({transaction_date})")
            else:
                # Fallback: Use dates from payment advice
                if len(payment_advice_dates) >= 2:
                    # Sort dates - earlier is invoice, later is transaction
                    sorted_dates = sorted(payment_advice_dates)
                    invoice_date = sorted_dates[0] if not warsoft_invoice_date else warsoft_invoice_date
                    transaction_date = sorted_dates[1]
                    print(f"   ⚠️  Using payment advice dates: Invoice = {invoice_date}, Transaction = {transaction_date}")
                elif len(payment_advice_dates) == 1:
                    if not warsoft_invoice_date:
                        invoice_date = payment_advice_dates[0]
                    transaction_date = datetime.now().strftime('%Y-%m-%d')
                    print(f"   ⚠️  Only one date in payment advice, using invoice={invoice_date}, transaction=today ({transaction_date})")
                else:
                    # No dates found anywhere
                    if not invoice_date:
                        invoice_date = datetime.now().strftime('%Y-%m-%d')
                    transaction_date = datetime.now().strftime('%Y-%m-%d')
                    print(f"   ⚠️  No dates found, using today for both: {invoice_date}")
            
            # VALIDATION: Ensure transaction_date > invoice_date (transaction always AFTER invoice, never same)
            if transaction_date and invoice_date:
                from datetime import datetime as dt, timedelta
                inv_dt = dt.strptime(invoice_date, '%Y-%m-%d')
                trans_dt = dt.strptime(transaction_date, '%Y-%m-%d')
                
                if trans_dt <= inv_dt:
                    # If transaction is same or before invoice, swap them
                    print(f"   ⚠️  Date issue! Transaction ({transaction_date}) not after Invoice ({invoice_date})")
                    invoice_date, transaction_date = transaction_date, invoice_date
                    # Re-parse dates after swap
                    inv_dt = dt.strptime(invoice_date, '%Y-%m-%d')
                    trans_dt = dt.strptime(transaction_date, '%Y-%m-%d')
                    if trans_dt <= inv_dt:
                        # If still same/before, add 1 day to transaction
                        transaction_date = (inv_dt + timedelta(days=1)).strftime('%Y-%m-%d')
                        print(f"   ✅ Corrected: Invoice date = {invoice_date}, Transaction date = {transaction_date} (+1 day)")
                    else:
                        print(f"   ✅ Swapped: Invoice date = {invoice_date}, Transaction date = {transaction_date}")
            
            # Get payment-specific fields (these come from payment advice)
            payment_amount_net = float(payment.get('net_payment_amount') or payment.get('payment_amount') or 0)
            tds_amount = float(payment.get('tds_amount') or 0)
            
            # For total_amount: prefer payment advice bill_amount, fallback to Warsoft total
            total_amount = float(payment.get('bill_amount') or invoice.get('total_amount') or payment_amount_net)
            
            # Bank reference (from payment advice)
            bank_reference = payment.get('bank_reference_number') or payment.get('utr_number', 'N/A')
            
            # UPLOAD PDF TO BLOB STORAGE
            pdf_data = payment.get('pdf_data')
            pdf_filename = payment.get('pdf_filename', 'payment_advice.pdf')
            
            # DEBUG: Check if pdf_data exists
            print(f"\n   🔍 PDF DATA CHECK:")
            print(f"      pdf_filename: {pdf_filename}")
            print(f"      pdf_data type: {type(pdf_data)}")
            print(f"      pdf_data exists: {pdf_data is not None}")
            if pdf_data:
                print(f"      pdf_data size: {len(pdf_data)} bytes")
                print(f"      pdf_data first 4 bytes: {pdf_data[:4] if len(pdf_data) >= 4 else 'N/A'}")
            else:
                print(f"      ❌ pdf_data is None or empty!")
            
            blob_url = None
            uploaded_filename = None
            file_location = "https://"  # Default fallback
            
            if pdf_data:
                print(f"   📤 Uploading PDF to blob storage...")
                blob_url, uploaded_filename = self.blob_storage.upload_pdf(pdf_data, pdf_filename)
                
                if blob_url:
                    # Update file location and filename for Warsoft API
                    pdf_filename = uploaded_filename
                    file_location = blob_url
                    # Store blob info in payment dict for tracking
                    payment['blob_url'] = blob_url
                    payment['blob_filename'] = uploaded_filename
                    print(f"   ✅ PDF uploaded: {blob_url}")
                else:
                    print(f"   ⚠️  PDF upload failed, using default file location")
            else:
                print(f"   ⚠️  No PDF data available, using default file location")

            print(f"\n   🔍 WARSOFT WRITE - FINAL DATA:")
            print(f"   - Invoice Number: {invoice_number}")
            print(f"   - Customer Name: {customer_name}")
            print(f"   - Invoice Date: {invoice_date}")
            print(f"   - Transaction Date: {transaction_date}")
            print(f"   - Net Payment Amount: ₹{payment_amount_net}")
            print(f"   - TDS Amount: ₹{tds_amount}")
            print(f"   - Total Amount: ₹{total_amount}")
            print(f"   - Bank Reference: {bank_reference}")
            print(f"   - PDF Filename: {pdf_filename}")
            print(f"   - File Location: {file_location}")
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
                "file_location": file_location,  # Blob storage URL
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
            'reconciled_by': 'SYSTEM',
            'pdf_filename': payment.get('blob_filename') or payment.get('pdf_filename'),
            'blob_url': payment.get('blob_url')
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

        # Upload summary
        uploaded_count = sum(1 for r in results if r.get('blob_url'))
        failed_count = len([r for r in results if r.get('match_status') == 'MATCHED']) - uploaded_count
        
        print(f"\n✅ Reconciliation complete: {len(results)} payments processed")
        print(f"\n📊 BLOB UPLOAD SUMMARY:")
        print(f"   ✅ PDFs uploaded to blob storage: {uploaded_count}")
        if failed_count > 0:
            print(f"   ⚠️  Upload failures: {failed_count}")
        
        return results

#!/usr/bin/env python3
"""
Zoho Books API Client for invoice fetching
"""
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


class ZohoClient:
    def __init__(self):
        self.client_id = os.getenv('ZOHO_CLIENT_ID')
        self.client_secret = os.getenv('ZOHO_CLIENT_SECRET')
        self.refresh_token = os.getenv('ZOHO_REFRESH_TOKEN')
        self.organization_id = os.getenv('ZOHO_ORGANIZATION_ID')
        self.access_token = None

        # Support multiple Zoho regions (.com, .in, .eu, .com.au)
        self.api_domain = os.getenv('ZOHO_API_DOMAIN', 'https://www.zohoapis.com')
        self.accounts_domain = os.getenv('ZOHO_ACCOUNTS_DOMAIN', 'https://accounts.zoho.com')
        self.base_url = f'{self.api_domain}/books/v3'

        if not all([self.client_id, self.client_secret, self.refresh_token, self.organization_id]):
            print("❌ Zoho API credentials not configured in .env file")
            print("📋 Please set: ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_ORGANIZATION_ID")
            self.enabled = False
        else:
            self.enabled = True
            print(f"🌍 Using Zoho region: {self.api_domain}")
            self.refresh_access_token()

    def refresh_access_token(self):
        """Refresh Zoho OAuth access token"""
        try:
            url = f'{self.accounts_domain}/oauth/v2/token'
            params = {
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'refresh_token'
            }

            response = requests.post(url, params=params)
            response.raise_for_status()

            data = response.json()
            self.access_token = data.get('access_token')
            print("✅ Zoho access token refreshed")
            return True

        except Exception as e:
            print(f"❌ Failed to refresh Zoho token: {e}")
            self.enabled = False
            return False

    def get_headers(self):
        """Get request headers with access token"""
        return {
            'Authorization': f'Zoho-oauthtoken {self.access_token}',
            'Content-Type': 'application/json'
        }

    def get_invoice_by_number(self, invoice_number):
        """Fetch invoice by invoice number from Zoho (searches all statuses including drafts)"""
        if not self.enabled:
            print("⚠️  Zoho API not enabled - check credentials")
            return None

        # Try searching with all possible statuses since Zoho API filters by default
        statuses_to_try = ['all', 'draft', 'sent', 'paid', 'overdue', 'void', 'unpaid']

        for status in statuses_to_try:
            try:
                url = f'{self.base_url}/invoices'
                params = {
                    'organization_id': self.organization_id,
                    'invoice_number': invoice_number,
                    'status': status
                }

                response = requests.get(url, headers=self.get_headers(), params=params)

                if response.status_code == 401:
                    print("🔄 Token expired, refreshing...")
                    self.refresh_access_token()
                    response = requests.get(url, headers=self.get_headers(), params=params)

                response.raise_for_status()
                data = response.json()

                if data.get('invoices') and len(data['invoices']) > 0:
                    invoice = data['invoices'][0]
                    invoice_status = invoice.get('status', 'unknown')
                    print(f"   ✅ Found invoice {invoice_number} in Zoho (Status: {invoice_status})")
                    return self._parse_invoice(invoice)

            except Exception as e:
                # Continue trying other statuses
                if status == statuses_to_try[-1]:  # Last attempt
                    print(f"   ❌ Error fetching invoice from Zoho: {e}")
                continue

        print(f"   ⚠️  Invoice {invoice_number} not found in any status")
        return None

    def fetch_all_invoices(self, status_filter=None, limit=200):
        """
        Fetch all invoices from Zoho with pagination support

        Args:
            status_filter: Filter by status - 'draft', 'sent', 'paid', 'overdue', 'void', etc.
                          None = fetch all invoices
            limit: Maximum invoices per page (max 200)
        """
        if not self.enabled:
            print("⚠️  Zoho API not enabled")
            return []

        try:
            all_invoices = []
            page = 1
            per_page = min(limit, 200)  # Zoho max is 200 per page

            if status_filter:
                print(f"📥 Fetching invoices with status: {status_filter}")
            else:
                print(f"🔍 Fetching all invoices from Zoho...")

            while True:
                url = f'{self.base_url}/invoices'
                params = {
                    'organization_id': self.organization_id,
                    'per_page': per_page,
                    'page': page
                }

                # Add status filter if specified
                if status_filter:
                    params['status'] = status_filter

                response = requests.get(url, headers=self.get_headers(), params=params)

                if response.status_code == 401:
                    print("🔄 Token expired, refreshing...")
                    self.refresh_access_token()
                    response = requests.get(url, headers=self.get_headers(), params=params)

                response.raise_for_status()
                data = response.json()

                invoices = data.get('invoices', [])
                if not invoices:
                    break  # No more invoices

                parsed_invoices = [self._parse_invoice(inv) for inv in invoices]
                all_invoices.extend(parsed_invoices)

                print(f"   📄 Page {page}: Fetched {len(parsed_invoices)} invoices")

                # Check if there are more pages
                page_context = data.get('page_context', {})
                has_more_page = page_context.get('has_more_page', False)

                if not has_more_page:
                    break

                page += 1

            print(f"✅ Total fetched: {len(all_invoices)} invoices from Zoho")

            return all_invoices

        except Exception as e:
            print(f"❌ Error fetching invoices from Zoho: {e}")
            return []

    def fetch_draft_invoices(self):
        """Fetch only draft invoices from Zoho"""
        return self.fetch_all_invoices(status_filter='draft')

    def fetch_sent_invoices(self):
        """Fetch only sent invoices from Zoho"""
        return self.fetch_all_invoices(status_filter='sent')

    def fetch_unpaid_invoices(self):
        """Fetch unpaid invoices (sent + overdue) from Zoho"""
        sent = self.fetch_all_invoices(status_filter='sent')
        overdue = self.fetch_all_invoices(status_filter='overdue')
        return sent + overdue

    def search_invoices(self, search_term=None, date_from=None, date_to=None):
        """Search invoices with filters"""
        if not self.enabled:
            return []

        try:
            url = f'{self.base_url}/invoices'
            params = {
                'organization_id': self.organization_id
            }

            if search_term:
                params['search_text'] = search_term
            if date_from:
                params['date_start'] = date_from
            if date_to:
                params['date_end'] = date_to

            response = requests.get(url, headers=self.get_headers(), params=params)
            response.raise_for_status()

            data = response.json()
            invoices = data.get('invoices', [])

            return [self._parse_invoice(inv) for inv in invoices]

        except Exception as e:
            print(f"❌ Error searching Zoho invoices: {e}")
            return []

    def get_invoice_details(self, invoice_id):
        """Get detailed invoice information by ID"""
        if not self.enabled:
            return None

        try:
            url = f'{self.base_url}/invoices/{invoice_id}'
            params = {'organization_id': self.organization_id}

            response = requests.get(url, headers=self.get_headers(), params=params)
            response.raise_for_status()

            data = response.json()
            if data.get('invoice'):
                return self._parse_invoice(data['invoice'])

            return None

        except Exception as e:
            print(f"❌ Error fetching invoice details: {e}")
            return None

    def mark_invoice_as_sent(self, invoice_id):
        """Mark a draft invoice as sent"""
        if not self.enabled:
            print("⚠️  Zoho API not enabled")
            return False

        try:
            url = f'{self.base_url}/invoices/{invoice_id}/status/sent'
            params = {'organization_id': self.organization_id}

            response = requests.post(url, headers=self.get_headers(), params=params)

            if response.status_code == 401:
                print("🔄 Token expired, refreshing...")
                self.refresh_access_token()
                response = requests.post(url, headers=self.get_headers(), params=params)

            response.raise_for_status()
            print(f"   ✅ Marked invoice {invoice_id} as SENT")
            return True

        except Exception as e:
            print(f"   ❌ Error marking invoice as sent: {e}")
            return False

    def record_payment(self, invoice_id, payment_data, customer_id):
        """Record payment for an invoice using customerpayments endpoint

        Args:
            invoice_id: Zoho invoice ID
            payment_data: Dict with payment details
                - amount: Payment amount
                - date: Payment date (YYYY-MM-DD)
                - payment_mode: 'cash', 'check', 'bank_transfer', etc.
                - reference_number: UTR/reference number
                - notes: Optional notes
            customer_id: Customer ID from invoice (required)
        """
        if not self.enabled:
            print("⚠️  Zoho API not enabled")
            return False

        try:
            # Use customerpayments endpoint (correct for Zoho Books India API)
            url = f'{self.base_url}/customerpayments'
            params = {'organization_id': self.organization_id}

            # Build payment JSON with invoice application
            payment_json = {
                'customer_id': customer_id,
                'payment_mode': payment_data.get('payment_mode', 'bank_transfer'),
                'amount': payment_data['amount'],
                'date': payment_data['date'],
                'reference_number': payment_data.get('reference_number', ''),
                'notes': payment_data.get('notes', 'Auto-recorded payment'),
                'invoices': [
                    {
                        'invoice_id': invoice_id,
                        'amount_applied': payment_data['amount']
                    }
                ]
            }

            params['JSONString'] = json.dumps(payment_json)

            print(f"   🔍 DEBUG - API URL: {url}")
            print(f"   🔍 DEBUG - Payment JSON: {payment_json}")

            response = requests.post(url, headers=self.get_headers(), params=params)

            if response.status_code == 401:
                print("🔄 Token expired, refreshing...")
                self.refresh_access_token()
                response = requests.post(url, headers=self.get_headers(), params=params)

            print(f"   🔍 DEBUG - Response Status: {response.status_code}")
            print(f"   🔍 DEBUG - Response Body: {response.text[:500]}")

            response.raise_for_status()
            data = response.json()

            if data.get('code') == 0:
                print(f"   ✅ Recorded payment of ₹{payment_data['amount']} for invoice {invoice_id}")
                return True
            else:
                print(f"   ⚠️  Zoho API returned error code: {data.get('code')}")
                print(f"   ⚠️  Error message: {data.get('message', 'Unknown error')}")
                return False

        except requests.exceptions.HTTPError as e:
            print(f"   ❌ HTTP Error recording payment: Status {e.response.status_code}")
            print(f"   ❌ Response: {e.response.text}")
            return False
        except Exception as e:
            print(f"   ❌ Error recording payment: {type(e).__name__}: {e}")
            return False

    def auto_mark_invoice_as_paid(self, invoice_id, invoice_number, payment_amount, payment_date, utr_number,
                                  invoice_status='draft', customer_id=None):
        """Automatically mark a matched invoice as paid in Zoho

        This performs the complete workflow:
        1. If draft/overdue, mark as sent
        2. Record payment using customerpayments endpoint
        3. Invoice automatically becomes 'paid' when full amount is recorded

        Args:
            invoice_id: Zoho invoice ID
            invoice_number: Invoice number for logging
            payment_amount: Payment amount received
            payment_date: Payment date (YYYY-MM-DD format)
            utr_number: UTR/reference number from payment advice
            invoice_status: Current invoice status ('draft', 'sent', etc.)
            customer_id: Customer ID (required for payment recording)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            print("⚠️  Zoho API not enabled - cannot auto-mark as paid")
            return False

        if not customer_id:
            print("   ❌ Missing customer_id - cannot record payment")
            return False

        print(f"\n🚀 AUTO-MARKING INVOICE {invoice_number} AS PAID...")

        # Step 1: If invoice is draft or overdue, mark it as sent first
        if invoice_status in ['draft', 'overdue']:
            print(f"   📤 Step 1: Marking {invoice_status} invoice as SENT...")
            if not self.mark_invoice_as_sent(invoice_id):
                print(f"   ❌ Failed to mark invoice as sent - aborting")
                return False

            # Wait for Zoho to process status change
            import time
            print(f"   ⏳ Waiting 2 seconds for Zoho to process status change...")
            time.sleep(2)
        else:
            print(f"   ✅ Step 1: Invoice already in '{invoice_status}' status, skipping mark-as-sent")

        # Step 2: Record the payment
        print(f"   💰 Step 2: Recording payment of ₹{payment_amount}...")
        payment_data = {
            'amount': payment_amount,
            'date': payment_date,
            'payment_mode': 'bank_transfer',
            'reference_number': utr_number or '',
            'notes': f'Auto-recorded payment from reconciliation system. UTR: {utr_number}'
        }

        if not self.record_payment(invoice_id, payment_data, customer_id):
            print(f"   ❌ Failed to record payment - aborting")
            return False

        print(f"   ✅ Step 3: Invoice will be automatically marked as PAID by Zoho (full payment recorded)")
        print(f"✅ Successfully processed invoice {invoice_number} - marked as PAID")

        return True

    def _parse_invoice(self, invoice_data):
        """Parse Zoho invoice response to standardized format"""
        return {
            'invoice_id': str(invoice_data.get('invoice_id', '')),
            'invoice_number': invoice_data.get('invoice_number'),
            'customer_id': invoice_data.get('customer_id'),
            'customer_name': invoice_data.get('customer_name'),
            'invoice_date': invoice_data.get('date'),
            'due_date': invoice_data.get('due_date'),
            'total_amount': float(invoice_data.get('total', 0)),
            'balance_amount': float(invoice_data.get('balance', 0)),
            'status': invoice_data.get('status'),
            'currency_code': invoice_data.get('currency_code', 'INR'),
            'reference_number': invoice_data.get('reference_number', ''),
            'zoho_raw_json': json.dumps(invoice_data)
        }
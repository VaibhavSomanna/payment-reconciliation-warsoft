#!/usr/bin/env python3
"""
Warsoft API Client for invoice reconciliation
"""
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


class WarsoftClient:
    def __init__(self):
        self.access_token = os.getenv('WARSOFT_ACCESS_TOKEN') or os.getenv('ACCESS_TOKEN')
        self.read_url = os.getenv('WARSOFT_READ_URL', 'https://hbinvoiceapi.staysimplyfied.com/api/ClientInvoice/UnPaidinvoicedata')
        self.write_url = os.getenv('WARSOFT_WRITE_URL', 'https://hbinvoiceapi.staysimplyfied.com/api/ClientInvoice/Push')
        
        if not self.access_token:
            print("❌ Warsoft API access token not configured in .env file")
            print("📋 Please set: WARSOFT_ACCESS_TOKEN or ACCESS_TOKEN")
            self.enabled = False
        else:
            self.enabled = True
            print("✅ Warsoft API client initialized")

    def get_headers(self):
        """Get request headers with access token"""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

    def fetch_unpaid_invoices(self, page_no=1):
        """Fetch unpaid invoices from Warsoft for a specific page
        
        Args:
            page_no: Page number to fetch (starts from 1)
            
        Returns:
            list: List of unpaid invoices, or empty list if error/no data
        """
        if not self.enabled:
            print("⚠️  Warsoft API not enabled - check credentials")
            return []

        try:
            print(f"🔍 Fetching Warsoft unpaid invoices (page {page_no})...")
            
            json_data = {"pageNo": page_no}
            
            print(f"   📤 Request URL: {self.read_url}")
            print(f"   📤 Request Body: {json_data}")
            
            response = requests.post(
                self.read_url,
                headers=self.get_headers(),
                json=json_data,
                timeout=30
            )
            
            print(f"   📥 Response Status: {response.status_code}")
            
            response.raise_for_status()
            
            # Get raw response text first
            response_text = response.text
            print(f"   📥 Response (first 500 chars): {response_text[:500]}")
            
            # Try to parse JSON
            try:
                data = response.json()
            except json.JSONDecodeError as je:
                print(f"   ❌ Failed to parse JSON: {je}")
                print(f"   📄 Full response: {response_text}")
                return []
            
            # Debug: Print response structure
            if isinstance(data, dict):
                print(f"   📋 Response keys: {list(data.keys())}")
            
            # Extract invoices from response
            invoices = []
            
            # Try direct list
            if isinstance(data, list):
                invoices = data
                print(f"   ✅ Response is direct list with {len(invoices)} invoices")
            
            # Try dict with various keys
            elif isinstance(data, dict):
                # Try all possible keys (unpaidInvoices is the correct one for Warsoft API)
                for key in ['unpaidInvoices', 'unmappedInvoices', 'data', 'invoices', 'results', 'items', 'records']:
                    if key in data and isinstance(data[key], list):
                        invoices = data[key]
                        print(f"   ✅ Found invoices in key '{key}': {len(invoices)} invoices")
                        break
                
                # If no list found, check if the dict itself is a single invoice
                if not invoices and 'invoiceNumber' in data:
                    invoices = [data]
                    print(f"   ✅ Response is single invoice object")
            
            if not invoices:
                print(f"   ⚠️  No invoices found in response")
                print(f"   📄 Response structure: {type(data)}")
                if isinstance(data, dict):
                    print(f"   📄 Available keys: {list(data.keys())}")
            
            print(f"   ✅ Fetched {len(invoices)} unpaid invoices from page {page_no}")
            return invoices

        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching Warsoft invoices (page {page_no}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Status code: {e.response.status_code}")
                print(f"   Response: {e.response.text[:1000]}")
            return []
        except Exception as e:
            print(f"❌ Unexpected error: {type(e).__name__}: {e}")
            return []

    def fetch_all_unpaid_invoices(self):
        """Fetch all unpaid invoices from Warsoft across all pages
        
        Supports page range via environment variables:
        - START_PAGE: Starting page number (default: 1)
        - END_PAGE: Ending page number (default: unlimited)
        - MAX_PAGES_TO_FETCH: Max pages from start (legacy support)
        
        Returns:
            list: Combined list of all unpaid invoices
        """
        if not self.enabled:
            return []

        print("\n📥 Fetching all unpaid invoices from Warsoft...")
        
        # Check for page range from environment variables
        start_page = int(os.getenv('START_PAGE', '1'))
        end_page_env = os.getenv('END_PAGE', None)
        max_pages_env = os.getenv('MAX_PAGES_TO_FETCH', None)
        
        if end_page_env:
            end_page = int(end_page_env)
        elif max_pages_env:
            end_page = start_page + int(max_pages_env) - 1
        else:
            end_page = 999999
        
        if start_page > 1 or end_page < 999999:
            pages_count = end_page - start_page + 1
            print(f"   📄 Fetching pages {start_page} to {end_page} ({pages_count} pages)")
        
        all_invoices = []
        page_no = start_page
        has_more_data = True
        
        while has_more_data and page_no <= end_page:
            invoices = self.fetch_unpaid_invoices(page_no)
            
            if invoices and len(invoices) > 0:
                all_invoices.extend(invoices)
                page_no += 1
            else:
                has_more_data = False
        
        pages_fetched = page_no - start_page
        if page_no > end_page:
            print(f"   ⚠️  Reached end page limit ({end_page})")
        
        print(f"✅ Fetched {len(all_invoices)} unpaid invoices from pages {start_page}-{page_no - 1} ({pages_fetched} pages)")
        return all_invoices

    def write_payment_data(self, payment_data):
        """Write/push payment data to Warsoft
        
        Args:
            payment_data: dict with keys:
                - client_name: Customer name
                - invoice_number: Invoice number (e.g., "4EXT2526/450")
                - invoice_date: Invoice date string
                - amount: Payment amount (net amount after TDS)
                - tds: TDS amount
                - file_name: PDF filename
                - file_location: PDF file path/location
                - bank_reference: Bank reference number
                - total_amount: Total invoice amount (before TDS)
                - transaction_date: Transaction date
                
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            print("⚠️  Warsoft API not enabled - cannot write payment data")
            return False

        try:
            invoice_number = payment_data.get('invoice_number', 'Unknown')
            print(f"\n📤 Writing payment data to Warsoft for invoice {invoice_number}...")
            
            # Prepare request payload with all required fields
            payload = {
                "client_name": payment_data.get('client_name', ''),
                "invoice_number": payment_data.get('invoice_number', ''),
                "invoice_date": payment_data.get('invoice_date', ''),
                "amount": str(payment_data.get('amount', '')),
                "tds": str(payment_data.get('tds', '0')),
                "file_name": payment_data.get('file_name', ''),
                "file_location": payment_data.get('file_location', ''),
                "bank_reference": payment_data.get('bank_reference', ''),
                "total_amount": str(payment_data.get('total_amount', '')),
                "transaction_date": payment_data.get('transaction_date', '')
            }
            
            # VALIDATE REQUIRED FIELDS - Warsoft API requires all 10 fields
            required_fields = [
                'client_name', 'invoice_number', 'invoice_date', 'amount', 
                'tds', 'file_name', 'bank_reference', 'total_amount', 'transaction_date'
            ]
            
            missing_fields = []
            empty_fields = []
            
            for field in required_fields:
                if field not in payload:
                    missing_fields.append(field)
                elif not payload[field] or payload[field] == '':
                    empty_fields.append(field)
            
            if missing_fields:
                print(f"   ❌ VALIDATION FAILED: Missing required fields: {', '.join(missing_fields)}")
                return False
            
            if empty_fields:
                # Allow file_location to be empty
                critical_empty = [f for f in empty_fields if f != 'file_location']
                if critical_empty:
                    print(f"   ⚠️  WARNING: Empty required fields: {', '.join(critical_empty)}")
                    print(f"   ❌ VALIDATION FAILED: Critical fields cannot be empty")
                    return False
            
            print(f"   ✅ Validation passed - all required fields present")
            print(f"   📋 Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(
                self.write_url,
                headers=self.get_headers(),
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            print(f"   ✅ Successfully wrote payment data for invoice {invoice_number}")
            print(f"   Response: {response.text[:200]}")
            
            return True

        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error writing payment data to Warsoft: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Status code: {e.response.status_code}")
                print(f"   Response: {e.response.text[:500]}")
            return False

    def parse_invoice(self, invoice_data):
        """Parse Warsoft invoice response to standardized format
        
        
        """
        return {
            'invoice_id': invoice_data.get('invoiceNumber', ''),  # Use invoice number as ID
            'invoice_number': invoice_data.get('invoiceNumber', ''),
            'customer_name': invoice_data.get('cusotmerName', ''),  # Note: typo in API
            'invoice_date': invoice_data.get('invoicedate', ''),
            'sub_total': float(invoice_data.get('subTotal', 0)),
            'cgst': float(invoice_data.get('cgst', 0)),
            'sgst': float(invoice_data.get('sgst', 0)),
            'igst': float(invoice_data.get('igst', 0)),
            'total_amount': float(invoice_data.get('total', 0)),
            'balance_amount': float(invoice_data.get('balance', 0)),
            'status': invoice_data.get('invoiceStatus', ''),
            'warsoft_raw_json': json.dumps(invoice_data)
        }


if __name__ == "__main__":
    # Test Warsoft client
    client = WarsoftClient()
    
    if client.enabled:
        # Test fetching unpaid invoices
        invoices = client.fetch_all_unpaid_invoices()
        print(f"\n📊 Total unpaid invoices: {len(invoices)}")
        
        if invoices:
            print("\n📋 Sample invoice:")
            print(json.dumps(client.parse_invoice(invoices[0]), indent=2))

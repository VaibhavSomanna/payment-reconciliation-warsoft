#!/usr/bin/env python3
"""
Payment Advice Extractor (OpenAI-only)
Uses OpenAI extractor to parse PDF payment advices and produce structured records.
"""
import os
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from dotenv import load_dotenv

from openai_extractor import OpenAIPaymentExtractor

load_dotenv()

# Keywords used to quickly detect payment advice emails
PAYMENT_KEYWORDS = [
    'payment advice', 'payment confirmation', 'payment receipt',
    'fund transfer', 'neft', 'rtgs', 'imps', 'upi',
    'transaction confirmation', 'credit advice', 'debit advice',
    'remittance advice', 'payment processed', 'amount credited',
    'utr', 'transaction reference', 'payment reference'
]


class PaymentAdviceExtractor:
    def __init__(self):
        # Only OpenAI extractor; fail fast if not configured
        self.openai_extractor = OpenAIPaymentExtractor()

    def is_payment_advice_email(self, subject, body):
        """Lightweight heuristic to decide if an email is a payment advice."""
        text = f"{subject} {body}".lower()
        return any(keyword in text for keyword in PAYMENT_KEYWORDS)

    @staticmethod
    def _to_float(value):
        try:
            return float(str(value).replace(',', '').strip())
        except Exception:
            return None

    def extract_payment_data(self, email_message, subject, from_email, body):
        """Extract payment data using OpenAI only. Returns a list of payment dicts."""
        pdf_candidates = []

        if email_message.is_multipart():
            for part in email_message.walk():
                content_disposition = part.get_content_disposition()
                content_type = part.get_content_type()
                filename = part.get_filename()
                
                # Decode filename if it's encoded (e.g., =?utf-8?B?...?=)
                if filename:
                    try:
                        decoded_parts = decode_header(filename)
                        decoded_filename = ""
                        for decoded_part, charset in decoded_parts:
                            if isinstance(decoded_part, bytes):
                                decoded_filename += decoded_part.decode(charset or 'utf-8', errors='ignore')
                            else:
                                decoded_filename += decoded_part
                        filename = decoded_filename
                    except Exception:
                        pass  # Keep original filename if decoding fails
                
                # Debug: show all parts
                print(f"   🔍 Part - Type: {content_type}, Disposition: {content_disposition}, Filename: {filename}")
                
                # Check if it's a PDF attachment (inline or attachment)
                if filename and filename.lower().endswith('.pdf'):
                    data = part.get_payload(decode=True)
                    pdf_candidates.append((filename, content_type, data))
                    print(f"   📎 Found PDF: {filename} ({len(data)} bytes)")
                    continue
                # Also check content type directly for PDFs without explicit filename
                elif content_type == 'application/pdf':
                    data = part.get_payload(decode=True)
                    fname = filename or 'payment_advice.pdf'
                    pdf_candidates.append((fname, content_type, data))
                    print(f"   📎 Found PDF (by content-type): {fname} ({len(data)} bytes)")
                    continue
                # Check for octet-stream with .pdf in name
                elif content_type == 'application/octet-stream' and filename and '.pdf' in filename.lower():
                    data = part.get_payload(decode=True)
                    pdf_candidates.append((filename, content_type, data))
                    print(f"   📎 Found PDF (octet-stream): {filename} ({len(data)} bytes)")
                    continue

        if not pdf_candidates:
            print("⚠️  No PDF attachment found; skipping email")
            return []

        # Pick the largest PDF candidate assuming it is the main advice
        pdf_candidates.sort(key=lambda x: len(x[2]) if x[2] else 0, reverse=True)
        pdf_filename, pdf_content_type, pdf_data = pdf_candidates[0]
        print(f"   📌 Selected PDF for extraction: {pdf_filename} ({len(pdf_data)} bytes, type={pdf_content_type})")

        try:
            openai_result = self.openai_extractor.extract_from_pdf(pdf_data)
        except Exception as e:
            print(f"❌ OpenAI extraction failed: {e}")
            return []

        if not openai_result or not openai_result.get('invoices'):
            print("⚠️  OpenAI returned no invoices; skipping email")
            return []

        invoices = openai_result.get('invoices', []) or []
        common_details = openai_result.get('common_details', {}) or {}

        payment_data_list = []
        for idx, invoice in enumerate(invoices, 1):
            net_payment_amount = self._to_float(invoice.get('net_payment_amount'))
            bill_amount = self._to_float(invoice.get('bill_amount'))
            tds_amount = self._to_float(invoice.get('tds_amount'))

            payment_data_list.append({
                'email_id': f"{email_message.get('Message-ID', '')}_invoice_{idx}",
                'email_from': from_email,
                'email_subject': subject,
                'email_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'invoice_number': invoice.get('invoice_number'),
                'invoice_date': invoice.get('invoice_date'),
                'payment_date': common_details.get('payment_date') or invoice.get('payment_date'),
                'transaction_date': common_details.get('transaction_date'),
                'payment_amount': net_payment_amount,
                'net_payment_amount': net_payment_amount,
                'bill_amount': bill_amount,
                'tds_amount': tds_amount,
                'bank_name': common_details.get('bank_name'),
                'bank_reference_number': common_details.get('bank_reference_number') or common_details.get('utr_number'),
                'transaction_reference': None,
                'utr_number': common_details.get('utr_number') or common_details.get('bank_reference_number'),
                'customer_name': common_details.get('customer_name'),
                'vendor_name': None,
                'pdf_filename': pdf_filename,
                'pdf_data': pdf_data,
                'raw_text': body[:5000],
                'status': 'PENDING'
            })

        return payment_data_list

    def fetch_payment_advices_from_email(self, days_back=7):
        """Fetch payment advice emails and extract using OpenAI."""
        try:
            mail = imaplib.IMAP4_SSL(os.getenv('IMAP_SERVER'), int(os.getenv('IMAP_PORT')))
            mail.login(os.getenv('GMAIL_EMAIL'), os.getenv('GMAIL_PASSWORD'))
            mail.select('inbox')
            print("✅ Connected to Gmail")

            mark_as_read = os.getenv('MARK_PAYMENT_EMAILS_AS_READ', 'true').lower() == 'true'
            since_date = (datetime.now() - timedelta(days=days_back)).strftime('%d-%b-%Y')
            status, messages = mail.search(None, f'SINCE {since_date}')
            email_ids = messages[0].split()[::-1]  # newest first

            max_emails = int(os.getenv('MAX_EMAILS_TO_PROCESS', 100))
            if len(email_ids) > max_emails:
                print(f"⚠️  Found {len(email_ids)} emails, limiting to NEWEST {max_emails}")
                email_ids = email_ids[:max_emails]
            else:
                print(f"📧 Found {len(email_ids)} emails to scan")

            payment_advices = []
            processed_emails = set()

            for email_id in email_ids:
                try:
                    status, msg_data = mail.fetch(email_id, '(BODY.PEEK[])')
                    email_message = email.message_from_bytes(msg_data[0][1])

                    subject = str(email_message.get('Subject', ''))
                    from_email = email_message.get('From', '')
                    message_id = email_message.get('Message-ID', '')

                    if message_id in processed_emails:
                        print(f"   ⏭️  Skipping duplicate email: {subject[:50]}")
                        continue

                    body = ""
                    if email_message.is_multipart():
                        for part in email_message.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                break
                    else:
                        body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

                    if self.is_payment_advice_email(subject, body):
                        print(f"💰 Payment advice found: {subject[:50]}")
                        payment_data_list = self.extract_payment_data(email_message, subject, from_email, body)

                        processed_emails.add(message_id)
                        payment_advices.extend(payment_data_list)

                        if mark_as_read:
                            mail.store(email_id, '+FLAGS', '\\Seen')
                            print(f"   ✅ Marked email as read")
                    else:
                        print(f"   ℹ️  Not a payment advice: {subject[:50]}")

                except Exception as e:
                    print(f"⚠️  Error processing email: {e}")
                    continue

            mail.close()
            mail.logout()

            print(f"✅ Extracted {len(payment_advices)} payment advices")
            return payment_advices

        except Exception as e:
            print(f"❌ Error fetching emails: {e}")
            return []

#!/usr/bin/env python3
"""
Payment Advice Extractor - Extract payment details from bank emails
Uses PDF text extraction (PyPDF2 and pdfplumber)
"""
import re
import os
import imaplib
import email
from datetime import datetime, timedelta
from dotenv import load_dotenv
import PyPDF2
import io

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

load_dotenv()

# Payment advice keywords
PAYMENT_KEYWORDS = [
    'payment advice', 'payment confirmation', 'payment receipt',
    'fund transfer', 'neft', 'rtgs', 'imps', 'upi',
    'transaction confirmation', 'credit advice', 'debit advice',
    'remittance advice', 'payment processed', 'amount credited',
    'utr', 'transaction reference', 'payment reference'
]

# Bank name patterns
BANK_PATTERNS = [
    'hdfc', "icici", 'sbi', 'axis', 'kotak', 'yes bank',
    'indusind', 'bank of baroda', 'pnb', 'canara', 'union bank',
    'bank of india', 'idbi', 'federal bank', 'rbl'
]


class PaymentAdviceExtractor:
    def __init__(self):
        pass

    def is_payment_advice_email(self, subject, body):
        """Check if email is a payment advice"""
        text = f"{subject} {body}".lower()
        return any(keyword in text for keyword in PAYMENT_KEYWORDS)

    def extract_all_invoice_numbers(self, text):
        """Extract ALL invoice numbers from text (for multi-invoice payment advices)"""

        # DEBUG: Show first 500 chars of text being processed
        print(f"\n   🔍 DEBUG: Processing text (first 500 chars):\n{text[:500]}\n")
        print(f"   🔍 DEBUG: Text length: {len(text)} chars\n")

        # Priority patterns for your specific formats (EXT, HB, HBT)
        priority_patterns = [
            # HIGHEST PRIORITY: Complete invoice on SAME line (most common and most accurate)
            # Matches: "11EXT1126/1572" - prevents false matches like "11EXT1126/2100" from split patterns
            r'(\d{2,3}EXT\d{2,5}/\d{2,6})(?!\d)',  # EXT format - same line, not followed by more digits
            r'(\d{2,3}HBT\d{2,4}/\d{2,6})(?!\d)',  # HBT format - same line
            r'(\d{2,3}HB\d{2,4}/\d{2,6})(?!\d)',  # HB format - same line

            # SECOND PRIORITY: SPLIT ACROSS LINES with slash at end + suffix on NEXT line (no content between)
            # Matches: "21EXT1926/\n2657" but NOT "21EXT1926/ 12" (date on same line)
            # Use negative lookahead to ensure no digits immediately after slash on same line
            r'(\d{2,3}EXT\d{2,5})/(?!\d)[\s]*\n[\s]*(\d{2,6})(?!\d)',  # EXT: slash at line end, suffix on next line
            r'(\d{2,3}HBT\d{2,4})/(?!\d)[\s]*\n[\s]*(\d{2,6})(?!\d)',  # HBT: slash at line end, suffix on next line
            r'(\d{2,3}HB\d{2,4})/(?!\d)[\s]*\n[\s]*(\d{2,6})(?!\d)',  # HB: slash at line end, suffix on next line

            # THIRD PRIORITY: RARE - Invoice with slash + ANY content (date, amounts, text) + newline + suffix
            # Handles: "16EXT1326/ 12/09/2025 Ash 43120.00 0.00 43120\n2657" (rare edge case)
            # The .*? matches any content between slash and newline (non-greedy)
            # NOTE: This is LOWER priority to avoid false matches when complete invoice exists
            r'(\d{2,3}EXT\d{2,5})/.*?\n\s*(\d{1,6})(?=\s|,|$)',  # EXT with anything between
            r'(\d{2,3}HBT\d{2,4})/.*?\n\s*(\d{1,6})(?=\s|,|$)',  # HBT with anything between
            r'(\d{2,3}HB\d{2,4})/.*?\n\s*(\d{1,6})(?=\s|,|$)',  # HB with anything between

            # FOURTH PRIORITY: Space/newline separator WITHOUT slash (e.g., "23EXT2526 2834")
            r'(\d{2,3}EXT\d{2,5})[\s\n]+(\d{2,6})(?![/\d])',  # EXT with space/newline, not followed by slash
            r'(\d{2,3}HBT\d{2,4})[\s\n]+(\d{2,6})(?![/\d])',  # HBT with space/newline
            r'(\d{2,3}HB\d{2,4})[\s\n]+(\d{2,6})(?![/\d])',  # HB with space/newline

            # LOWEST PRIORITY: Catch-all patterns (very flexible)
            r'(\d+EXT\d+/\d+)(?!\d)',  # EXT very flexible
            r'(\d+HBT\d+/\d+)(?!\d)',  # HBT flexible
            r'(\d+HB\d+/\d+)(?!\d)',  # HB flexible
        ]

        invoice_numbers = []
        seen = set()  # Avoid duplicates

        # Try priority patterns first (EXT, HBT, HB)
        for idx, pattern in enumerate(priority_patterns, 1):
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)

            for match in matches:
                # Handle tuples from split patterns (e.g., ('21EXT1326', '2611'))
                if isinstance(match, tuple):
                    # Combine with slash: "21EXT1326" + "/" + "2611" = "21EXT1326/2611"
                    normalized = f"{match[0]}/{match[1]}".strip().upper()
                else:
                    # Single string match (already has slash on same line)
                    normalized = match.strip().upper()

                # Validate: must contain EXT/HB/HBT and be reasonable length
                if (normalized not in seen and
                        len(normalized) >= 8 and  # Minimum length for valid invoice
                        any(x in normalized.upper() for x in ['EXT', 'HBT', 'HB'])):
                    invoice_numbers.append(normalized)
                    seen.add(normalized)
                    print(f"   ✅ Found invoice number: {normalized} (pattern #{idx})")

        # If no priority matches, try standard patterns (but AVOID date patterns)
        if not invoice_numbers:
            standard_patterns = [
                # Look for invoice-like patterns, but NOT dates
                r'(?:invoice|inv|bill)\s*(?:no|number|#|ref)?\s*:?\s*([A-Z0-9]{2,3}[A-Z]+\d+[/-]\d+)',
            ]
            for pattern in standard_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    normalized = match.strip().upper()
                    # Validate: contains letters (not just numbers like dates)
                    if (normalized not in seen and
                            len(normalized) >= 8 and
                            any(c.isalpha() for c in normalized) and
                            any(x in normalized for x in ['EXT', 'HBT', 'HB'])):
                        invoice_numbers.append(normalized)
                        seen.add(normalized)
                        print(f"   ✅ Found invoice number: {normalized} (standard pattern)")
                        break  # Only take first standard match

        return invoice_numbers if invoice_numbers else [None]

    def extract_invoice_number(self, text):
        """Extract first invoice number from text (backward compatibility)"""
        all_invoices = self.extract_all_invoice_numbers(text)
        return all_invoices[0] if all_invoices else None

    def extract_payment_amount(self, text):
        """Extract net payment amount from text (Amount column - final payment after TDS)"""
        # Updated patterns to handle amounts with AND without commas
        patterns = [
            # HIGHEST PRIORITY: "Payment amount\n5814.00" format (label and amount on separate lines)
            r'payment\s+amount\s*\n\s*(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)',
            # With labels and currency symbols (flexible)
            r'(?:amount|sum|total|paid|value)\s*:?\s*(?:rs\.?|₹|inr)?\s*(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)',
            # Currency symbol first (with or without commas)
            r'(?:rs\.?|₹|inr)\s*(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)',
            # Currency symbol after (with or without commas)
            r'(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)\s*(?:rs\.?|₹|inr)',
            # Plain numbers with decimal (as fallback, minimum 4 digits to avoid false matches)
            r'\b(\d{4,10}\.\d{2})\b',
            # Plain numbers without decimal (minimum 4 digits)
            r'\b(\d{4,10})\b'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            if matches:
                try:
                    # Remove commas, spaces, and any non-digit characters except decimal point
                    amount_str = matches[0].replace(',', '').replace(' ', '')
                    amount = float(amount_str)

                    # VALIDATION RULES to reject document numbers:
                    # 1. Amount must be >= 100 to avoid false positives
                    if amount < 100:
                        continue

                    # 2. Reject if starts with multiple zeros (document number pattern like 0000767906)
                    if amount_str.startswith('0000') or amount_str.startswith('000'):
                        print(f"   ⚠️  Rejected document number (leading zeros): {amount_str}")
                        continue

                    # 3. Reject if it's a very long integer without decimals (document numbers are usually 8-10+ digits)
                    if '.' not in amount_str and len(amount_str) >= 8:
                        print(f"   ⚠️  Rejected document number (long integer): {amount_str}")
                        continue

                    # 4. Reject unrealistic amounts (> 10 million)
                    if amount > 10000000:
                        print(f"   ⚠️  Rejected unrealistic amount: {amount}")
                        continue

                    return amount
                except:
                    continue

        return None

    def extract_bill_amount(self, text):
        """Extract gross bill/invoice amount (Amt/Bill Amt field - BEFORE TDS deduction)
        This is the amount that should match with Zoho invoice total"""
        patterns = [
            # Bill Amt: 20160.00 format (specific to your payment advice)
            r'(?:bill\s*amt|bill\s*amount|invoice\s*amt|invoice\s*amount)\s*:?\s*(?:rs\.?|₹|inr)?\s*(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)',
            # Amt:20160.00 format - REQUIRE colon to prevent matching "Payment"
            r'\bamt\s*:\s*(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            if matches:
                try:
                    # Remove commas, spaces, and any non-digit characters except decimal point
                    amount_str = matches[0].replace(',', '').replace(' ', '')
                    amount = float(amount_str)
                    # Only accept amounts >= 100 to avoid false positives
                    if amount >= 100:
                        return amount
                except:
                    continue

        return None

    def extract_tds_amount(self, text):
        """Extract TDS amount from text"""
        patterns = [
            # TDS:360.00 format
            r'tds\s*:?\s*(?:rs\.?|₹|inr)?\s*(\d{1,10}(?:[,\s]\d{3})*(?:\.\d{2})?)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
                    # Remove commas, spaces, and any non-digit characters except decimal point
                    amount_str = matches[0].replace(',', '').replace(' ', '')
                    amount = float(amount_str)
                    return amount
                except:
                    continue

        return None

    def extract_utr_number(self, text):
        """Extract UTR/Transaction reference number"""
        patterns = [
            r'utr\s*(?:no|number|#)?\s*:?\s*([A-Z0-9]{10,22})',
            r'transaction\s*(?:ref|reference)?\s*(?:no|number)?\s*:?\s*([A-Z0-9]{10,22})',
            r'ref(?:erence)?\s*(?:no|number)?\s*:?\s*([A-Z0-9]{10,22})',
            r'\b([A-Z]{4}\d{12,16})\b'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0].strip().upper()

        return None

    def extract_payment_date(self, text):
        """Extract payment date from text"""
        patterns = [
            r'(?:date|dated|on)\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    date_str = matches[0]
                    for fmt in ['%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%y', '%d/%m/%y']:
                        try:
                            payment_date = datetime.strptime(date_str, fmt)
                            return payment_date.strftime('%Y-%m-%d')
                        except:
                            continue
                except:
                    continue

        return None

    @staticmethod
    def extract_bank_name(text):
        """Extract bank name from contextual patterns in payment advice"""
        text_lower = text.lower()

        # Pattern 1: "We have credited your Account Number with <BANK> Bank"
        account_credit_pattern = r'credited\s+(?:your\s+)?account\s+(?:number\s+)?(?:[\w\d]+\s+)?with\s+([a-z\s]+bank(?:\s+ltd)?)'
        match = re.search(account_credit_pattern, text_lower, re.IGNORECASE)
        if match:
            bank_name = match.group(1).strip()
            # Extract core bank name (e.g., "hdfc bank ltd" -> "HDFC")
            for bank in BANK_PATTERNS:
                if bank in bank_name.lower():
                    return bank.upper()
            return bank_name.upper()

        # Pattern 2: Bank code in account number (e.g., "HSBCNxxxxxxx", "ICICIxxxxxxx")
        account_number_pattern = r'\b(hdfc|hsbc|icici|sbi|axis|kotak|yes|indusind|citi|bob|pnb|canara|union|boi|idbi|federal|rbl)[a-z]?\d{5,}'
        match = re.search(account_number_pattern, text_lower, re.IGNORECASE)
        if match:
            bank_code = match.group(1).upper()
            # Map common abbreviations to full names
            bank_map = {
                'HSBC': 'HSBC',
                'CITI': 'CITI',
                'BOB': 'BANK OF BARODA',
                'BOI': 'BANK OF INDIA'
            }
            return bank_map.get(bank_code, bank_code)

        # Pattern 3: "BANK NAME: KMAMC-KOTAK-NEFT-RTGS" or similar headers
        bank_name_pattern = r'bank\s+name\s*:\s*([^\n]+)'
        match = re.search(bank_name_pattern, text_lower, re.IGNORECASE)
        if match:
            bank_line = match.group(1).strip()
            # Check if known bank name is in this line
            for bank in BANK_PATTERNS:
                if bank in bank_line.lower():
                    return bank.upper()

        # Pattern 4: Bank code in reference number (e.g., "CITI/25/10/1111", "HDFC/NEFT/2024/xxx")
        reference_pattern = r'\b(hdfc|hsbc|icici|sbi|axis|kotak|yes|indusind|citi|bob|pnb|canara|union|boi|idbi|federal|rbl)[/\-]'
        match = re.search(reference_pattern, text_lower, re.IGNORECASE)
        if match:
            bank_code = match.group(1).upper()
            bank_map = {
                'HSBC': 'HSBC',
                'CITI': 'CITI',
                'BOB': 'BANK OF BARODA',
                'BOI': 'BANK OF INDIA'
            }
            return bank_map.get(bank_code, bank_code)

        # Pattern 5: Email sender domain (e.g., "from: noreply@hdfcbank.com")
        email_pattern = r'from[:\s]+.*?@([a-z]+)bank\.com'
        match = re.search(email_pattern, text_lower, re.IGNORECASE)
        if match:
            bank_domain = match.group(1)
            for bank in BANK_PATTERNS:
                if bank in bank_domain:
                    return bank.upper()

        # Pattern 6: Bank mentioned in PDF header/title with word boundaries
        # (e.g., "HDFC Bank Payment Advice", "ICICI Bank Transaction Confirmation")
        for bank in BANK_PATTERNS:
            # Use word boundary and check for "bank" nearby to avoid false matches
            pattern = r'\b' + re.escape(bank) + r'\s+bank\b'
            if re.search(pattern, text_lower, re.IGNORECASE):
                return bank.upper()

        # Pattern 7: Standalone bank name with strong context indicators (at start of line or after colon)
        for bank in BANK_PATTERNS:
            pattern = r'(?:^|\n|:\s+)' + re.escape(bank) + r'\b'
            if re.search(pattern, text_lower, re.IGNORECASE):
                return bank.upper()

        return None

    def extract_from_pdf_text(self, pdf_data):
        """Extract text from PDF - tries PyPDF2 first, then pdfplumber as fallback"""

        # Method 1: Try PyPDF2 first (fast, works for most simple PDFs)
        try:
            print("   🔍 [Method 1] Attempting PyPDF2 extraction...")

            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))

            # Check if PDF is encrypted
            if pdf_reader.is_encrypted:
                print(f"   🔒 PDF is password-protected, attempting to decrypt...")

                # Get passwords from .env
                password1 = os.getenv('PDF_PASSWORD_1', '')
                password2 = os.getenv('PDF_PASSWORD_2', '')
                passwords = [password1, password2, '']  # Try both passwords + empty string

                decrypted = False
                for pwd in passwords:
                    if pwd:  # Skip empty passwords
                        try:
                            if pdf_reader.decrypt(pwd):
                                print(f"   ✅ PDF decrypted successfully")
                                decrypted = True
                                break
                        except:
                            continue

                if not decrypted:
                    print(f"   ❌ Failed to decrypt PDF with provided passwords, trying fallback...")
                    raise ValueError("Decryption failed")

            # Extract text from all pages
            text = ""
            num_pages = len(pdf_reader.pages)
            print(f"   📄 PDF has {num_pages} pages")

            for i, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                        print(f"   ✅ Extracted {len(page_text)} characters from page {i + 1}")
                except Exception as e:
                    print(f"   ⚠️  Error on page {i + 1}: {str(e)}")

            if text and len(text.strip()) > 50:
                print(f"   ✅ PyPDF2 successfully extracted {len(text)} characters")
                return text
            else:
                print(f"   ⚠️  PyPDF2 extracted insufficient text ({len(text.strip())} chars), trying fallback...")
                raise ValueError("Insufficient text")

        except Exception as e:
            print(f"   ❌ PyPDF2 extraction failed: {str(e)}")

        # Method 2: Fallback to pdfplumber (robust, handles Adobe-specific features)
        if pdfplumber:
            try:
                print("   🔍 [Method 2] Attempting pdfplumber extraction (fallback)...")

                text = ""
                with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
                    num_pages = len(pdf.pages)
                    print(f"   📄 pdfplumber found {num_pages} pages")

                    for i, page in enumerate(pdf.pages):
                        try:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                                print(f"   ✅ pdfplumber extracted {len(page_text)} chars from page {i + 1}")
                        except Exception as e:
                            print(f"   ⚠️  Error on page {i + 1}: {str(e)}")

                if text and len(text.strip()) > 50:
                    print(f"   ✅ pdfplumber successfully extracted {len(text)} characters")
                    return text
                else:
                    print(f"   ⚠️  pdfplumber extracted insufficient text ({len(text.strip())} chars)")

            except Exception as e:
                print(f"   ❌ pdfplumber extraction failed: {str(e)}")
        else:
            print("   ⚠️  pdfplumber not available (not installed)")

        # Both methods failed - return empty string (will trigger AWS Bedrock fallback)
        print("   ❌ Both PyPDF2 and pdfplumber failed, will use AWS Bedrock as last resort")
        return ""

    def extract_from_pdf_with_bedrock(self, pdf_data):
        """Use AWS Bedrock (DeepSeek R1 + Titan) as fallback for PDF extraction"""
        try:
            result = self.bedrock_extractor.extract_payment_advice_from_pdf(pdf_data)
            if result:
                # Format result as text
                formatted = f"""
INVOICE NUMBER: {result.get('invoice_number', 'Not Found')}
PAYMENT AMOUNT: {result.get('payment_amount', 'Not Found')}
PAYMENT DATE: {result.get('payment_date', 'Not Found')}
UTR/REFERENCE: {result.get('utr_number', 'Not Found')}
BANK NAME: {result.get('bank_name', 'Not Found')}
VENDOR/BENEFICIARY: {result.get('vendor_name', 'Not Found')}
                """
                return formatted.strip()
            return None

        except Exception as e:
            print(f"⚠️  AWS Bedrock extraction error: {e}")
            return None

    def extract_invoice_rows_from_text(self, text):
        """Extract multiple invoice rows from payment advice table

        Returns: List of dicts with {invoice_number, net_amount, bill_amount, tds_amount, date}
        """
        invoice_rows = []

        # Get all invoice numbers first
        invoice_numbers = self.extract_all_invoice_numbers(text)

        if not invoice_numbers or invoice_numbers == [None]:
            return []

        print(f"   📋 Extracting data for {len(invoice_numbers)} invoice(s): {invoice_numbers}")

        # Split text into lines for better row-by-row parsing
        lines = text.split('\n')
        used_line_indices = set()  # Track which lines we've already processed

        # For each invoice number, find its row and nearby context (for multi-line table rows)
        for invoice_num in invoice_numbers:
            # Find the line containing this invoice number
            # For normalized invoices like "23EXT1111/2834", search for the suffix part after slash
            if '/' in invoice_num:
                # Split: "23EXT1111/2834" -> base="23EXT1111", suffix="2834"
                base_part, suffix_part = invoice_num.split('/', 1)

                # Search for a line that has BOTH the base part AND the suffix part
                # This handles cases where they might be on the same line or consecutive lines
                invoice_line_idx = None
                for idx, line in enumerate(lines):
                    if idx in used_line_indices:
                        continue  # Skip already processed lines

                    line_upper = line.upper()
                    # Check if this line or next line contains the suffix
                    if base_part.upper() in line_upper:
                        # Check current line and next few lines for the suffix
                        context_window = '\n'.join(lines[idx:min(idx + 3, len(lines))]).upper()
                        if suffix_part in context_window:
                            invoice_line_idx = idx
                            used_line_indices.add(idx)  # Mark this line as used
                            break
            else:
                # No slash - search for exact invoice number
                search_term = invoice_num
                invoice_line_idx = None
                for idx, line in enumerate(lines):
                    if idx in used_line_indices:
                        continue
                    if search_term.upper() in line.upper():
                        invoice_line_idx = idx
                        used_line_indices.add(idx)
                        break

            if invoice_line_idx is None:
                print(f"   ⚠️  Could not find unique line for invoice {invoice_num}")
                continue

            print(
                f"   🔍 Processing invoice {invoice_num} from line {invoice_line_idx}: {lines[invoice_line_idx][:100]}")

            # Get context: current line + next 3 lines (for "Additional info" on next lines)
            context_lines = lines[invoice_line_idx:min(invoice_line_idx + 4, len(lines))]
            context = '\n'.join(context_lines)

            # Also get the specific line with the invoice number (for amount extraction)
            invoice_line = lines[invoice_line_idx]

            # PRIMARY METHOD: Extract amounts using label-based patterns from context
            bill_amount = self.extract_bill_amount(context)
            tds_amount = self.extract_tds_amount(context)
            net_amount = None

            # Look for INR amount on the same line as invoice number
            inr_pattern = r'INR\s+(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)'
            inr_matches = re.findall(inr_pattern, invoice_line, re.IGNORECASE)
            if inr_matches:
                try:
                    # Take the LAST INR amount on the line (usually the net payment amount)
                    net_amount = float(inr_matches[-1].replace(',', ''))
                    # Sanity check: amount should be reasonable (100 to 10 million)
                    if net_amount < 100 or net_amount > 10000000:
                        net_amount = None
                except:
                    pass

            # If not found, look for amount pattern with reasonable limits
            if not net_amount:
                # Pattern for amounts: between 100 and 1,000,000
                amount_pattern = r'\b(\d{3,7}(?:\.\d{1,2})?)\b'
                amount_matches = re.findall(amount_pattern, invoice_line)
                for amt_str in reversed(amount_matches):  # Check from right to left
                    try:
                        amt = float(amt_str)
                        if 100 <= amt <= 10000000:  # Reasonable range
                            net_amount = amt
                            break
                    except:
                        continue

            # FALLBACK METHOD: If label-based extraction didn't work, use simpler decimal extraction
            if not bill_amount or not tds_amount or not net_amount:
                print(f"   ⚠️  Label-based extraction incomplete, trying decimal fallback...")

                # FIXED: Extract all decimal numbers including those with commas
                # Pattern matches: 7,850.00 or 8,801.00 or 951.00 or 157.00 or 8,644.00
                decimal_amounts_pattern = r'(\d{1,3}(?:,\d{3})*\.\d{2})'
                decimal_matches = re.findall(decimal_amounts_pattern, invoice_line)

                # Remove commas and convert to float
                decimal_amounts = []
                for match in decimal_matches:
                    try:
                        clean_amount = float(match.replace(',', ''))
                        # Only keep amounts >= 10 (to filter out tiny numbers like 0.00)
                        if clean_amount >= 10:
                            decimal_amounts.append(clean_amount)
                    except:
                        continue

                print(f"   🔢 Found decimal amounts in line: {decimal_amounts}")

                # For your payment advice format, the columns are:
                # [0]=Amount, [1]=GST Amount, [2]=Invoice Amount, [3]=Other Adjustment, [4]=Mobilization Advance,
                # [5]=Other Advance, [6]=TDS, [7]=Retention, [8]=SDR, [9]=Other Holds, [10]=Total deduction,
                # [11]=Net invoice value, [12]=Current Net Paid

                # We need: Invoice Amount (bill_amount), TDS, Current Net Paid (net_payment_amount)
                if len(decimal_amounts) >= 7:
                    # Extract from specific positions based on your table structure
                    if not bill_amount:
                        bill_amount = decimal_amounts[2]  # Index 2 = Invoice Amount (8,801.00)
                    if not tds_amount:
                        tds_amount = decimal_amounts[6]  # Index 6 = TDS (157.00)
                    if not net_amount:
                        net_amount = decimal_amounts[-1]  # Last value = Current Net Paid (8,644.00)
                    print(
                        f"   💰 Fallback extraction (full table): Bill={bill_amount}, TDS={tds_amount}, Net={net_amount}")

                elif len(decimal_amounts) >= 3:
                    # Partial table - try to identify by position
                    if not bill_amount:
                        bill_amount = decimal_amounts[2] if len(decimal_amounts) > 2 else None
                    if not tds_amount:
                        # TDS is usually a smaller amount in the middle
                        tds_amount = min(decimal_amounts[1:]) if len(decimal_amounts) > 1 else None
                    if not net_amount:
                        net_amount = decimal_amounts[-1]  # Last amount = net paid
                    print(f"   💰 Fallback extraction (partial): Bill={bill_amount}, TDS={tds_amount}, Net={net_amount}")

                elif len(decimal_amounts) == 2:
                    # If we have 2 decimal numbers: likely Bill Amount and Net Amount
                    if not bill_amount:
                        bill_amount = max(decimal_amounts)  # Larger amount = gross bill
                    if not net_amount:
                        net_amount = min(decimal_amounts)  # Smaller amount = net paid
                    if not tds_amount and bill_amount and net_amount:
                        tds_amount = bill_amount - net_amount  # Calculate TDS
                    print(
                        f"   💰 Fallback extraction (2 values): Bill={bill_amount}, Net={net_amount}, TDS={tds_amount}")

                elif len(decimal_amounts) == 1 and not net_amount:
                    # Only one decimal number - assume it's the net payment
                    net_amount = decimal_amounts[0]
                    print(f"   💰 Fallback extraction (1 value): Net={net_amount}")

            payment_date = self.extract_payment_date(context)

            invoice_rows.append({
                'invoice_number': invoice_num,
                'net_payment_amount': net_amount,
                'bill_amount': bill_amount,
                'tds_amount': tds_amount,
                'payment_date': payment_date
            })

        return invoice_rows

    def extract_payment_data(self, email_message, subject, from_email, body):
        """Extract comprehensive payment advice data - PDF text first, then AWS Bedrock (DeepSeek R1 + Titan)"""
        pdf_data = None
        pdf_filename = None
        raw_text = body

        # Extract PDF attachment
        pdf_processed = False  # Flag to ensure we only process ONE PDF
        if email_message.is_multipart():
            for part in email_message.walk():
                # Skip if we've already processed a PDF
                if pdf_processed:
                    continue

                if part.get_content_disposition() == 'attachment':
                    filename = part.get_filename()
                    if filename and filename.lower().endswith('.pdf'):
                        pdf_data = part.get_payload(decode=True)
                        pdf_filename = filename

                        print(f"   📄 Processing PDF attachment: {filename}")

                        # Extract text from PDF using PyPDF2/pdfplumber
                        print(f"   📄 Extracting text from {filename} using PDF reader...")
                        pdf_text = self.extract_from_pdf_text(pdf_data)

                        if pdf_text and len(pdf_text.strip()) > 50:
                            raw_text += "\n" + pdf_text
                            print(f"   ✅ PDF text extracted successfully ({len(pdf_text)} chars)")
                        else:
                            print(
                                f"   ⚠️  PDF text extraction insufficient ({len(pdf_text.strip()) if pdf_text else 0} chars)")

                        pdf_processed = True  # Mark that we've processed a PDF
                        break  # Exit the loop after processing first PDF

        # Extract fields from combined text
        combined_text = f"{subject}\n{raw_text}"

        # Try to extract multiple invoice rows (for multi-invoice payment advices)
        invoice_rows = self.extract_invoice_rows_from_text(combined_text)

        # If multiple invoices found, return list of payment_data dicts
        if len(invoice_rows) > 1:
            print(f"   🔢 Found {len(invoice_rows)} invoices in this payment advice")
            payment_data_list = []

            for idx, row in enumerate(invoice_rows, 1):
                # Use net_payment_amount (Amount column) for matching with Zoho
                amount_for_matching = row['net_payment_amount']

                payment_data = {
                    'email_id': f"{email_message.get('Message-ID', '')}_invoice_{idx}",  # Unique ID per invoice
                    'email_from': from_email,
                    'email_subject': subject,
                    'email_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'invoice_number': row['invoice_number'],
                    'payment_date': row['payment_date'] or self.extract_payment_date(combined_text),
                    'payment_amount': amount_for_matching,
                    'net_payment_amount': row['net_payment_amount'],
                    'bill_amount': row['bill_amount'],
                    'tds_amount': row['tds_amount'],
                    'bank_name': self.extract_bank_name(combined_text),
                    'transaction_reference': None,
                    'utr_number': self.extract_utr_number(combined_text),
                    'vendor_name': None,
                    'pdf_filename': pdf_filename,
                    'pdf_data': pdf_data,
                    'raw_text': raw_text[:5000],
                    'status': 'PENDING'
                }
                payment_data_list.append(payment_data)

            return payment_data_list

        # Single invoice - use original extraction logic
        else:
            # Extract all three amounts: net payment, gross bill amount, and TDS
            net_payment_amount = self.extract_payment_amount(combined_text)  # "Amount" column (net, after TDS)
            bill_amount = self.extract_bill_amount(combined_text)  # "Amt/Bill Amt" field (gross, before TDS)
            tds_amount = self.extract_tds_amount(combined_text)  # TDS deducted

            # Use net_payment_amount (Amount column) for matching with Zoho
            amount_for_matching = net_payment_amount

            payment_data = {
                'email_id': email_message.get('Message-ID', ''),
                'email_from': from_email,
                'email_subject': subject,
                'email_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'invoice_number': self.extract_invoice_number(combined_text),
                'payment_date': self.extract_payment_date(combined_text),
                'payment_amount': amount_for_matching,  # Use net payment amount (Amount column) for Zoho matching
                'net_payment_amount': net_payment_amount,  # Net payment (Amount column - what was actually paid)
                'bill_amount': bill_amount,  # Gross invoice amount (Amt field - before TDS)
                'tds_amount': tds_amount,  # TDS deducted
                'bank_name': self.extract_bank_name(combined_text),
                'transaction_reference': None,
                'utr_number': self.extract_utr_number(combined_text),
                'vendor_name': None,
                'pdf_filename': pdf_filename,
                'pdf_data': pdf_data,
                'raw_text': raw_text[:5000],
                'status': 'PENDING'
            }

            return [payment_data]  # Return as list for consistency

    def fetch_payment_advices_from_email(self, days_back=7):
        """Fetch payment advice emails from mailbox"""
        try:
            mail = imaplib.IMAP4_SSL(os.getenv('IMAP_SERVER'), int(os.getenv('IMAP_PORT')))
            mail.login(os.getenv('GMAIL_EMAIL'), os.getenv('GMAIL_PASSWORD'))
            mail.select('inbox')
            print("✅ Connected to Gmail")

            # Get configuration for marking emails as read
            mark_as_read = os.getenv('MARK_PAYMENT_EMAILS_AS_READ', 'true').lower() == 'true'
            if mark_as_read:
                print("ℹ️  Payment advice emails will be marked as read")
            else:
                print("ℹ️  All emails will remain unread (MARK_PAYMENT_EMAILS_AS_READ=false)")

            since_date = (datetime.now() - timedelta(days=days_back)).strftime('%d-%b-%Y')
            status, messages = mail.search(None, f'SINCE {since_date}')
            email_ids = messages[0].split()

            # Reverse to process NEWEST emails first (instead of oldest)
            email_ids = email_ids[::-1]

            # Apply MAX_EMAILS_TO_PROCESS limit
            max_emails = int(os.getenv('MAX_EMAILS_TO_PROCESS', 100))
            if len(email_ids) > max_emails:
                print(f"⚠️  Found {len(email_ids)} emails, limiting to NEWEST {max_emails} (MAX_EMAILS_TO_PROCESS)")
                email_ids = email_ids[:max_emails]
            else:
                print(f"📧 Found {len(email_ids)} emails to scan")

            payment_advices = []
            processed_emails = set()  # Track processed email IDs to avoid duplicates

            for email_id in email_ids:
                try:
                    # Use BODY.PEEK[] to fetch without marking as read automatically
                    status, msg_data = mail.fetch(email_id, '(BODY.PEEK[])')
                    email_message = email.message_from_bytes(msg_data[0][1])

                    subject = str(email_message.get('Subject', ''))
                    from_email = email_message.get('From', '')
                    message_id = email_message.get('Message-ID', '')

                    # Skip if we've already processed this email (duplicate detection)
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
                        print(f"   📧 Email ID: {message_id}")

                        payment_data_list = self.extract_payment_data(email_message, subject, from_email, body)

                        # Mark this email as processed
                        processed_emails.add(message_id)

                        # extract_payment_data now returns a list
                        if isinstance(payment_data_list, list):
                            print(f"   📦 Extracted {len(payment_data_list)} payment(s) from this email")
                            payment_advices.extend(payment_data_list)  # Add all invoices from this email
                        else:
                            # Backward compatibility (shouldn't happen with new code)
                            payment_advices.append(payment_data_list)

                        # Mark payment advice email as read (if feature enabled)
                        if mark_as_read:
                            mail.store(email_id, '+FLAGS', '\\Seen')
                            print(f"   ✅ Marked email as read")
                        else:
                            print(f"   ℹ️  Keeping email as unread")

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

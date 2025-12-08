#!/usr/bin/env python3
"""
OpenAI GPT-4o mini extractor for payment advice PDFs
Supports password-protected PDFs
"""
import os
import base64
import json
import io
from openai import OpenAI
from dotenv import load_dotenv
import PyPDF2

load_dotenv()


class OpenAIPaymentExtractor:
    def __init__(self):
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in .env file")
        
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
        self.total_cost = 0.0
        
        # GPT-4o mini pricing (per 1M tokens)
        self.input_cost_per_1m = 0.150
        self.output_cost_per_1m = 0.600
        
        # PDF passwords from .env
        self.pdf_passwords = [
            os.getenv('PDF_PASSWORD_1', '253538'),
            os.getenv('PDF_PASSWORD_2', '502000')
        ]
        
        print(f"✅ OpenAI Payment Extractor initialized (model: {self.model})")
    
    def decrypt_pdf(self, pdf_data):
        """Decrypt password-protected PDF
        
        Args:
            pdf_data: Binary PDF data (encrypted)
            
        Returns:
            bytes: Decrypted PDF data or original if not encrypted
        """
        try:
            # Try to read the PDF
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
            
            # Check if encrypted
            if pdf_reader.is_encrypted:
                print(f"   🔒 PDF is password-protected, attempting to decrypt...")
                
                # Try each password
                for password in self.pdf_passwords:
                    try:
                        if pdf_reader.decrypt(password):
                            print(f"   ✅ PDF decrypted successfully with password: {password[:3]}***")
                            
                            # Create a new PDF writer and copy decrypted content
                            pdf_writer = PyPDF2.PdfWriter()
                            for page in pdf_reader.pages:
                                pdf_writer.add_page(page)
                            
                            # Write to bytes
                            decrypted_bytes = io.BytesIO()
                            pdf_writer.write(decrypted_bytes)
                            decrypted_bytes.seek(0)
                            
                            return decrypted_bytes.read()
                    except Exception as e:
                        continue
                
                print(f"   ❌ Could not decrypt PDF with provided passwords")
                return None
            else:
                print(f"   ℹ️  PDF is not encrypted")
                return pdf_data
                
        except Exception as e:
            print(f"   ⚠️  Error checking PDF encryption: {e}")
            # Return original data if we can't check encryption
            return pdf_data
    
    def extract_from_pdf(self, pdf_data):
        """Extract payment advice data using GPT-4o mini with native PDF support
        
        Args:
            pdf_data: Binary PDF data (may be encrypted)
            
        Returns:
            dict: Extracted payment advice data or None if extraction fails
        """
        try:
            print(f"   🤖 Starting OpenAI extraction...")
            
            # Decrypt PDF if needed
            decrypted_pdf = self.decrypt_pdf(pdf_data)
            if decrypted_pdf is None:
                print(f"   ❌ Failed to decrypt PDF")
                return None
            
            # Convert PDF to base64
            pdf_base64 = base64.standard_b64encode(decrypted_pdf).decode('utf-8')
            
            # Detailed extraction prompt
            prompt = """You are a financial document processing AI. Extract ALL payment details from this payment advice PDF.

IMPORTANT: This PDF may contain MULTIPLE invoices. Extract EACH invoice as a separate entry.

Return ONLY a valid JSON object with this structure:

{
  "invoices": [
    {
      "invoice_number": "invoice number (formats: ##EXT####/####, ##HB####/####, ##HBT####/####)",
      "net_payment_amount": "final amount paid after TDS for THIS invoice (number only)",
      "bill_amount": "gross amount before TDS for THIS invoice (number only)",
      "tds_amount": "TDS deducted for THIS invoice (number only)",
      "invoice_date": "YYYY-MM-DD format"
    }
  ],
  "common_details": {
    "transaction_date": "YYYY-MM-DD (date at top of document - payment date)",
    "payment_date": "YYYY-MM-DD format",
    "bank_name": "name of the bank",
    "bank_reference_number": "UTR/reference/transaction ID (alphanumeric, 10-25 chars)",
    "customer_name": "remitter/customer/payer name",
    "utr_number": "UTR number if different from bank_reference_number",
    "total_payment_amount": "total of all invoices combined (if shown)"
  }
}

CRITICAL EXTRACTION RULES:

1. MULTIPLE INVOICES: 
   - If the PDF has a table with multiple invoice rows, extract EACH row as a separate invoice entry
   - Each invoice should have its OWN: invoice_number, net_payment_amount, bill_amount, tds_amount, invoice_date
   - Look for table structures with columns like: Invoice No, Date, Bill Amt, TDS, Amount, etc.

2. Invoice numbers: Look for formats like "23EXT1126/1572", "11HB234/5678", "15HBT567/8901"
   - If invoice split across lines (e.g., "23EXT1126/\\n1572"), combine them as "23EXT1126/1572"
   - Common prefixes: EXT, HB, HBT

3. Amounts (extract as numbers only, no currency symbols, no commas):
   - net_payment_amount: Final payment after TDS (often labeled "Amount", "Net Paid", "Current Net Paid")
   - bill_amount: Gross amount before TDS (often labeled "Bill Amt", "Invoice Amount", "Amt")
   - tds_amount: TDS deducted (labeled "TDS")
   - Example: "8,644.00" should be "8644.00"

4. Dates (convert all to YYYY-MM-DD):
   - transaction_date: Payment/advice date at the TOP of the document
   - invoice_date: Date specific to each invoice (usually in the table row)

5. Bank reference: Look for long alphanumeric codes like:
   - CITIN25657707761, HSBCN52025112997504684, SBIN525331564590
   - Or labeled as "UTR", "Reference Number", "Transaction ID"

6. Customer name: Look for "Remitter Name", "From", "Sender", "Payer", "Customer Name"

Be thorough - extract EVERY invoice in the document as a separate entry in the invoices array."""

            # Call OpenAI API with native PDF support
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "file",
                                "file": {
                                    "filename": "payment_advice.pdf",
                                    "file_data": f"data:application/pdf;base64,{pdf_base64}"
                                }
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=2000,
                temperature=0
            )
            
            # Extract result
            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            
            # Track usage and cost
            usage = response.usage
            input_cost = (usage.prompt_tokens / 1_000_000) * self.input_cost_per_1m
            output_cost = (usage.completion_tokens / 1_000_000) * self.output_cost_per_1m
            total_cost = input_cost + output_cost
            
            self.total_cost += total_cost
            
            print(f"   ✅ OpenAI extraction successful!")
            print(f"   📊 Tokens: {usage.prompt_tokens} input + {usage.completion_tokens} output")
            print(f"   💵 Cost: ${total_cost:.4f} (Total session: ${self.total_cost:.4f})")
            
            # Display extracted data
            invoices = result.get('invoices', [])
            common = result.get('common_details', {})
            
            print(f"   📄 Found {len(invoices)} invoice(s):")
            for i, inv in enumerate(invoices, 1):
                print(f"      Invoice {i}: {inv.get('invoice_number')} | Net: {inv.get('net_payment_amount')} | Bill: {inv.get('bill_amount')} | TDS: {inv.get('tds_amount')} | Date: {inv.get('invoice_date')}")
            
            print(f"   📋 Common details:")
            print(f"      - Transaction Date: {common.get('transaction_date')}")
            print(f"      - Bank Ref: {common.get('bank_reference_number')}")
            print(f"      - Customer: {common.get('customer_name')}")
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"   ❌ OpenAI returned invalid JSON: {e}")
            print(f"   📄 Raw response: {result_text[:500]}")
            return None
            
        except Exception as e:
            print(f"   ❌ OpenAI extraction error: {e}")
            return None
    
    def get_total_cost(self):
        """Get total cost of all extractions in this session"""
        return self.total_cost


# Test function
def test_openai_extractor(pdf_path):
    """Test the OpenAI extractor with a sample PDF"""
    print(f"\n{'='*60}")
    print(f"Testing OpenAI Payment Extractor")
    print(f"{'='*60}\n")
    
    try:
        # Load PDF
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
        
        print(f"📄 Loaded PDF: {pdf_path} ({len(pdf_data)} bytes)")
        
        # Initialize extractor
        extractor = OpenAIPaymentExtractor()
        
        # Extract data
        result = extractor.extract_from_pdf(pdf_data)
        
        if result:
            print(f"\n{'='*60}")
            print(f"EXTRACTION RESULTS:")
            print(f"{'='*60}")
            print(json.dumps(result, indent=2))
            print(f"\n💰 Total session cost: ${extractor.get_total_cost():.4f}")
        else:
            print(f"\n❌ Extraction failed")
            
    except FileNotFoundError:
        print(f"❌ PDF file not found: {pdf_path}")
    except Exception as e:
        print(f"❌ Test error: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        test_openai_extractor(pdf_path)
    else:
        print("\n" + "="*60)
        print("OpenAI Payment Advice Extractor - Test Mode")
        print("="*60)
        pdf_path = input("\n📄 Enter the path to your payment advice PDF: ").strip().strip('"')
        
        if pdf_path:
            test_openai_extractor(pdf_path)
        else:
            print("❌ No path provided. Exiting.")
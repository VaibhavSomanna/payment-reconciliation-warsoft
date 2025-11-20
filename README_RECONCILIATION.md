# Payment Reconciliation System

## Overview
Automated system to match payment advices from bank emails with invoices stored in Gmail drafts (or Zoho Books API), then categorize results as **MATCHED**, **UNMATCHED**, or **NOT FOUND**.

## Key Changes from Original System

### ✅ What Changed:
1. **PDF Extraction Order**: Now uses PyPDF2 text extraction FIRST, OpenAI Vision as fallback only
2. **Removed**: Vendor assignment logic (no more fuzzy matching to SANDHYA/MOKSHITHA/KUMAR columns)
3. **Removed**: Google Drive upload functionality
4. **Added**: Zoho integration (fetches invoices from drafts folder in Gmail or via Zoho API)
5. **Added**: Invoice number-based matching (primary key for reconciliation)
6. **Added**: SQLite database for structured storage
7. **Added**: Excel reports with MATCHED/UNMATCHED/NOT_FOUND sheets

### 🔄 New Workflow:

```
📧 Inbox Payment Advices → 📥 Gmail Drafts Invoices → 🔄 Match by Invoice# → 📊 Excel Report
```

## Architecture

### Files Created:
- `payment_reconciliation.py` - Main orchestrator
- `payment_advice_extractor.py` - Extracts payment details from bank emails
- `zoho_client.py` - Fetches invoices from Gmail drafts or Zoho API
- `reconciliation_engine.py` - Matches payments with invoices
- `database.py` - SQLite database layer

### Files Kept (Unchanged):
- `invoice_processor_final.py` - Original invoice processor (still works)
- `openai_vision_extractor.py` - OpenAI Vision helper (used as fallback)
- `google_drive_uploader.py` - Not used in reconciliation, but kept for old workflow

## Setup Instructions

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Configure Zoho (Optional - for API access)
If you want to fetch invoices from Zoho Books API instead of Gmail drafts:

1. Go to https://api-console.zoho.com/
2. Create a new "Server-based Application"
3. Get your Client ID and Client Secret
4. Generate a Refresh Token (follow Zoho OAuth flow)
5. Get your Organization ID from Zoho Books settings

Update `.env` file:
```ini
ZOHO_CLIENT_ID=your_actual_client_id
ZOHO_CLIENT_SECRET=your_actual_client_secret
ZOHO_REFRESH_TOKEN=your_actual_refresh_token
ZOHO_ORGANIZATION_ID=your_actual_org_id
```

**NOTE**: If you don't configure Zoho, the system will automatically fetch invoices from **Gmail Drafts** folder (no extra setup needed).

### 3. Prepare Invoices in Gmail Drafts
For the system to work without Zoho API:
1. Save invoice PDFs as **drafts** in your Gmail account
2. The system will scan `[Gmail]/Drafts` folder and extract invoice numbers, amounts, dates

## Usage

### Run Payment Reconciliation:
```powershell
python payment_reconciliation.py
```

### What It Does:
1. **Scans Gmail Inbox** for payment advice emails (keywords: "payment advice", "NEFT", "RTGS", "UTR", etc.)
2. **Extracts from PDFs** using PyPDF2 first (text extraction), then OpenAI Vision if text is poor
3. **Fetches invoices** from Gmail Drafts folder (extracts invoice numbers, amounts, dates from PDFs)
4. **Matches by invoice number** - compares payment invoice# with Zoho invoice#
5. **Checks for discrepancies**:
   - Amount mismatch (tolerance: ₹1)
   - Date mismatch (tolerance: 30 days)
   - Invoice status issues
6. **Generates Excel report** with sheets:
   - `MATCHED` - Perfect matches
   - `UNMATCHED` - Discrepancies found (amount/date mismatches)
   - `NOT_FOUND` - Invoice number not found in Zoho
   - `ALL_RESULTS` - Complete dataset
   - `SUMMARY` - Statistics

## Excel Report Columns

| Column | Description |
|--------|-------------|
| invoice_number | Invoice reference number |
| match_status | MATCHED / UNMATCHED / NOT_FOUND |
| payment_amount | Amount from payment advice |
| invoice_amount | Amount from Zoho invoice |
| amount_difference | Absolute difference |
| amount_match | TRUE if amounts match (±₹1) |
| date_match | TRUE if dates within 30 days |
| confidence_score | Matching confidence (0-100%) |
| discrepancy_notes | Details of mismatches |
| bank_name | Bank from payment advice |
| utr_number | Transaction reference |
| customer_name | Customer from invoice |

## Database Schema

### payment_advices
Stores extracted payment advice data from emails.

### zoho_invoices
Caches invoice data fetched from Zoho/Gmail drafts.

### reconciliation_results
Stores matching results with match_status (MATCHED/UNMATCHED/NOT_FOUND).

## Matching Logic

### Primary Match:
- **Invoice Number** must exactly match (case-insensitive)

### Validation Checks:
1. **Amount Match**: `|payment_amount - invoice_amount| <= ₹1`
2. **Date Match**: `|payment_date - invoice_date| <= 30 days`
3. **Status Check**: Invoice not already paid

### Confidence Scoring:
- **100%**: Perfect match (amount + date + status)
- **80-99%**: Minor discrepancies (within tolerance)
- **50-79%**: Significant discrepancies
- **<50%**: Major mismatches

### Status Assignment:
- **MATCHED**: Confidence ≥ 80%
- **UNMATCHED**: 50% ≤ Confidence < 80% (review needed)
- **NOT_FOUND**: Invoice number not in Zoho

## Environment Variables

```ini
# OpenAI (for PDF extraction fallback)
OPENAI_API_KEY=sk-proj-...
ENABLE_OPENAI_VISION=true

# Gmail (for payment advices + invoice drafts)
GMAIL_EMAIL=your_email@gmail.com
GMAIL_PASSWORD=your_app_password

# Processing
DAYS_TO_SEARCH=10

# Zoho (optional - if not set, uses Gmail drafts)
ZOHO_CLIENT_ID=...
ZOHO_CLIENT_SECRET=...
ZOHO_REFRESH_TOKEN=...
ZOHO_ORGANIZATION_ID=...
```

## Example Output

```
💰 PAYMENT RECONCILIATION SYSTEM
==================================================
1. 📧 Extract payment advices from email inbox
2. 📥 Sync invoices from Gmail drafts folder
3. 🔄 Match payment advices with invoices by invoice number
4. 📊 Generate Excel report (MATCHED/UNMATCHED/NOT_FOUND)
==================================================

📧 STEP 1: Extracting payment advices from inbox...
✅ Connected to Gmail
📧 Found 50 emails to scan
💰 Payment advice found: NEFT Payment Advice - INV/2024/001
   📄 Extracting text from payment_advice.pdf using PDF reader...
   ✅ PDF text extracted successfully (1250 chars)
   ✅ Stored: Invoice INV/2024/001 - ₹50000.0

📥 STEP 2: Syncing invoices from Gmail drafts...
✅ Connected to Gmail drafts
📧 Found 10 emails in drafts
📄 Processing invoice PDF: invoice_INV-2024-001.pdf
   ✅ Extracted invoice: INV/2024/001
✅ Synced 10 invoices from drafts

🔄 STEP 3: Reconciling payments with invoices by invoice number...
📊 Found 1 pending payment advices

💰 Processing payment for invoice: INV/2024/001
🔍 Fetching invoice INV/2024/001 from Zoho...
✅ Cached invoice INV/2024/001 from Zoho
   Status: MATCHED
   Confidence: 100.0%
   Notes: No discrepancies found

📊 STEP 4: Generating Excel report...
   ✅ MATCHED: 1 records
✅ Excel report generated: payment_reconciliation_20251030_143522.xlsx

==================================================
✅ RECONCILIATION COMPLETE
==================================================
   ✅ MATCHED: 1 payments

==================================================
📄 Excel Report: payment_reconciliation_20251030_143522.xlsx
   - Sheet 'MATCHED': Successfully reconciled payments
   - Sheet 'UNMATCHED': Payments with discrepancies
   - Sheet 'NOT_FOUND': Payments without matching invoices
   - Sheet 'SUMMARY': Overview statistics
==================================================
```

## Troubleshooting

### Issue: "No invoices found in drafts"
**Solution**: Make sure invoice PDFs are saved as drafts in Gmail. The system looks for PDFs in `[Gmail]/Drafts`.

### Issue: "Invoice not found in Zoho"
**Solution**: 
1. Check if invoice PDF is in drafts
2. Verify invoice number format matches (e.g., INV/2024/001)
3. Configure Zoho API credentials if using Zoho Books

### Issue: "PDF text extraction insufficient"
**Solution**: System will automatically use OpenAI Vision. Make sure `ENABLE_OPENAI_VISION=true` in `.env`.

### Issue: "Amount mismatch"
**Solution**: Check if amounts include/exclude taxes. System allows ₹1 tolerance for rounding.

## Original Invoice Processor
The original `invoice_processor_final.py` still works independently for hotel invoice processing. It hasn't been modified.

To run the old system:
```powershell
python invoice_processor_final.py
```

## Support
For Zoho API setup help: https://www.zoho.com/books/api/v3/

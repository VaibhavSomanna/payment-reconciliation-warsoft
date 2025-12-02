# Payment Reconciliation System - Warsoft Integration

Automated payment reconciliation system that matches payment advice emails with Warsoft unpaid invoices and automatically writes matched payments back to Warsoft.

## Features

- ✅ **Email Extraction**: Automatically extracts payment advices from Gmail
- ✅ **PDF Processing**: Extracts data from payment advice PDFs (invoice numbers, amounts, dates, bank references)
- ✅ **Field Extraction**: Extracts invoice_date, transaction_date, customer_name, bank_reference_number, TDS, etc.
- ✅ **Warsoft Integration**: Fetches unpaid invoices from Warsoft API
- ✅ **Smart Matching**: Matches payments with invoices by invoice number and amount
- ✅ **Auto-Write**: Automatically writes matched payments to Warsoft
- ✅ **Excel Reports**: Generates detailed reconciliation reports (MATCHED/UNMATCHED/NOT_FOUND)
- ✅ **Multi-Invoice Support**: Handles payment advices with multiple invoices

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required configuration:

```env
# Gmail Configuration
GMAIL_EMAIL=your_email@gmail.com
GMAIL_PASSWORD=your_app_password
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993

# Warsoft API
WARSOFT_ACCESS_TOKEN=your_warsoft_access_token
WARSOFT_READ_URL=https://hbinvoiceapi.staysimplyfied.com/api/ClientInvoice/UnPaidinvoicedata
WARSOFT_WRITE_URL=https://hbinvoiceapi.staysimplyfied.com/api/ClientInvoice/Push
```

### 3. Gmail App Password

1. Go to your Google Account settings
2. Navigate to Security → 2-Step Verification
3. Scroll down to "App passwords"
4. Generate a new app password for "Mail"
5. Copy the 16-character password to `.env`

## Usage

### Run Full Reconciliation

```bash
python payment_reconciliation.py
```

This will:
1. Extract payment advices from Gmail (last 365 days by default)
2. Fetch unpaid invoices from Warsoft
3. Match payments with invoices
4. **Automatically write matched payments to Warsoft**
5. Generate Excel reports

### Test Warsoft Connection

```bash
python warsoft_client.py
```

This will test your Warsoft API connection and fetch sample invoices.

## Payment Advice Field Extraction

The system extracts the following fields from payment advice PDFs:

### Core Fields
- **invoice_number**: Invoice number (e.g., "10EXT2425/106")
- **invoice_date**: Date near the invoice number
- **payment_amount**: Net payment amount (after TDS)
- **bill_amount**: Gross invoice amount (before TDS)
- **tds_amount**: TDS deducted

### New Fields
- **customer_name**: Extracted from "Remitter Name" or email
- **bank_reference_number**: UTR/reference (CITIN25657707761, HSBCN52025112997504684, etc.)
- **transaction_date**: Date from top of payment advice PDF
- **payment_date**: Date of payment
- **bank_name**: Bank name extracted from payment advice

## Warsoft API Integration

### Read API (Unpaid Invoices)

**Endpoint**: `POST /api/ClientInvoice/UnPaidinvoicedata`

**Request**:
```json
{
  "pageNo": 1
}
```

**Response Structure**:
```json
{
  "unmappedInvoices": [
    {
      "invoicedate": "2024-05-03",
      "invoiceNumber": "10EXT2425/106",
      "invoiceStatus": "overdue",
      "cusotmerName": "Nearby Technologies Pvt Ltd.",
      "subTotal": 6750,
      "cgst": 405,
      "sgst": 405,
      "igst": 0,
      "total": 7560,
      "balance": 7560
    }
  ]
}
```

### Write API (Push Matched Payments)

**Endpoint**: `POST /api/ClientInvoice/Push`

**Request**:
```json
{
  "client_name": "Nearby Technologies Pvt Ltd.",
  "invoice_number": "4EXT2526/450",
  "invoice_date": "2024-05-03",
  "amount": "7400",
  "tds": "160",
  "file_name": "payment_advice.pdf",
  "file_location": "",
  "bank_reference": "CITIN25657707761",
  "total_amount": "7560",
  "transaction_date": "2024-05-10"
}
```

When a payment is successfully matched:
- The system automatically calls the Write API
- Sends invoice number, amounts, TDS, bank reference, dates, etc.
- Marks the payment as reconciled in the database

## Bank Reference Number Patterns

The system recognizes these bank reference patterns:

- **Citi Bank**: CITIN25657707761
- **HSBC**: HSBCN52025112997504684
- **SBI**: SBIN525331564590
- **Standard Chartered**: SCBLN52025112700783823
- **Other Banks**: IN1ON251126022I2

And many more (40+ bank prefixes supported).

## Database Schema

### payment_advices
- All payment advice data including new fields
- invoice_date, transaction_date, customer_name, bank_reference_number

### warsoft_invoices
- Cached unpaid invoices from Warsoft
- invoice_number, customer_name, amounts, GST breakup

### reconciliation_results
- Matching results with confidence scores
- Links payment_advices to warsoft_invoices

## Excel Reports

The system generates two types of reports:

### 1. Reconciliation Report
- **MATCHED**: Successfully matched and written to Warsoft
- **UNMATCHED**: Discrepancies found (amount mismatch, etc.)
- **NOT_FOUND**: Invoice not found in Warsoft
- **ALL_RESULTS**: Complete data
- **SUMMARY**: Statistics

### 2. No Invoice Number Report
- Payment advices where invoice number couldn't be extracted
- Requires manual review

## Troubleshooting

### No invoices fetched from Warsoft
- Check `WARSOFT_ACCESS_TOKEN` in `.env`
- Verify API endpoint URLs
- Test with: `python warsoft_client.py`

### Payment advices not extracted
- Check Gmail credentials
- Verify IMAP settings
- Check if emails contain payment advice keywords

### Bank reference not extracted
- Check if reference number matches supported patterns
- Verify PDF text extraction is working

### Amount mismatch
- System compares net payment amount with invoice total
- Check TDS calculations
- Review bill_amount vs payment_amount

## Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `GMAIL_EMAIL` | Gmail address | `user@gmail.com` |
| `GMAIL_PASSWORD` | Gmail app password | `xxxx xxxx xxxx xxxx` |
| `WARSOFT_ACCESS_TOKEN` | Warsoft API token | `your_token_here` |
| `WARSOFT_READ_URL` | Unpaid invoices endpoint | `https://...UnPaidinvoicedata` |
| `WARSOFT_WRITE_URL` | Payment push endpoint | `https://...Push` |
| `DAYS_TO_SEARCH` | Email search days | `365` |
| `MARK_PAYMENT_EMAILS_AS_READ` | Mark processed emails | `false` |

## File Structure

```
.
├── payment_reconciliation.py      # Main orchestrator
├── warsoft_client.py              # Warsoft API client
├── payment_advice_extractor.py    # Email & PDF extraction
├── reconciliation_engine.py       # Matching logic
├── database.py                    # SQLite database
├── requirements.txt               # Python dependencies
├── .env                          # Configuration (create from .env.example)
└── reconciliation.db             # SQLite database (auto-created)
```

## Support

For issues or questions, please check:
1. `.env` configuration is correct
2. Gmail app password is valid
3. Warsoft API token is active
4. Run test scripts to isolate issues

## License

Proprietary - All rights reserved

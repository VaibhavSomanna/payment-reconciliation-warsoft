#!/usr/bin/env python3
"""
Quick test script for reconciliation with specific page range
"""
import os
os.environ['MAX_EMAILS_TO_PROCESS'] = '10'  # Process 10 emails
os.environ['START_PAGE'] = '200'  # Start from page 200
os.environ['END_PAGE'] = '300'  # End at page 300

from payment_reconciliation import main

if __name__ == "__main__":
    print("🧪 Testing reconciliation with 10 emails and Warsoft pages 200-300...")
    print("   This will fetch ~25,250 invoices (101 pages × ~250 invoices/page)\n")
    main()

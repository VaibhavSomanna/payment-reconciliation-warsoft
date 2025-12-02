#!/usr/bin/env python3
"""
Quick test script for reconciliation with limited emails and pages
"""
import os
os.environ['MAX_EMAILS_TO_PROCESS'] = '10'  # Set before imports
os.environ['MAX_PAGES_TO_FETCH'] = '10'  # Limit Warsoft API to 10 pages

from payment_reconciliation import main

if __name__ == "__main__":
    print("🧪 Testing reconciliation with 10 emails and 10 Warsoft pages...")
    main()

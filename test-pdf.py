#!/usr/bin/env python3
"""
Simple script to extract text from PDF using PaymentAdviceExtractor
"""
from payment_advice_extractor import PaymentAdviceExtractor
import os

# Create extractor instance
extractor = PaymentAdviceExtractor()

# Get PDF file path from user
pdf_file = input('Enter PDF path: ')

# Read and extract text from PDF
with open(pdf_file, 'rb') as f:
    pdf_data = f.read()
    text = extractor.extract_from_pdf_text(pdf_data)

# Print extracted text (first 1000 characters)
print('\n=== EXTRACTED TEXT ===\n')
print(text[:1000])

# Optional: Print full text length
print(f'\n\n=== TOTAL TEXT LENGTH: {len(text)} characters ===')
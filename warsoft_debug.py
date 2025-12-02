#!/usr/bin/env python3
"""
Debug script to test Warsoft API connection
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

# Get credentials
ACCESS_TOKEN = os.getenv('WARSOFT_ACCESS_TOKEN') or os.getenv('ACCESS_TOKEN')
READ_URL = os.getenv('WARSOFT_READ_URL', 'https://hbinvoiceapi.staysimplyfied.com/api/ClientInvoice/UnPaidinvoicedata')

print("=" * 70)
print("🔍 WARSOFT API DEBUG TEST")
print("=" * 70)
print(f"URL: {READ_URL}")
print(f"Token: {ACCESS_TOKEN[:20]}..." if ACCESS_TOKEN else "Token: NOT SET")
print("=" * 70)

if not ACCESS_TOKEN:
    print("❌ Error: WARSOFT_ACCESS_TOKEN not found in .env file")
    exit(1)

# Test connection
headers = {
    'accept': 'text/plain',
    'Authorization': f'Bearer {ACCESS_TOKEN}',
    'Content-Type': 'application/json'
}

page_no = 1
print(f"\n📤 Sending request to page {page_no}...")
print(f"Headers: {json.dumps({k: v[:50] + '...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")

payload = {"pageNo": page_no}
print(f"Payload: {json.dumps(payload, indent=2)}")

try:
    response = requests.post(
        READ_URL,
        headers=headers,
        json=payload,
        timeout=30
    )
    
    print(f"\n📥 Response Status: {response.status_code}")
    print(f"Response Headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    
    print(f"\n📄 Response Body (first 1000 chars):")
    print(response.text[:1000])
    
    if response.status_code == 200:
        try:
            data = response.json()
            print(f"\n✅ JSON parsed successfully!")
            print(f"Response type: {type(data)}")
            
            if isinstance(data, dict):
                print(f"Response keys: {list(data.keys())}")
                for key in data.keys():
                    if isinstance(data[key], list):
                        print(f"  - {key}: list with {len(data[key])} items")
                    else:
                        print(f"  - {key}: {type(data[key])}")
            elif isinstance(data, list):
                print(f"Response is a list with {len(data)} items")
                if data:
                    print(f"\nFirst invoice:")
                    print(json.dumps(data[0], indent=2))
            
        except json.JSONDecodeError as e:
            print(f"\n❌ Failed to parse JSON: {e}")
    else:
        print(f"\n❌ Request failed with status {response.status_code}")

except requests.exceptions.RequestException as e:
    print(f"\n❌ Request error: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Error response: {e.response.text[:1000]}")
#!/usr/bin/env python3
"""
Azure Blob Storage client for uploading payment advice PDFs
"""
import os
import io
from datetime import datetime
from azure.storage.blob import ContainerClient
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()


class BlobStorageClient:
    def __init__(self):
        """Initialize blob storage client with SAS URL from environment"""
        self.sas_url = os.getenv('AZURE_BLOB_SAS_URL') or os.getenv('BLOB_STORAGE_SAS_URL')
        
        if not self.sas_url:
            print("❌ ERROR: AZURE_BLOB_SAS_URL or BLOB_STORAGE_SAS_URL not found in .env file!")
            raise ValueError("AZURE_BLOB_SAS_URL environment variable not set")
        
        try:
            # Parse SAS URL
            parsed_url = urlparse(self.sas_url)
            self.container_name = parsed_url.path.strip('/').split('/')[-1] if parsed_url.path else 'receipts'
            self.account_url = f"https://{parsed_url.netloc}"
            self.sas_token = parsed_url.query
            
            # Create container client
            self.container_client = ContainerClient(
                self.account_url, 
                self.container_name, 
                credential=self.sas_token
            )
            
            print(f"✅ Blob Storage client initialized")
            print(f"   Account: {self.account_url}")
            print(f"   Container: {self.container_name}")
            
        except Exception as e:
            print(f"❌ ERROR initializing Blob Storage client: {e}")
            raise

    def format_blob_name(self, filename, folder_prefix=None):
        """
        Format the blob name as datetime_filename with spaces replaced by hyphens.
        
        Args:
            filename (str): Original filename
            folder_prefix (str, optional): Folder prefix to organize blobs (e.g., "KUMAR", "MOKSHITHA")
        
        Returns:
            str: Formatted filename in "YYYY-MM-DD_HH:MM_filename" format with spaces replaced by hyphens
        """
        # Get current datetime in format: YYYY-MM-DD_HH:MM (without seconds)
        now = datetime.now()
        datetime_prefix = now.strftime("%Y-%m-%d_%H:%M")
        
        # Get the base filename (without path) and sanitize it
        base_name = os.path.basename(filename)
        safe_filename = base_name.replace(" ", "-").replace("'", "").replace('"', '')
        safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in ".-_")
        
        # Combine: datetime_filename
        blob_name = f"{datetime_prefix}_{safe_filename}"
        
        # Add folder prefix if provided (simulates folder structure using blob name prefix)
        if folder_prefix:
            folder_prefix = folder_prefix.replace(" ", "-").replace("/", "-")
            blob_name = f"{folder_prefix}/{blob_name}"
        
        return blob_name

    def upload_pdf(self, pdf_data, original_filename='payment_advice.pdf', folder_prefix=None):
        """
        Upload PDF bytes directly to Azure Blob Storage.
        The blob name will be automatically formatted with folder prefix and date.
        
        Args:
            pdf_data (bytes): PDF file content as bytes
            original_filename (str): Original filename (used for naming)
            folder_prefix (str, optional): Folder prefix to organize blobs (e.g., "KUMAR", "MOKSHITHA")
        
        Returns:
            tuple: (blob_url with SAS token, unique_filename) or (None, None) if upload fails
        """
        # Validate PDF data
        if not pdf_data:
            print(f"   ❌ ERROR: No PDF data provided (pdf_data is None or empty)")
            return None, None
            
        if not isinstance(pdf_data, bytes):
            print(f"   ❌ ERROR: pdf_data is not bytes (type: {type(pdf_data)})")
            return None, None
            
        if len(pdf_data) < 4:
            print(f"   ❌ ERROR: PDF data too small ({len(pdf_data)} bytes)")
            return None, None
        
        try:
            # Format blob name with datetime prefix
            unique_filename = self.format_blob_name(original_filename, folder_prefix)
            
            print(f"   📤 Uploading {len(pdf_data)} bytes as {unique_filename}...")
            
            # Get blob client
            blob_client = self.container_client.get_blob_client(unique_filename)
            
            # Upload PDF bytes
            blob_client.upload_blob(io.BytesIO(pdf_data), overwrite=True)
            
            # Construct blob URL WITH SAS token (for download access)
            blob_url = f"{self.account_url}/{self.container_name}/{unique_filename}?{self.sas_token}"
            
            print(f"   ✅ PDF uploaded successfully!")
            print(f"      URL: {blob_url}")
            
            return blob_url, unique_filename
            
        except Exception as e:
            print(f"   ❌ ERROR uploading PDF to blob storage:")
            print(f"      Error type: {type(e).__name__}")
            print(f"      Error message: {str(e)}")
            import traceback
            print(f"      Traceback: {traceback.format_exc()}")
            return None, None

    def get_blob_url_with_sas(self, filename):
        """Get full blob URL with SAS token for accessing the file"""
        return f"{self.account_url}/{self.container_name}/{filename}?{self.sas_token}"


def upload_pdf_to_blob_storage(pdf_file_path, blob_name=None, sas_url=None):
    """
    Upload a PDF file to Azure Blob Storage using a SAS URL.
    The blob name will be automatically formatted as "datetime_filename" with spaces replaced by hyphens.
    
    Args:
        pdf_file_path (str): Path to the PDF file to upload
        blob_name (str, optional): Custom name for the blob in storage. If not provided, uses datetime_filename format
        sas_url (str, optional): SAS URL for the blob container. If not provided, uses the default one
    
    Returns:
        str: URL of the uploaded blob
    """
    # Validate file exists
    if not os.path.exists(pdf_file_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_file_path}")
    
    # Validate it's a PDF file
    if not pdf_file_path.lower().endswith('.pdf'):
        raise ValueError("File must be a PDF file (.pdf extension)")
    
    # Read PDF file
    with open(pdf_file_path, "rb") as f:
        pdf_bytes = f.read()
    
    # Create client and upload
    client = BlobStorageClient()
    
    # Extract folder prefix from custom blob name if provided
    folder_prefix = None
    if blob_name and '/' in blob_name:
        folder_prefix = blob_name.split('/')[0]
        blob_name = blob_name.split('/')[-1]
    
    uploaded_url, uploaded_filename = client.upload_pdf(pdf_bytes, blob_name or pdf_file_path, folder_prefix)
    
    if uploaded_url:
        print(f"Successfully uploaded PDF to: {uploaded_url}")
        return uploaded_url
    else:
        raise Exception("Upload failed")


def upload_pdf_simple(pdf_file_path, blob_name=None):
    """
    Simplified function to upload PDF using the default SAS URL.
    The blob name will be automatically formatted as "datetime_filename" with spaces replaced by hyphens.
    
    Args:
        pdf_file_path (str): Path to the PDF file to upload
        blob_name (str, optional): Custom name for the blob in storage. If not provided, uses datetime_filename format
    
    Returns:
        str: URL of the uploaded blob
    """
    return upload_pdf_to_blob_storage(pdf_file_path, blob_name)


if __name__ == "__main__":
    import sys
    
    # Test blob storage client
    print("Testing Blob Storage Client...")
    
    if len(sys.argv) > 1:
        # Upload from command line
        pdf_path = sys.argv[1]
        blob_name = sys.argv[2] if len(sys.argv) > 2 else None
        
        try:
            url = upload_pdf_simple(pdf_path, blob_name)
            print(f"\n✅ Upload successful!")
            print(f"Blob URL: {url}")
        except Exception as e:
            print(f"❌ Error uploading PDF: {e}")
            sys.exit(1)
    else:
        # Test client initialization
        try:
            client = BlobStorageClient()
            print("\n✅ Client initialized successfully!")
            
            # Test with a sample PDF file if it exists
            test_pdf_path = "test_receipt.pdf"
            if os.path.exists(test_pdf_path):
                with open(test_pdf_path, 'rb') as f:
                    pdf_data = f.read()
                
                url, filename = client.upload_pdf(pdf_data, "test_receipt.pdf")
                if url:
                    print(f"\n✅ Test upload successful!")
                    print(f"   URL: {url}")
                    print(f"   Filename: {filename}")
                else:
                    print("\n❌ Test upload failed!")
            else:
                print(f"\n⚠️  Create a '{test_pdf_path}' file to test upload")
                print("   (Client initialization was successful)")
                print("\nUsage: python blob_storage_client.py <path_to_pdf_file> [blob_name]")
                
        except Exception as e:
            print(f"\n❌ Test failed: {e}")

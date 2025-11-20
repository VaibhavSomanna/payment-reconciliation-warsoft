import os
import json
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def get_env_value(name, *, default=None, required=False):
    """Fetch environment variable values with optional defaults."""
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Environment variable '{name}' is required but missing.")
    return value


class BedrockPDFExtractor:
    def __init__(
            self,
            region_name=None,
            model_id=None,
            aws_access_key_id=None,
            aws_secret_access_key=None,
            aws_session_token=None,
    ):
        """
        Initialize Bedrock client for Amazon Nova Pro using Converse API

        Args:
            region_name: AWS region (default: us-east-1)
            model_id: Model ID (default: amazon.nova-pro-v1:0)
        """
        region_name = region_name or get_env_value("AWS_REGION", default="us-east-1")
        model_id = model_id or get_env_value("BEDROCK_MODEL_ID", default="amazon.nova-pro-v1:0")
        aws_access_key_id = aws_access_key_id or get_env_value("AWS_ACCESS_KEY_ID", required=True)
        aws_secret_access_key = aws_secret_access_key or get_env_value("AWS_SECRET_ACCESS_KEY", required=True)
        aws_session_token = aws_session_token or get_env_value("AWS_SESSION_TOKEN", default=None)

        self.client = boto3.client(
            service_name='bedrock-runtime',
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token
        )
        self.model_id = model_id

    def _sanitize_filename(self, filename):
        """
        Sanitize filename to meet Bedrock API requirements:
        - Only alphanumeric, whitespace, hyphens, parentheses, square brackets
        - No consecutive whitespace
        """
        import re
        # Remove invalid characters
        sanitized = re.sub(r'[^a-zA-Z0-9\s\-()\[\]]', '_', filename)
        # Replace consecutive whitespace with single space
        sanitized = re.sub(r'\s+', ' ', sanitized)
        return sanitized.strip()

    def _read_pdf(self, pdf_path):
        """
        Read PDF file as bytes

        Args:
            pdf_path: Path to PDF file

        Returns:
            PDF content as bytes
        """
        with open(pdf_path, 'rb') as file:
            return file.read()

    def extract_pdf_details(self, pdf_path, extraction_prompt=None, max_tokens=4096, temperature=0.3):
        """
        Extract detailed information from PDF using Amazon Nova Pro

        Args:
            pdf_path: Path to PDF file
            extraction_prompt: Custom prompt for extraction (optional)
            max_tokens: Maximum tokens to generate (default: 4096)
            temperature: Temperature for generation (default: 0.3)

        Returns:
            Extracted information as string
        """
        # Default prompt if none provided
        if extraction_prompt is None:
            extraction_prompt = """Please analyze this PDF document and extract the following details:

1. Document type and purpose
2. Key information (dates, names, amounts, etc.)
3. Main sections and their content
4. Any tables or structured data
5. Important notes or highlights

Provide a comprehensive and structured summary."""

        # Read PDF file
        document_bytes = self._read_pdf(pdf_path)

        # Sanitize filename for Bedrock API
        sanitized_name = self._sanitize_filename(Path(pdf_path).name)

        # Create conversation with document
        conversation = [
            {
                "role": "user",
                "content": [
                    {"text": extraction_prompt},
                    {
                        "document": {
                            "format": "pdf",
                            "name": sanitized_name,
                            "source": {"bytes": document_bytes}
                        }
                    }
                ]
            }
        ]

        try:
            # Send message using Converse API
            response = self.client.converse(
                modelId=self.model_id,
                messages=conversation,
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": temperature
                }
            )

            # Extract and return response text
            return response["output"]["message"]["content"][0]["text"]

        except ClientError as e:
            raise Exception(f"Error invoking model: {e}")

    def extract_structured_data(self, pdf_path, fields_to_extract, max_tokens=4096):
        """
        Extract specific structured fields from PDF

        Args:
            pdf_path: Path to PDF file
            fields_to_extract: List of fields to extract
            max_tokens: Maximum tokens to generate

        Returns:
            Extracted structured data as string
        """
        fields_list = "\n".join([f"- {field}" for field in fields_to_extract])
        prompt = f"""Extract the following specific information from this PDF document:

{fields_list}

Return the information in a clear, structured format with labels. If a field is not found, indicate "Not found"."""

        return self.extract_pdf_details(pdf_path, prompt, max_tokens=max_tokens)

    def extract_as_json(self, pdf_path, fields_to_extract, max_tokens=4096):
        """
        Extract specific fields and return as JSON format

        Args:
            pdf_path: Path to PDF file
            fields_to_extract: List of fields to extract
            max_tokens: Maximum tokens to generate

        Returns:
            Extracted data in JSON format
        """
        fields_list = "\n".join([f"- {field}" for field in fields_to_extract])
        prompt = f"""Extract the following information from this PDF document:

{fields_list}

Return ONLY a valid JSON object with these fields as keys. If a field is not found, use null as the value.
Do not include any explanation, just the JSON object."""

        result = self.extract_pdf_details(pdf_path, prompt, max_tokens=max_tokens, temperature=0.1)

        # Try to parse as JSON
        try:
            # Remove markdown code blocks if present
            clean_result = result.strip()
            if clean_result.startswith("```json"):
                clean_result = clean_result[7:]
            if clean_result.startswith("```"):
                clean_result = clean_result[3:]
            if clean_result.endswith("```"):
                clean_result = clean_result[:-3]

            return json.loads(clean_result.strip())
        except json.JSONDecodeError:
            return {"raw_response": result, "note": "Could not parse as JSON"}

    def extract_invoice_fields(self, pdf_path, max_tokens=4096):
        """
        Extract invoice/booking fields from PDF

        Args:
            pdf_path: Path to PDF file
            max_tokens: Maximum tokens to generate

        Returns:
            Extracted data in JSON format
        """
        fields = [
            "booking_code",
            "bill_number",
            "property_name",
            "hbd_gst_number",
            "client_gst_number",
            "check_in_date",
            "check_out_date",
            "total_amount",
            "guest_name",
            "room_type"
        ]
        return self.extract_as_json(pdf_path, fields, max_tokens=max_tokens)


# Example usage
if __name__ == "__main__":
    import sys

    # Initialize extractor
    extractor = BedrockPDFExtractor()

    # Get PDF path from command line or use default
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "tarun nandwani.pdf"

    print(f"=== Extracting Invoice Fields from: {pdf_path} ===")
    try:
        result = extractor.extract_invoice_fields(pdf_path)
        print(json.dumps(result, indent=2))
    except FileNotFoundError:
        print(f"Error: PDF file '{pdf_path}' not found.")
        print("\nUsage: python aws_nova.py <path_to_pdf>")
    except Exception as e:
        print(f"Error: {e}")
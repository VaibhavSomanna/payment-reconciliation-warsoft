#!/usr/bin/env python3
"""
FastAPI Server for Invoice Reconciliation System
Provides REST API endpoints for the React frontend
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
from datetime import datetime
import os
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment
from dotenv import load_dotenv

from payment_advice_extractor import PaymentAdviceExtractor
from warsoft_client import WarsoftClient
from reconciliation_engine import ReconciliationEngine
from database import ReconciliationDB

load_dotenv()

app = FastAPI(title="Invoice Reconciliation API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
reconciliation_status = {
    "is_running": False,
    "progress": 0,
    "status_message": "Ready",
    "last_run": None,
    "results": None
}


class ReconciliationRequest(BaseModel):
    max_emails: int = 1000000
    days_back: int = 7
    auto_mark_paid: bool = True
    start_page: int = 1
    end_page: int = 999999


class InvoiceSearchRequest(BaseModel):
    invoice_number: str


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "Invoice Reconciliation API is running"}


@app.get("/api/status")
async def get_status():
    """Get current reconciliation status"""
    return reconciliation_status


@app.post("/api/reconcile")
async def start_reconciliation(request: ReconciliationRequest, background_tasks: BackgroundTasks):
    """Start reconciliation process"""
    if reconciliation_status["is_running"]:
        raise HTTPException(status_code=400, detail="Reconciliation is already running")

    # Update environment variables
    os.environ['MAX_EMAILS_TO_PROCESS'] = str(request.max_emails)
    os.environ['START_PAGE'] = str(request.start_page)
    os.environ['END_PAGE'] = str(request.end_page)

    # Start reconciliation in background
    background_tasks.add_task(run_reconciliation, request.days_back, request.auto_mark_paid)

    return {
        "message": "Reconciliation started",
        "max_emails": request.max_emails,
        "auto_mark_paid": request.auto_mark_paid,
        "warsoft_pages": f"{request.start_page}-{request.end_page}"
    }


@app.get("/api/results")
async def get_results():
    """Get reconciliation results"""
    db = ReconciliationDB()

    # Get all reconciliation results
    results = db.get_all_reconciliation_results()

    # Get summary statistics
    total_invoices = len(results)
    matched = sum(1 for r in results if r['match_status'] == "MATCHED")
    not_found = sum(1 for r in results if r['match_status'] == "NOT_FOUND" or r['match_status'] == "NOT_FOUND_IN_WARSOFT")
    amount_mismatch = sum(1 for r in results if r['match_status'] in ["AMOUNT_MISMATCH", "UNMATCHED", "PARTIAL_MATCH"])

    return {
        "summary": {
            "total": total_invoices,
            "matched": matched,
            "not_found": not_found,
            "amount_mismatch": amount_mismatch
        },
        "results": [
            {
                "id": r['recon_id'],
                "invoice_number": r['invoice_number'],
                "status": r['match_status'],
                "gross_amount": float(r['bill_amount'] or 0),  # Gross amount (before TDS)
                "tds": float(r['tds_amount'] or 0),  # TDS amount
                "bank_reference": r['bank_reference_number'] or r['utr_number'] or '-',  # Bank reference
                "notes": r['discrepancy_notes'] or '',
                "reconciliation_date": r['reconciled_date']
            }
            for r in results
        ]
    }


@app.get("/api/invoice/{invoice_number}")
async def search_invoice(invoice_number: str):
    """Search for a specific invoice"""
    db = ReconciliationDB()

    # Get payment advice
    payment_advice = db.get_payment_advice_by_invoice(invoice_number)

    # Get reconciliation result
    reconciliation = db.get_reconciliation_by_invoice(invoice_number)

    if not payment_advice and not reconciliation:
        raise HTTPException(status_code=404, detail="Invoice not found")

    result = {
        "invoice_number": invoice_number,
        "payment_advice": None,
        "reconciliation": None
    }

    if payment_advice:
        result["payment_advice"] = {
            "id": payment_advice[0],
            "invoice_number": payment_advice[1],
            "payment_date": payment_advice[2],
            "payment_amount": payment_advice[3],
            "net_payment_amount": payment_advice[4],
            "bill_amount": payment_advice[5],
            "tds_amount": payment_advice[6],
            "bank_name": payment_advice[7],
            "email_subject": payment_advice[10],
            "status": payment_advice[14]
        }

    if reconciliation:
        result["reconciliation"] = {
            "id": reconciliation[0],
            "invoice_number": reconciliation[1],
            "payment_amount": reconciliation[2],
            "status": reconciliation[3],
            "zoho_invoice_number": reconciliation[4],
            "zoho_total": reconciliation[5],
            "amount_difference": reconciliation[6],
            "notes": reconciliation[7],
            "reconciliation_date": reconciliation[8]
        }

    return result


@app.delete("/api/clear")
async def clear_data():
    """Clear all reconciliation data"""
    db = ReconciliationDB()
    db.clear_payment_advices()
    db.clear_reconciliation_results()

    global reconciliation_status
    reconciliation_status["results"] = None
    reconciliation_status["last_run"] = None

    return {"message": "All data cleared successfully"}


@app.get("/api/download-excel")
async def download_excel():
    """Generate and download Excel report"""
    db = ReconciliationDB()

    # Get all reconciliation results
    results = db.get_all_reconciliation_results()

    if not results:
        raise HTTPException(status_code=404, detail="No reconciliation data available")

    # Convert to DataFrame
    df = pd.DataFrame([dict(row) for row in results])

    # Create Excel with multiple sheets
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'reconciliation_report_{timestamp}.xlsx'
    filepath = os.path.join(os.getcwd(), filename)

    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        # Sheet 1: MATCHED
        matched_df = df[df['match_status'] == 'MATCHED'].copy()
        if not matched_df.empty:
            matched_df.to_excel(writer, sheet_name='MATCHED', index=False)

        # Sheet 2: UNMATCHED (includes PARTIAL_MATCH)
        unmatched_df = df[df['match_status'].isin(['UNMATCHED', 'PARTIAL_MATCH', 'AMOUNT_MISMATCH'])].copy()
        if not unmatched_df.empty:
            unmatched_df.to_excel(writer, sheet_name='UNMATCHED', index=False)

        # Sheet 3: NOT_FOUND
        not_found_df = df[df['match_status'].isin(['NOT_FOUND', 'NOT_FOUND_IN_WARSOFT'])].copy()
        if not not_found_df.empty:
            not_found_df.to_excel(writer, sheet_name='NOT_FOUND', index=False)

        # Sheet 4: ALL RESULTS
        df.to_excel(writer, sheet_name='ALL_RESULTS', index=False)

        # Sheet 5: SUMMARY
        summary_data = {
            'Category': [
                'Total Payments Processed',
                'MATCHED',
                'UNMATCHED (with discrepancies)',
                'NOT FOUND (invoice missing)',
                'Amount Mismatches',
                'Total Amount Difference'
            ],
            'Count/Value': [
                len(df),
                len(matched_df) if not matched_df.empty else 0,
                len(unmatched_df) if not unmatched_df.empty else 0,
                len(not_found_df) if not not_found_df.empty else 0,
                len(df[df['amount_match'] == False]),
                f"₹{df['amount_difference'].sum():.2f}"
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='SUMMARY', index=False)

        # Format headers
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]

            if sheet_name != 'SUMMARY':
                for cell in worksheet[1]:
                    cell.font = Font(bold=True, color="FFFFFF", size=11)
                    cell.fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
                    cell.alignment = Alignment(horizontal="center", vertical="center")

            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


async def run_reconciliation(days_back: int, auto_mark_paid: bool = True):
    """Background task to run reconciliation"""
    global reconciliation_status

    try:
        reconciliation_status["is_running"] = True
        reconciliation_status["progress"] = 10
        reconciliation_status["status_message"] = "Extracting payment advices from emails..."

        # Initialize components
        db = ReconciliationDB()
        extractor = PaymentAdviceExtractor()
        warsoft = WarsoftClient()
        engine = ReconciliationEngine(db=db, warsoft=warsoft, auto_write_matched=auto_mark_paid)

        # Clear previous data
        db.clear_payment_advices()
        db.clear_reconciliation_results()

        # Extract payment advices
        reconciliation_status["progress"] = 20
        payment_advices = extractor.fetch_payment_advices_from_email(days_back=days_back)

        # Store payment advices
        reconciliation_status["progress"] = 40
        reconciliation_status["status_message"] = f"Storing {len(payment_advices)} payment advices..."

        for advice in payment_advices:
            db.insert_payment_advice(advice)

        # Fetch Warsoft invoices
        reconciliation_status["progress"] = 50
        reconciliation_status["status_message"] = "Syncing Warsoft unpaid invoices..."
        unpaid_invoices = warsoft.fetch_all_unpaid_invoices()
        for inv_data in unpaid_invoices:
            inv = warsoft.parse_invoice(inv_data)
            db.insert_warsoft_invoice(inv)

        # Load invoice cache for fast reconciliation
        reconciliation_status["progress"] = 70
        reconciliation_status["status_message"] = "Loading invoice cache..."
        engine.load_invoice_cache()

        # Perform reconciliation
        reconciliation_status["progress"] = 80
        reconciliation_status["status_message"] = "Performing reconciliation..."
        reconciliation_results = engine.reconcile_all_pending()

        # Update status
        reconciliation_status["progress"] = 100
        reconciliation_status["status_message"] = "Reconciliation completed successfully"
        reconciliation_status["last_run"] = datetime.now().isoformat()

        # Calculate summary from results
        total = len(reconciliation_results)
        matched = sum(1 for r in reconciliation_results if r.get('match_status') == 'MATCHED')
        not_found = sum(
            1 for r in reconciliation_results if r.get('match_status') in ['NOT_FOUND', 'NOT_FOUND_IN_WARSOFT'])
        amount_mismatch = sum(1 for r in reconciliation_results if
                              r.get('match_status') in ['AMOUNT_MISMATCH', 'UNMATCHED', 'PARTIAL_MATCH'])

        reconciliation_status["results"] = {
            "total": total,
            "matched": matched,
            "not_found": not_found,
            "amount_mismatch": amount_mismatch
        }

    except Exception as e:
        reconciliation_status["status_message"] = f"Error: {str(e)}"
        reconciliation_status["progress"] = 0
    finally:
        reconciliation_status["is_running"] = False


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="localhost", port=8000, reload=True)
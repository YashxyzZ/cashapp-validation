import logging
import concurrent.futures
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import ReceiptRecord, MatchedRecord
from reports import get_receipt_rows, get_invoice_rows
from matching import match_receipt, match_invoice_item
from client import AuthError, ReportError
from cache import cache_info, clear_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(
    title="CashApp Remittance Validation",
    version="1.0.0",
    description="Validates AI-extracted remittance data against Oracle Fusion reports",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
#  POST /reports/match  — Single remittance validation
# ═══════════════════════════════════════════════════════════════

@app.post("/reports/match", response_model=MatchedRecord)
def match_remittance(record: ReceiptRecord):
    """
    Accept AI-extracted remittance JSON → validate against Fusion reports
    → return validated JSON with fusion_* fields.
    """

    # ── 1. Fetch both reports (parallel, with cache) ──
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipt_future = pool.submit(get_receipt_rows)
            invoice_future = pool.submit(get_invoice_rows)

            receipt_rows = receipt_future.result()
            invoice_rows = invoice_future.result()

    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ReportError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # ── 2. Receipt matching (Rule 2: A1 → A2 → B) ──
    receipt_result = match_receipt(record, receipt_rows)

    # ── 3. Invoice matching (Rule 3: 1a → 1b → 2 → 3) per invoice ──
    fused_invoices = [
        match_invoice_item(inv, invoice_rows, customer_name=record.customer_name)
        for inv in record.invoices
    ]

    # ── 4. Build validated output ──
    return MatchedRecord(
        customer_name=record.customer_name,
        payment_reference=record.payment_reference,
        payment_date=record.payment_date,
        total_amount=record.total_amount,
        confidence_label=record.confidence_label,
        fusion_receipt_number=receipt_result["fusion_receipt_number"],
        fusion_receipt_date=receipt_result["fusion_receipt_date"],
        fusion_customer_name=receipt_result["fusion_customer_name"],
        receipt_match_scenario=receipt_result["receipt_match_scenario"],
        invoices=fused_invoices,
    )


# ═══════════════════════════════════════════════════════════════
#  POST /reports/match/batch  — Multiple remittances at once
# ═══════════════════════════════════════════════════════════════

@app.post("/reports/match/batch", response_model=List[MatchedRecord])
def match_batch(records: List[ReceiptRecord]):
    """Validate a batch of remittances in one call."""
    results = []
    for record in records:
        try:
            result = match_remittance(record)
            results.append(result)
        except HTTPException:
            raise
    return results


# ═══════════════════════════════════════════════════════════════
#  Utility endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/cache/info")
def get_cache_info():
    """Check current cache state (age, row counts)."""
    return cache_info()


@app.post("/cache/clear")
def post_clear_cache():
    """Force-clear the in-memory cache."""
    clear_cache()
    return {"status": "cache cleared"}


@app.get("/health")
def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
#  Run with: uvicorn main:app --reload --port 8000
# ═══════════════════════════════════════════════════════════════

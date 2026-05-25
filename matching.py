import re
import logging
from typing import Optional, List, Dict

from models import ReceiptRecord, InvoiceItem, FusedInvoiceItem
from config import AMOUNT_TOLERANCE

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  DATE HELPERS
# ═══════════════════════════════════════════════════════════════

def _convert_json_date(date_str: str) -> Optional[str]:
    """Convert input date to DD-MM-YYYY for CSV comparison.

    Accepts: YYYY/MM/DD, YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY
    Returns: DD-MM-YYYY
    """
    if not date_str:
        return None
    date_str = date_str.strip()

    # YYYY/MM/DD or YYYY-MM-DD
    m = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # DD-MM-YYYY or DD/MM/YYYY  (already target format or close)
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", date_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None


def _convert_csv_date(date_str: str) -> Optional[str]:
    """Convert DD-MM-YYYY → YYYY/MM/DD for API response."""
    if not date_str:
        return None
    date_str = date_str.strip()

    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", date_str)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return None


# ═══════════════════════════════════════════════════════════════
#  AMOUNT HELPER
# ═══════════════════════════════════════════════════════════════

def _amounts_match(csv_amount_str: str, expected: Optional[float]) -> bool:
    """Check |csv_amount - expected| < 0.005 tolerance."""
    if expected is None:
        return False
    try:
        csv_val = float(str(csv_amount_str).replace(",", ""))
    except (ValueError, TypeError):
        return False
    return abs(csv_val - expected) < AMOUNT_TOLERANCE


# ═══════════════════════════════════════════════════════════════
#  RECEIPT MATCHING — Rule 2
#  Order: A(1) → A(2) → B
# ═══════════════════════════════════════════════════════════════

def _extract_receipt_fields(row: Dict) -> Dict[str, Optional[str]]:
    """Pull fusion fields from a matched receipt row."""
    return {
        "fusion_receipt_number": (row.get("RECEIPT_NUMBER") or "").strip(),
        "fusion_receipt_date": _convert_csv_date(
            (row.get("RECEIPT_DATE") or "").strip()
        ),
        "fusion_customer_name": (row.get("BILL_CUSTOMER_NAME") or "").strip(),
    }


_NO_RECEIPT_MATCH: Dict[str, Optional[str]] = {
    "fusion_receipt_number": None,
    "fusion_receipt_date": None,
    "fusion_customer_name": None,
    "receipt_match_scenario": None,
}


def match_receipt(
    record: ReceiptRecord, receipt_rows: List[Dict]
) -> Dict[str, Optional[str]]:
    """Find the single matching receipt row using cascading scenarios."""

    payment_date_csv = (
        _convert_json_date(record.payment_date) if record.payment_date else None
    )

    # ── Scenario A: payment_reference IS provided ──
    if record.payment_reference:

        # A(1): payment_reference SUBSTRING of RECEIPT_NUMBER + amount
        matches = [
            row
            for row in receipt_rows
            if record.payment_reference.lower()
            in (row.get("RECEIPT_NUMBER") or "").strip().lower()
            and _amounts_match(row.get("RECEIPT_AMOUNT", ""), record.total_amount)
        ]

        if len(matches) == 1:
            result = _extract_receipt_fields(matches[0])
            result["receipt_match_scenario"] = "A1"
            logger.info("Receipt matched via Scenario A(1)")
            return result

        # A(2): payment_date + customer_name + amount
        matches = [
            row
            for row in receipt_rows
            if (row.get("BILL_CUSTOMER_NAME") or "").strip().lower()
            == record.customer_name.strip().lower()
            and payment_date_csv
            and (row.get("RECEIPT_DATE") or "").strip() == payment_date_csv
            and _amounts_match(row.get("RECEIPT_AMOUNT", ""), record.total_amount)
        ]

        if len(matches) == 1:
            result = _extract_receipt_fields(matches[0])
            result["receipt_match_scenario"] = "A2"
            logger.info("Receipt matched via Scenario A(2)")
            return result

    # ── Scenario B: payment_reference NULL  OR  A(1)+A(2) failed ──
    if payment_date_csv:
        matches = [
            row
            for row in receipt_rows
            if (row.get("BILL_CUSTOMER_NAME") or "").strip().lower()
            == record.customer_name.strip().lower()
            and (row.get("RECEIPT_DATE") or "").strip() == payment_date_csv
            and _amounts_match(row.get("RECEIPT_AMOUNT", ""), record.total_amount)
        ]

        if len(matches) == 1:
            result = _extract_receipt_fields(matches[0])
            result["receipt_match_scenario"] = "B"
            logger.info("Receipt matched via Scenario B")
            return result

    # ── No match found across all scenarios ──
    logger.warning("No receipt match found for customer '%s'", record.customer_name)
    return dict(_NO_RECEIPT_MATCH)


# ═══════════════════════════════════════════════════════════════
#  INVOICE MATCHING — Rule 3
#  Order: Step 0 → 1a → 1b → 2 → 3   (per invoice line)
# ═══════════════════════════════════════════════════════════════

def _build_fused_invoice(
    invoice: InvoiceItem,
    row: Optional[Dict] = None,
    step: Optional[str] = None,
) -> FusedInvoiceItem:
    """Create a FusedInvoiceItem, populating fusion fields from matched row."""

    fusion_number = None
    fusion_date = None
    fusion_amount = None

    if row is not None:
        fusion_number = (row.get("TRANSACTION_NUMBER") or "").strip()
        fusion_date = _convert_csv_date(
            (row.get("TRANSACTION_DATE") or "").strip()
        )
        try:
            fusion_amount = float(
                str(row.get("TOTAL_AMOUNTS", "0")).replace(",", "")
            )
        except (ValueError, TypeError):
            fusion_amount = None

    return FusedInvoiceItem(
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        invoice_amount=invoice.invoice_amount,
        customer_invoice_number=invoice.customer_invoice_number,
        store_no=invoice.store_no,
        description=invoice.description,
        fusion_invoice_number=fusion_number,
        fusion_invoice_date=fusion_date,
        fusion_invoice_amount=fusion_amount,
        match_step=step,
    )


def match_invoice_item(
    invoice: InvoiceItem, invoice_rows: List[Dict], customer_name: str = ""
) -> FusedInvoiceItem:
    """Match a single invoice line using cascading steps."""

    inv_num = invoice.invoice_number.strip().lower() if invoice.invoice_number else None
    inv_date_csv = (
        _convert_json_date(invoice.invoice_date) if invoice.invoice_date else None
    )
    cust_name_lower = customer_name.strip().lower() if customer_name else ""

    # ── Step 0: invoice_number is NULL → match by date + amount + customer ──
    if inv_num is None:
        if inv_date_csv and invoice.invoice_amount is not None:
            matches = [
                row
                for row in invoice_rows
                if (row.get("TRANSACTION_DATE") or "").strip() == inv_date_csv
                and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
                and (row.get("BILL_CUSTOMER_NAME") or "").strip().lower() == cust_name_lower
            ]

            if len(matches) == 1:
                logger.info("Invoice matched at Step 0 (no invoice_number, date+amount+customer)")
                return _build_fused_invoice(invoice, matches[0], step="0")

        logger.warning("No invoice match — invoice_number is null")
        return _build_fused_invoice(invoice, row=None, step=None)

    # ── Step 1a: Exact match on invoice_number ONLY ──
    matches = [
        row
        for row in invoice_rows
        if (row.get("TRANSACTION_NUMBER") or "").strip().lower() == inv_num
    ]

    if len(matches) == 1:
        logger.info("Invoice '%s' matched at Step 1a", invoice.invoice_number)
        return _build_fused_invoice(invoice, matches[0], step="1a")

    # ── Step 1b: invoice_number + invoice_date + invoice_amount ──
    if inv_date_csv:
        matches = [
            row
            for row in invoice_rows
            if (row.get("TRANSACTION_NUMBER") or "").strip().lower() == inv_num
            and (row.get("TRANSACTION_DATE") or "").strip() == inv_date_csv
            and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
        ]

        if len(matches) == 1:
            logger.info("Invoice '%s' matched at Step 1b", invoice.invoice_number)
            return _build_fused_invoice(invoice, matches[0], step="1b")

    # ── Step 2: customer_invoice_number + date + amount ──
    if invoice.customer_invoice_number and inv_date_csv:
        cust_inv_num = invoice.customer_invoice_number.strip().lower()
        matches = [
            row
            for row in invoice_rows
            if (row.get("TRANSACTION_NUMBER") or "").strip().lower() == cust_inv_num
            and (row.get("TRANSACTION_DATE") or "").strip() == inv_date_csv
            and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
        ]

        if len(matches) == 1:
            logger.info("Invoice '%s' matched at Step 2", invoice.invoice_number)
            return _build_fused_invoice(invoice, matches[0], step="2")

    # ── Step 3: Substring fallback + date + amount ──
    if inv_date_csv:
        matches = [
            row
            for row in invoice_rows
            if inv_num in (row.get("TRANSACTION_NUMBER") or "").strip().lower()
            and (row.get("TRANSACTION_DATE") or "").strip() == inv_date_csv
            and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
        ]

        if len(matches) == 1:
            logger.info("Invoice '%s' matched at Step 3 (substring)", invoice.invoice_number)
            return _build_fused_invoice(invoice, matches[0], step="3")

    # ── No match found ──
    logger.warning("No invoice match found for '%s'", invoice.invoice_number)
    return _build_fused_invoice(invoice, row=None, step=None)

import re
import logging
from typing import Optional, List, Dict

from models import ReceiptRecord, InvoiceItem, FusedInvoiceItem
from config import AMOUNT_TOLERANCE

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


# ═══════════════════════════════════════════════════════════════
#  DATE HELPERS
# ═══════════════════════════════════════════════════════════════

def _normalize_date(date_str: str) -> Optional[str]:
    """Normalize any date format to YYYY-MM-DD for comparison.

    Handles: YYYY-MM-DD, YYYY/MM/DD, DD-MM-YYYY, DD/MM/YYYY,
             DD-Mon-YYYY, DD-MON-YYYY, MM/DD/YYYY
    """
    if not date_str:
        return None
    date_str = date_str.strip()

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})$", date_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # DD-MM-YYYY or DD/MM/YYYY
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # DD-Mon-YYYY or DD-MON-YYYY (e.g. 15-May-2026, 15-MAY-2026)
    m = re.match(r"^(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{4})$", date_str)
    if m:
        mon = MONTH_MAP.get(m.group(2).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{int(m.group(1)):02d}"

    # DD-Mon-YY (e.g. 15-May-26)
    m = re.match(r"^(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{2})$", date_str)
    if m:
        mon = MONTH_MAP.get(m.group(2).lower())
        if mon:
            year = int(m.group(3))
            full_year = 2000 + year if year < 100 else year
            return f"{full_year}-{mon}-{int(m.group(1)):02d}"

    return None


def _dates_match(date_a: Optional[str], date_b: Optional[str]) -> bool:
    if not date_a or not date_b:
        return False
    norm_a = _normalize_date(date_a)
    norm_b = _normalize_date(date_b)
    if norm_a and norm_b:
        return norm_a == norm_b
    return False


def _format_date_for_output(date_str: str) -> Optional[str]:
    """Convert any date format → YYYY/MM/DD for API response."""
    norm = _normalize_date(date_str)
    if norm:
        return norm.replace("-", "/")
    return None


# ═══════════════════════════════════════════════════════════════
#  AMOUNT HELPER
# ═══════════════════════════════════════════════════════════════

def _amounts_match(csv_amount_str: str, expected: Optional[float]) -> bool:
    """Check |abs(csv_amount) - abs(expected)| < tolerance.
    Uses absolute values because Oracle stores credit memos as negative.
    """
    if expected is None:
        return False
    try:
        csv_val = float(str(csv_amount_str).replace(",", ""))
    except (ValueError, TypeError):
        return False
    return abs(abs(csv_val) - abs(expected)) < AMOUNT_TOLERANCE


# ═══════════════════════════════════════════════════════════════
#  RECEIPT MATCHING — Rule 2
#  Order: A(1) → A(2) → B
# ═══════════════════════════════════════════════════════════════

def _extract_receipt_fields(row: Dict) -> Dict[str, Optional[str]]:
    """Pull fusion fields from a matched receipt row."""
    return {
        "fusion_receipt_number": (row.get("RECEIPT_NUMBER") or "").strip(),
        "fusion_receipt_date": _format_date_for_output(
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

    logger.info(
        "Receipt matching: customer='%s', ref='%s', date='%s', amount=%s, rows=%d",
        record.customer_name, record.payment_reference,
        record.payment_date, record.total_amount, len(receipt_rows),
    )

    cust_name_lower = record.customer_name.strip().lower() if record.customer_name else ""

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

        logger.info("A1: %d matches (ref substring + amount)", len(matches))
        if len(matches) == 1:
            result = _extract_receipt_fields(matches[0])
            result["receipt_match_scenario"] = "A1"
            return result

        # A(2): payment_date + customer_name + amount (requires customer_name)
        if cust_name_lower:
            matches = [
                row
                for row in receipt_rows
                if (row.get("BILL_CUSTOMER_NAME") or "").strip().lower()
                == cust_name_lower
                and _dates_match(record.payment_date, row.get("RECEIPT_DATE", ""))
                and _amounts_match(row.get("RECEIPT_AMOUNT", ""), record.total_amount)
            ]

            logger.info("A2: %d matches (customer + date + amount)", len(matches))
            if len(matches) == 1:
                result = _extract_receipt_fields(matches[0])
                result["receipt_match_scenario"] = "A2"
                return result
        else:
            logger.info("A2: skipped (no customer_name)")

    # ── Scenario B: payment_reference NULL  OR  A(1)+A(2) failed ──
    if cust_name_lower:
        matches = [
            row
            for row in receipt_rows
            if (row.get("BILL_CUSTOMER_NAME") or "").strip().lower()
            == cust_name_lower
            and _dates_match(record.payment_date, row.get("RECEIPT_DATE", ""))
            and _amounts_match(row.get("RECEIPT_AMOUNT", ""), record.total_amount)
        ]

        logger.info("B: %d matches (customer + date + amount)", len(matches))
        if len(matches) == 1:
            result = _extract_receipt_fields(matches[0])
            result["receipt_match_scenario"] = "B"
            return result
    else:
        logger.info("B: skipped (no customer_name)")

    # ── No match found across all scenarios ──
    if receipt_rows:
        sample = receipt_rows[0]
        logger.warning(
            "No receipt match. Sample row keys: %s, RECEIPT_DATE='%s', BILL_CUSTOMER_NAME='%s'",
            list(sample.keys()),
            sample.get("RECEIPT_DATE", "<MISSING>"),
            sample.get("BILL_CUSTOMER_NAME", "<MISSING>"),
        )
    else:
        logger.warning("No receipt match — Oracle returned 0 receipt rows")
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
        fusion_date = _format_date_for_output(
            (row.get("TRANSACTION_DATE") or "").strip()
        )
        try:
            fusion_amount = float(
                str(row.get("TOTAL_AMOUNTS", "0")).replace(",", "")
            )
        except (ValueError, TypeError):
            fusion_amount = None

    return FusedInvoiceItem(
        Line_ID=invoice.Line_ID,
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
    cust_name_lower = customer_name.strip().lower() if customer_name else ""

    logger.info(
        "Invoice matching: num='%s', date='%s', amount=%s, rows=%d",
        invoice.invoice_number, invoice.invoice_date,
        invoice.invoice_amount, len(invoice_rows),
    )

    # ── Step 0: invoice_number is NULL → match by date + amount + customer ──
    if inv_num is None:
        if cust_name_lower and invoice.invoice_date and invoice.invoice_amount is not None:
            matches = [
                row
                for row in invoice_rows
                if _dates_match(invoice.invoice_date, row.get("TRANSACTION_DATE", ""))
                and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
                and (row.get("BILL_CUSTOMER_NAME") or "").strip().lower() == cust_name_lower
            ]

            if len(matches) == 1:
                logger.info("Invoice matched at Step 0 (date+amount+customer)")
                return _build_fused_invoice(invoice, matches[0], step="0")

        logger.warning("No invoice match — invoice_number is null")
        return _build_fused_invoice(invoice, row=None, step=None)

    # ── Step 1a: Exact match on invoice_number ONLY ──
    matches = [
        row
        for row in invoice_rows
        if (row.get("TRANSACTION_NUMBER") or "").strip().lower() == inv_num
    ]

    logger.info("Step 1a: %d matches (exact invoice_number)", len(matches))
    if len(matches) == 1:
        return _build_fused_invoice(invoice, matches[0], step="1a")

    # ── Step 1a-sub: Substring match on invoice_number + amount ──
    # Handles Oracle prefixed numbers like NF-CM-225719630729
    matches = [
        row
        for row in invoice_rows
        if inv_num in (row.get("TRANSACTION_NUMBER") or "").strip().lower()
        and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
    ]

    logger.info("Step 1a-sub: %d matches (substring + amount)", len(matches))
    if len(matches) == 1:
        return _build_fused_invoice(invoice, matches[0], step="1a-sub")

    # ── Step 1b: invoice_number + invoice_date + invoice_amount ──
    if invoice.invoice_date:
        matches = [
            row
            for row in invoice_rows
            if (row.get("TRANSACTION_NUMBER") or "").strip().lower() == inv_num
            and _dates_match(invoice.invoice_date, row.get("TRANSACTION_DATE", ""))
            and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
        ]

        logger.info("Step 1b: %d matches (num + date + amount)", len(matches))
        if len(matches) == 1:
            return _build_fused_invoice(invoice, matches[0], step="1b")

    # ── Step 2: customer_invoice_number + date + amount ──
    if invoice.customer_invoice_number and invoice.invoice_date:
        cust_inv_num = invoice.customer_invoice_number.strip().lower()
        matches = [
            row
            for row in invoice_rows
            if (row.get("TRANSACTION_NUMBER") or "").strip().lower() == cust_inv_num
            and _dates_match(invoice.invoice_date, row.get("TRANSACTION_DATE", ""))
            and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
        ]

        logger.info("Step 2: %d matches (cust_inv_num + date + amount)", len(matches))
        if len(matches) == 1:
            return _build_fused_invoice(invoice, matches[0], step="2")

    # ── Step 3: Substring fallback + date + amount ──
    if invoice.invoice_date:
        matches = [
            row
            for row in invoice_rows
            if inv_num in (row.get("TRANSACTION_NUMBER") or "").strip().lower()
            and _dates_match(invoice.invoice_date, row.get("TRANSACTION_DATE", ""))
            and _amounts_match(row.get("TOTAL_AMOUNTS", ""), invoice.invoice_amount)
        ]

        logger.info("Step 3: %d matches (substring + date + amount)", len(matches))
        if len(matches) == 1:
            return _build_fused_invoice(invoice, matches[0], step="3")

    # ── No match found ──
    if invoice_rows:
        sample = invoice_rows[0]
        logger.warning(
            "No invoice match for '%s'. Sample row: TRANSACTION_NUMBER='%s', TRANSACTION_DATE='%s'",
            invoice.invoice_number,
            sample.get("TRANSACTION_NUMBER", "<MISSING>"),
            sample.get("TRANSACTION_DATE", "<MISSING>"),
        )
    else:
        logger.warning("No invoice match — Oracle returned 0 invoice rows")
    return _build_fused_invoice(invoice, row=None, step=None)

import csv
import io
import os
import logging
from typing import Optional, List, Dict

from cache import get_cached, set_cache
from client import fetch_report_from_oracle
from config import (
    RECEIPT_REPORT_PATH,
    INVOICE_REPORT_PATH,
    USE_LOCAL_CSV,
    LOCAL_CSV_DIR,
)

logger = logging.getLogger(__name__)


def _normalize_key(key: str) -> str:
    return key.strip().upper().replace(" ", "_")


def _normalize_rows(rows: List[Dict]) -> List[Dict]:
    normalized = [{_normalize_key(k): v for k, v in row.items()} for row in rows]
    if normalized:
        logger.info("CSV columns (normalized): %s", list(normalized[0].keys()))
        logger.info("CSV sample row: %s", normalized[0])
    else:
        logger.warning("CSV returned 0 rows")
    return normalized


def _parse_csv_bytes(csv_bytes: bytes) -> List[Dict]:
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    logger.info("Parsed %d rows from Oracle CSV", len(rows))
    return _normalize_rows(rows)


def _parse_csv_file(file_path: str) -> List[Dict]:
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    logger.info("Parsed %d rows from local CSV: %s", len(rows), file_path)
    return _normalize_rows(rows)


def _find_local_csv(keyword: str) -> Optional[str]:
    """Find a CSV in LOCAL_CSV_DIR whose name contains the keyword."""
    if not os.path.isdir(LOCAL_CSV_DIR):
        return None
    for fname in os.listdir(LOCAL_CSV_DIR):
        if fname.lower().endswith(".csv") and keyword.lower() in fname.lower():
            return os.path.join(LOCAL_CSV_DIR, fname)
    return None


def get_report_rows(
    report_path: str,
    report_key: str,
    customer_name: str = None,
    from_date: str = None,
    to_date: str = None,
) -> List[Dict]:
    """Fetch report rows — from cache, local CSV, or Oracle BIP."""

    has_filters = any([customer_name, from_date, to_date])

    # ── Filtered requests always bypass cache ──
    if not has_filters:
        cached = get_cached(report_key)
        if cached is not None:
            return cached

    # ── Local CSV mode (for testing) ──
    if USE_LOCAL_CSV:
        csv_path = _find_local_csv(report_key)
        if csv_path:
            logger.info("Loading local CSV: %s", csv_path)
            rows = _parse_csv_file(csv_path)
        else:
            raise FileNotFoundError(
                f"No local CSV found for '{report_key}' in {LOCAL_CSV_DIR}"
            )
    else:
        # ── Call Oracle BIP ──
        csv_bytes = fetch_report_from_oracle(
            report_path=report_path,
            customer_name=customer_name,
            from_date=from_date,
            to_date=to_date,
        )
        rows = _parse_csv_bytes(csv_bytes)

    # ── Cache unfiltered results ──
    if not has_filters:
        set_cache(report_key, rows)

    return rows


def get_receipt_rows(
    customer_name: str = None,
    from_date: str = None,
    to_date: str = None,
) -> List[Dict]:
    """Fetch receipt report rows."""
    return get_report_rows(
        RECEIPT_REPORT_PATH, "receipt", customer_name, from_date, to_date
    )


def get_invoice_rows(
    customer_name: str = None,
    from_date: str = None,
    to_date: str = None,
) -> List[Dict]:
    """Fetch invoice report rows."""
    return get_report_rows(
        INVOICE_REPORT_PATH, "invoice", customer_name, from_date, to_date
    )

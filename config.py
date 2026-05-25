import os
from dotenv import load_dotenv

load_dotenv()

# ── Oracle BIP Connection ──
ORACLE_BIP_URL = os.getenv(
    "ORACLE_BIP_URL",
    "https://your-instance.fa.us6.oraclecloud.com/xmlpserver/services/ExternalReportWSSService",
)
ORACLE_USERNAME = os.getenv("ORACLE_USERNAME", "")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")

# ── Report Paths in Oracle BIP ──
RECEIPT_REPORT_PATH = os.getenv(
    "RECEIPT_REPORT_PATH",
    "/Custom/Financials/Receipt_Details_Report.xdo",
)
INVOICE_REPORT_PATH = os.getenv(
    "INVOICE_REPORT_PATH",
    "/Custom/Financials/Invoice_Details_Report.xdo",
)

# ── Cache TTL (seconds) ──
# 5 minutes = 300 seconds
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))

# ── Matching ──
AMOUNT_TOLERANCE = 0.005

# ── Local CSV mode (for testing without Oracle) ──
# Set to "true" to load CSVs from LOCAL_CSV_DIR instead of calling Oracle
USE_LOCAL_CSV = os.getenv("USE_LOCAL_CSV", "false").lower() == "true"
LOCAL_CSV_DIR = os.getenv("LOCAL_CSV_DIR", "./report")

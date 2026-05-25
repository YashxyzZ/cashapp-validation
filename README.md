# CashApp Remittance Validation API

Validates AI-extracted remittance data against Oracle Fusion reports. Takes AI-extracted payment and invoice data as input, matches it against Fusion Receipt and Invoice reports, and returns validated JSON with Fusion-verified fields.

## How It Works

```
Paper Check (PDF)
      |
      v
AI Extraction (OCR / LLM)
      |
      v
POST /reports/match  <-- INPUT: AI-extracted JSON
      |
      |--- Fetch Receipt CSV (cache or Oracle BIP)
      |--- Fetch Invoice CSV  (cache or Oracle BIP)
      |
      |--- Receipt Matching:  A(1) --> A(2) --> B
      |--- Invoice Matching:  1a --> 1b --> 2 --> 3
      |
      v
Validated JSON  <-- OUTPUT: Original fields + fusion_* fields
```

## Project Structure

```
VALIDATION 3/
|-- .env                 # Configuration (Oracle credentials, cache TTL)
|-- config.py            # Reads .env, exposes typed settings
|-- models.py            # Pydantic models (input/output contracts)
|-- cache.py             # In-memory cache (Python dict, 5-min TTL)
|-- client.py            # Oracle BIP SOAP client
|-- matching.py          # Core validation engine (receipt + invoice matching)
|-- reports.py           # Report fetching orchestrator (cache + Oracle)
|-- main.py              # FastAPI app with endpoints
|-- requirements.txt     # Python dependencies
|-- VALIDATION_RULES.md  # Detailed matching rules documentation
|-- report/              # Local CSV files for testing
```

## Setup

### 1. Install dependencies

```bash
pip install fastapi uvicorn pydantic requests python-dotenv
```

### 2. Configure .env

```env
# Oracle BIP Connection
ORACLE_BIP_URL=https://your-instance.oraclecloud.com/xmlpserver/services/ExternalReportWSSService
ORACLE_USERNAME=your_username
ORACLE_PASSWORD=your_password

# Report Paths
RECEIPT_REPORT_PATH=/Custom/Financials/Receipt_Details_Report.xdo
INVOICE_REPORT_PATH=/Custom/Financials/Invoice_Details_Report.xdo

# Cache (5 minutes)
CACHE_TTL_SECONDS=300

# Local CSV mode (for testing without Oracle)
USE_LOCAL_CSV=true
LOCAL_CSV_DIR=./report
```

### 3. Run the server

```bash
uvicorn main:app --reload --port 8000
```

### 4. Open Swagger UI

```
http://localhost:8000/docs
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/reports/match` | POST | Validate single remittance |
| `/reports/match/batch` | POST | Validate multiple remittances |
| `/cache/info` | GET | Check cache age and row counts |
| `/cache/clear` | POST | Force-clear the cache |
| `/health` | GET | Health check |

## Sample Request

```json
POST /reports/match

{
  "customer_name": "Canada Bread Co",
  "payment_reference": "JV0899",
  "payment_date": "2024/01/15",
  "total_amount": 5000.00,
  "invoices": [
    {
      "invoice_number": "1262018",
      "invoice_date": "2024/01/10",
      "invoice_amount": 2500.00
    }
  ]
}
```

## Sample Response

```json
{
  "customer_name": "Canada Bread Co",
  "payment_reference": "JV0899",
  "payment_date": "2024/01/15",
  "total_amount": 5000.00,
  "fusion_receipt_number": "18-19/Jan/JV0899",
  "fusion_receipt_date": "2024/01/15",
  "fusion_customer_name": "Canada Bread Co Ltd",
  "receipt_match_scenario": "A1",
  "invoices": [
    {
      "invoice_number": "1262018",
      "invoice_date": "2024/01/10",
      "invoice_amount": 2500.00,
      "fusion_invoice_number": "1262018",
      "fusion_invoice_date": "2024/01/10",
      "fusion_invoice_amount": 2500.00,
      "match_step": "1a"
    }
  ]
}
```

If no match is found, `fusion_*` fields return `null`.

## Matching Logic Summary

### Receipt Matching (Rule 2)

Tries 3 scenarios in order. First match wins:

| Scenario | Search Criteria | When |
|----------|----------------|------|
| A(1) | `payment_reference` SUBSTRING of `RECEIPT_NUMBER` + amount match | payment_reference provided |
| A(2) | `customer_name` + `payment_date` + `total_amount` | A(1) failed |
| B | `customer_name` + `payment_date` + `total_amount` | A(1)+A(2) failed or no payment_reference |

### Invoice Matching (Rule 3)

Tries 4 steps per invoice. First match wins:

| Step | Search Criteria | When |
|------|----------------|------|
| 1a | `invoice_number` exact match on `TRANSACTION_NUMBER` | Always |
| 1b | `invoice_number` + `invoice_date` + `invoice_amount` | 1a found 0 or 2+ |
| 2 | `customer_invoice_number` + `invoice_date` + `invoice_amount` | 1b failed |
| 3 | `invoice_number` SUBSTRING of `TRANSACTION_NUMBER` + date + amount | Steps 1-2 failed |

All matches require **exactly 1 result**. 0 or 2+ results = `null`.

Amount tolerance: **+/-0.005** (handles float rounding).

## Caching

- Reports are cached **in-memory** (Python dict) for **5 minutes**
- Filtered requests (with customer_name/dates) bypass cache
- No external storage (no OCI, no Redis, no database)
- Cache size: ~24 MB for both reports (~35,000 rows)
- Check cache status: `GET /cache/info`
- Clear cache manually: `POST /cache/clear`

## Configuration

All settings are in `.env`. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `USE_LOCAL_CSV` | `true` | Use local CSVs instead of Oracle |
| `CACHE_TTL_SECONDS` | `300` | Cache lifetime (5 minutes) |
| `AMOUNT_TOLERANCE` | `0.005` | Amount match tolerance |

## Testing Modes

### Local CSV mode (development)

```env
USE_LOCAL_CSV=true
LOCAL_CSV_DIR=./report
```

Reads from local CSV files in `report/` folder. No Oracle connection needed.

### Oracle BIP mode (production)

```env
USE_LOCAL_CSV=false
ORACLE_BIP_URL=https://...
ORACLE_USERNAME=...
ORACLE_PASSWORD=...
```

Calls Oracle BIP via SOAP to fetch fresh reports.

# CashApp Remittance Validation Rules

## 1. Input Validation (`models.py`)

### InvoiceItem

| Field                       | Required | Rules                                                                        |
| --------------------------- | -------- | ---------------------------------------------------------------------------- |
| `invoice_number`          | No       | Empty string auto-converts to `null`. If null, Step 0 is used for matching |
| `invoice_date`            | No       | Empty string auto-converts to `null`                                       |
| `invoice_amount`          | No       | Float value                                                                  |
| `customer_invoice_number` | No       | Empty string auto-converts to `null`                                       |
| `store_no`                | No       | Empty string auto-converts to `null`                                       |
| `description`             | No       | Empty string auto-converts to `null`                                       |

### ReceiptRecord

| Field                 | Required      | Rules                                  |
| --------------------- | ------------- | -------------------------------------- |
| `customer_name`     | **YES** | Cannot be empty string or whitespace   |
| `payment_reference` | No            | Empty string auto-converts to `null` |
| `payment_date`      | No            | Empty string auto-converts to `null` |
| `total_amount`      | No            | Float value                            |
| `confidence_label`  | No            | Empty string auto-converts to `null` |
| `invoices`          | No            | List of `InvoiceItem` objects        |

---

## 2. Cache Decision (`cache.py`) — Rule 1

Decides whether to fetch fresh data from Oracle or use cached data from memory.

```
Request comes in
     |
     v
Has filters (customer_name/from_date/to_date)?
     |
     +-- YES --> Skip cache entirely --> Call Oracle directly
     |
     +-- NO  --> Check in-memory cache (_cache dict)
                  |
                  +-- No entry found
                  |   --> Cache MISS --> Fetch from Oracle
                  |
                  +-- Entry found but age >= 5 minutes
                  |   --> STALE --> Delete old entry --> Fetch from Oracle
                  |
                  +-- Entry found and age < 5 minutes
                      --> Cache HIT --> Use cached data (instant)
```

### Cache Rules

- **Filtered requests** (with customer_name/from_date/to_date) are **never cached**
- **Unfiltered requests** are cached for **5 minutes** (300 seconds)
- Age is calculated using `time.time()` at storage vs current time
- After a fresh Oracle fetch (unfiltered): save rows + timestamp to `_cache` dict
- Old data is automatically overwritten when new data is stored

---

## 3. SOAP Parameters (`client.py`)

When calling Oracle BIP, these filter parameters are embedded in the SOAP envelope:

| Parameter           | Source                                         |
| ------------------- | ---------------------------------------------- |
| `P_CUSTOMER_NAME` | From request's `customer_name` (if provided) |
| `P_FROM_DATE`     | From request's `from_date` (if provided)     |
| `P_TO_DATE`       | From request's `to_date` (if provided)       |

If none are provided, Oracle returns the full unfiltered report.

### Error Handling Order

| Condition                                                                | Error Type                      |
| ------------------------------------------------------------------------ | ------------------------------- |
| HTTP 401                                                                 | `AuthError` (bad credentials) |
| HTTP non-200                                                             | `ReportError`                 |
| SOAP fault containing "Authentication" or "Invalid username or password" | `AuthError`                   |
| Any other SOAP fault                                                     | `ReportError`                 |
| Missing `<reportBytes>` in response                                    | `ReportError`                 |
| Malformed base64 in `<reportBytes>`                                    | `ReportError`                 |

---

## 4. Receipt Matching (`matching.py`) — Rule 2

**Goal:** Find `fusion_receipt_number`, `fusion_receipt_date`, `fusion_customer_name`

**Order:** Receipt matching runs FIRST, then invoice matching.

### Scenario A(1) — Payment reference substring + amount

**Condition:** `payment_reference` IS provided

```
Search Receipt Details CSV for rows where:
    input's payment_reference is a SUBSTRING of row's RECEIPT_NUMBER
        (case-insensitive)
    AND
    row's RECEIPT_AMOUNT matches input's total_amount
        (within +/-0.005 tolerance)
```

**Example:**

```
Input payment_reference: "JV0899"
CSV RECEIPT_NUMBER:      "18-19/Jan/JV0899"
--> MATCH (JV0899 is found inside 18-19/Jan/JV0899)
```

- **1 match** --> DONE. Do NOT proceed to A(2) or B.
- **0 or 2+ matches** --> Proceed to Scenario A(2)

### Scenario A(2) — Date + customer name + amount

**Condition:** `payment_reference` IS provided but A(1) failed

```
Search Receipt Details CSV for rows where:
    BILL_CUSTOMER_NAME == customer_name (case-insensitive, exact)
    AND RECEIPT_DATE == payment_date (converted to DD-MM-YYYY)
    AND RECEIPT_AMOUNT matches total_amount (within +/-0.005)
```

- **1 match** --> DONE
- **0 or 2+ matches** --> Proceed to Scenario B

### Scenario B — Customer name + date + amount (fallback)

**Condition:** `payment_reference` is NULL, OR Scenarios A(1) and A(2) both failed

```
Search Receipt Details CSV for rows where:
    BILL_CUSTOMER_NAME == customer_name (case-insensitive, exact)
    AND payment_date IS NOT null (required for this scenario)
    AND RECEIPT_DATE == payment_date (converted to DD-MM-YYYY)
    AND RECEIPT_AMOUNT matches total_amount (within +/-0.005)
```

- **1 match** --> DONE
- **0 or 2+ matches** --> All fusion receipt fields = `null`

### Result

| Outcome         | fusion_receipt_number    | fusion_receipt_date                    | fusion_customer_name         |
| --------------- | ------------------------ | -------------------------------------- | ---------------------------- |
| Exactly 1 match | Row's `RECEIPT_NUMBER` | Row's `RECEIPT_DATE` (as YYYY/MM/DD) | Row's `BILL_CUSTOMER_NAME` |
| 0 or 2+ matches | `null`                 | `null`                               | `null`                     |

---

## 5. Invoice Matching (`matching.py`) — Rule 3

**Goal:** Find `fusion_invoice_number`, `fusion_invoice_date`, `fusion_invoice_amount`

Runs for **each invoice line independently**. Steps are tried in order — stops at first success.

### Step 0 — No invoice_number (date + amount fallback)

**Condition:** `invoice_number` is NULL (empty or not provided)

```
TRANSACTION_DATE == invoice_date (converted to DD-MM-YYYY)
AND TOTAL_AMOUNTS == invoice_amount (within +/-0.005)
AND BILL_CUSTOMER_NAME == customer_name
```

- **1 match** --> Populate fusion fields --> **STOP** (do NOT proceed to Steps 1-3)
- **0 or 2+** --> ALL fusion fields = `null` (Steps 1-3 are skipped since there's no invoice_number)

*Why Step 0 exists:* AI extraction sometimes fails to read the invoice number from the PDF. Rather than rejecting the invoice entirely, we try to match by date + amount. If that combo is unique in the report, we have a confident match.

### Step 1a — Exact match on invoice_number only

```
TRANSACTION_NUMBER == invoice_number (case-insensitive, exact)
```

- **1 match** --> Populate fusion fields --> **STOP**
- **0 or 2+** --> Go to Step 1b (only if `invoice_date` is available)

*Why 1a exists:* If the invoice number is unique across the entire report, date and amount aren't needed to disambiguate.

### Step 1b — Exact match on invoice_number + date + amount

**Condition:** Step 1a found 0 or 2+ matches AND `invoice_date` is provided

```
TRANSACTION_NUMBER == invoice_number (case-insensitive, exact)
AND TRANSACTION_DATE == invoice_date (converted to DD-MM-YYYY)
AND TOTAL_AMOUNTS == invoice_amount (within +/-0.005)
```

- **1 match** --> Populate fusion fields --> **STOP**
- **0 or 2+** --> Go to Step 2

### Step 2 — Match by customer_invoice_number + date + amount

**Condition:** Step 1 failed AND `customer_invoice_number` is provided AND `invoice_date` is provided

```
TRANSACTION_NUMBER == customer_invoice_number (case-insensitive, exact)
AND TRANSACTION_DATE == invoice_date (converted to DD-MM-YYYY)
AND TOTAL_AMOUNTS == invoice_amount (within +/-0.005)
```

- **1 match** --> Populate fusion fields --> **STOP**
- **0 or 2+** --> Go to Step 3

### Step 3 — Substring fallback

**Condition:** Steps 1-2 all failed AND `invoice_number` is provided AND `invoice_date` is provided

```
input's invoice_number appears INSIDE row's TRANSACTION_NUMBER
    (case-insensitive, substring)
AND TRANSACTION_DATE == invoice_date (converted to DD-MM-YYYY)
AND TOTAL_AMOUNTS == invoice_amount (within +/-0.005)
```

**Examples:**

```
Input: "25908454"    Row: "126125908454"   --> MATCH (substring found)
Input: "6153004273"  Row: "6153004273089"  --> MATCH (substring found)
Input: "25908454"    Row: "999999999"      --> NO MATCH
```

- **1 match** --> Populate fusion fields --> **STOP**
- **0 or 2+** --> ALL fusion fields = `null`

### When a match IS found (any step)

| Output Field              | Value                                                |
| ------------------------- | ---------------------------------------------------- |
| `fusion_invoice_number` | Row's `TRANSACTION_NUMBER`                         |
| `fusion_invoice_date`   | Row's `TRANSACTION_DATE` (converted to YYYY/MM/DD) |
| `fusion_invoice_amount` | Row's `TOTAL_AMOUNTS` (parsed as float)            |
| `match_step`            | Which step matched:`1a`, `1b`, `2`, or `3`   |

---

## 6. Amount Matching Logic

Used by both receipt and invoice matching.

```
If expected amount is null --> return False (no match possible)

Parse CSV value: remove commas, convert to float
Compare: |parsed - expected| < 0.005
```

| CSV Value      | Input Value | Difference | Match? |
| -------------- | ----------- | ---------- | ------ |
| `"5,000.00"` | `5000.0`  | `0.000`  | YES    |
| `"4999.998"` | `5000.0`  | `0.002`  | YES    |
| `"4999.99"`  | `5000.0`  | `0.010`  | NO     |

---

## 7. Date Conversion Logic

Two conversions used throughout:

### JSON Input --> CSV Comparison (`_convert_json_date`)

| Input Format   | Output         |
| -------------- | -------------- |
| `YYYY/MM/DD` | `DD-MM-YYYY` |
| `YYYY-MM-DD` | `DD-MM-YYYY` |
| `DD-MM-YYYY` | `DD-MM-YYYY` |
| `DD/MM/YYYY` | `DD-MM-YYYY` |

### CSV --> API Response (`_convert_csv_date`)

| Input Format   | Output         |
| -------------- | -------------- |
| `DD-MM-YYYY` | `YYYY/MM/DD` |

---

## 8. Complete Flow for POST /reports/match

```
1. Input: ReceiptRecord (customer_name, payment_reference, invoices[], etc.)

2. Fetch BOTH reports in parallel (in-memory cache --> Oracle fallback)
   - Receipt Details CSV
   - Invoice Details CSV

3. Parse both CSVs into rows (list of dicts)

4. Run receipt matching (A1 --> A2 --> B)
   --> Returns fusion_receipt_number, fusion_receipt_date, fusion_customer_name

5. For EACH invoice in record.invoices:
   Run invoice matching (1a --> 1b --> 2 --> 3)
   --> Returns fusion_invoice_number, fusion_invoice_date, fusion_invoice_amount

6. Build MatchedRecord combining:
   - All original input fields (passed through)
   - Receipt fusion fields (from step 4)
   - Invoice fusion fields for each invoice (from step 5)

7. Return as JSON
```

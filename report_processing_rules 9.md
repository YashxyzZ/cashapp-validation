## GOLDEN RULE (applies to every match check in this document)

```
match_count == 1   →  populate the output fields
match_count == 0   →  set ALL output fields to null
match_count >= 2   →  set ALL output fields to null
NEVER guess. NEVER assume. NEVER infer a match.
```

---

## DEFINITIONS FOR CODE

**"null or empty" check** — a value is considered null/empty if ANY of these are true:
```python
value is None
pd.isna(value)            # catches NaN, NaT, float('nan')
str(value).strip() == ""
```

**Amount match — exact equality (applies everywhere):**
```python
float(report_amount) == float(input_amount)
```



---

## CRITICAL DATA NOTES  (read before writing any code)

### ⚠️  DOCUMENT_NUMBER is stored as float64 in the Invoice Report
Raw pandas value: `31012324100034.0`
`str()` gives `"31012324100034.0"` — **WRONG, will never match.**
Correct conversion: `str(int(row['DOCUMENT_NUMBER']))` → `"31012324100034"`
Always apply this before any string comparison on `DOCUMENT_NUMBER`.

### ⚠️  TRANSACTION_NUMBER has 246 values that appear in 2+ rows
Short values like `"1"` (28 rows), `"2001"` (13 rows) are common.
Step 1a returning 2+ matches is normal — Step 1b (adding date) resolves it.

### ⚠️  RECEIPT_NUMBER has 85 values that appear in 2+ rows
Values like `"Mar'21"` (24 rows), `"Jan'21"` (21 rows) repeat across customers.
Scenario A1 returning 2+ matches is normal — A2 (adding date + name) resolves it.

### ⚠️  A2 only helps when A1 returns 2+ matches — not when A1 returns 0
If A1 = 0 matches → A2 will also = 0 (stricter criteria cannot find rows A1missed).
If A1 = 2+ matches → A2 narrows them down.

### ⚠️  Step 4 trigger condition — confirm with document owner
The original text says "IF INVOICE NUMBER IS NULL".
This document interprets that as: **all prior steps (1a → 1b → 2 → 3) failed to find exactly 1 match.**
If it instead means "only run Step 4 when the INPUT `invoice_number` field is null/empty", update the entry-point logic below.

### ℹ️  All amount comparisons use exact match
`float(report_amount) == float(input_amount)` — strict equality everywhere. No tolerance.

### ℹ️  Step 4 selectivity: 30% of customer+date+amount combos are not unique
5,434 of 18,190 unique (BILL_CUSTOMER_NAME + TRANSACTION_DATE + TOTAL_AMOUNTS) combinations appear in 2+ rows.
Step 4 will frequently return 2+ matches and output null — this is expected.

### ℹ️  DOCUMENT_NUMBER is null in 72% of Invoice Report rows (19,268 / 26,576)
Step 2 will return 0 matches for most records. Normal — proceed to Step 3.

### ℹ️  No nulls in RECEIPT_AMOUNT, TOTAL_AMOUNTS, RECEIPT_DATE, TRANSACTION_DATE, or BILL_CUSTOMER_NAME

---

## ACTUAL REPORT SCHEMAS

### Invoice Details Report  (26,576 rows)

| Column | pandas dtype | Notes |
|---|---|---|
| `TRANSACTION_NUMBER` | str | Always `.strip().lower()` before matching |
| `TRANSACTION_DATE` | str | `DD-MM-YYYY`. No nulls. |
| `TOTAL_AMOUNTS` | float64 | No nulls. Exact match: `float(TOTAL_AMOUNTS) == float(input)`. |
| `DOCUMENT_NUMBER` | **float64** | 72% null. Convert via `str(int(v))` before string matching. |
| `BILL_CUSTOMER_NAME` | str | No nulls. Always `.strip().lower()` before matching. |

### Receipt Details Report  (8,914 rows)

| Column | pandas dtype | Notes |
|---|---|---|
| `RECEIPT_NUMBER` | str | Can be numeric (`3003`) or alphanumeric (`3060-A`). Always treat as string. |
| `RECEIPT_DATE` | str | `DD-MM-YYYY`. No nulls. |
| `RECEIPT_AMOUNT` | float64 | No nulls. Exact match: `float(RECEIPT_AMOUNT) == float(input)`. |
| `BILL_CUSTOMER_NAME` | str | No nulls. Always `.strip().lower()` before matching. |

---

## RULE 1 — Should the report be re-run?

```
FILE_AGE_THRESHOLD_HOURS = 0.083        # default (~5 min). Override only if caller explicitly provides a value.
file_age_hours = current_time − file_last_modified_time    # unit: hours
```

```python
if not file_exists_in_cache:
    run_oracle_report()
    generate_and_commit_output_file()

elif file_age_hours > FILE_AGE_THRESHOLD_HOURS:
    run_oracle_report()
    overwrite_and_commit_output_file()

else:  # file exists AND age <= threshold
    use_cached_file()
```

---

## RULE 2 — Find the Receipt

**Output fields:**
```
fusion_receipt_number
fusion_receipt_date        # format: YYYY/MM/DD
fusion_customer_name
```
**Source:** Receipt Details Report

---

### RULE 2 — Entry point

```python
if is_null_or_empty(payment_reference):
    run_scenario_B()
else:
    run_scenario_A()
```

---

### RULE 2 — SCENARIO A  (`payment_reference` is present)

**Run A1 first. Run A2 only if A1 returns 2+ matches.**
*(If A1 returns 0 matches, A2 will also return 0 — set to null immediately.)*

#### A1 — Loose match  (2 criteria)

```python
matches = receipt_report[
    receipt_report['RECEIPT_NUMBER'].str.strip().str.lower().str.contains(
        payment_reference.strip().lower(), regex=False
    )
    & (receipt_report['RECEIPT_AMOUNT'] == float(total_amount))
]
```
```
IF len(matches) == 1:
    fusion_receipt_number = matches.RECEIPT_NUMBER
    fusion_receipt_date   = matches.RECEIPT_DATE  →  reformat to YYYY/MM/DD
    fusion_customer_name  = matches.BILL_CUSTOMER_NAME.strip()
    → STOP. Do NOT run A2.

ELIF len(matches) == 0:
    fusion_receipt_number = null
    fusion_receipt_date   = null
    fusion_customer_name  = null
    → STOP. A2 cannot recover zero matches.

ELSE (len >= 2):
    → Proceed to A2.
```

#### A2 — Strict match  (4 criteria) — only reached when A1 returned 2+ matches

```python
matches = receipt_report[
    receipt_report['RECEIPT_NUMBER'].str.strip().str.lower().str.contains(
        payment_reference.strip().lower(), regex=False
    )
    & (receipt_report['RECEIPT_AMOUNT'] == float(total_amount))
    & (receipt_report['RECEIPT_DATE'] == payment_date_as_DD_MM_YYYY)
    & (receipt_report['BILL_CUSTOMER_NAME'].str.strip().str.lower()
       == customer_name.strip().lower())
]
```
```
IF len(matches) == 1:
    fusion_receipt_number = matches.RECEIPT_NUMBER
    fusion_receipt_date   = matches.RECEIPT_DATE  →  reformat to YYYY/MM/DD
    fusion_customer_name  = matches.BILL_CUSTOMER_NAME.strip()

ELSE (len == 0 or >= 2):
    fusion_receipt_number = null
    fusion_receipt_date   = null
    fusion_customer_name  = null
```

---

### RULE 2 — SCENARIO B  (`payment_reference` is null or empty)

```python
matches = receipt_report[
    (receipt_report['BILL_CUSTOMER_NAME'].str.strip().str.lower()
     == customer_name.strip().lower())
    & (receipt_report['RECEIPT_DATE'] == payment_date_as_DD_MM_YYYY)
    & (receipt_report['RECEIPT_AMOUNT'] == float(total_amount))
]
```
```
IF len(matches) == 1:
    fusion_receipt_number = matches.RECEIPT_NUMBER
    fusion_receipt_date   = matches.RECEIPT_DATE  →  reformat to YYYY/MM/DD
    fusion_customer_name  = matches.BILL_CUSTOMER_NAME.strip()

ELSE (len == 0 or >= 2):
    fusion_receipt_number = null
    fusion_receipt_date   = null
    fusion_customer_name  = null
```

---

## RULE 3 — Find the Invoice

**Output fields:**
```
fusion_invoice_number
fusion_invoice_date        # format: YYYY/MM/DD
fusion_invoice_amount      # float
```
**Source:** Invoice Details Report

**Output mapping** — apply when any step below yields exactly 1 match:
```python
fusion_invoice_number = matched_row['TRANSACTION_NUMBER']
fusion_invoice_date   = matched_row['TRANSACTION_DATE']   # reformat DD-MM-YYYY → YYYY/MM/DD
fusion_invoice_amount = float(matched_row['TOTAL_AMOUNTS'])
```

**Step order:** 1a → 1b → 2 → 3 → 4
Stop the moment any step yields exactly 1 match. Do not run later steps.

---

### Step 1a — Exact invoice number only

```python
matches = invoice_report[
    invoice_report['TRANSACTION_NUMBER'].str.strip().str.lower()
    == invoice_number.strip().lower()
]
```
```
IF len(matches) == 1:  → write output fields. STOP.
ELSE:                  → proceed to Step 1b.
```
> Short numbers like `"1"` or `"2001"` commonly return 2+ matches. Step 1b adds the date to resolve.

---

### Step 1b — Exact invoice number + date

```python
matches = invoice_report[
    (invoice_report['TRANSACTION_NUMBER'].str.strip().str.lower()
     == invoice_number.strip().lower())
    & (invoice_report['TRANSACTION_DATE'] == invoice_date_as_DD_MM_YYYY)
]
```
```
IF len(matches) == 1:  → write output fields. STOP.
ELSE:                  → proceed to Step 2.
```

---

### Step 2 — Customer invoice number + date

> Skip this step entirely if `customer_invoice_number` (from input) is null or empty.
> 72% of `DOCUMENT_NUMBER` values in the report are null — 0 matches is the common outcome here.

```python
# DOCUMENT_NUMBER is float64 — must convert to int string before comparing
invoice_report['_doc_num_str'] = invoice_report['DOCUMENT_NUMBER'].apply(
    lambda x: str(int(x)) if pd.notna(x) else None
)

matches = invoice_report[
    (invoice_report['_doc_num_str'].str.strip().str.lower()
     == customer_invoice_number.strip().lower())
    & (invoice_report['TRANSACTION_DATE'] == invoice_date_as_DD_MM_YYYY)
]
```
```
IF len(matches) == 1:  → write output fields. STOP.
ELSE:                  → proceed to Step 3.
```

---

### Step 3 — Substring invoice number + date

The report's `TRANSACTION_NUMBER` may be a longer string that **contains** `invoice_number` as a substring.
Direction matters: report contains input — NOT the other way around.

```
Examples:
  invoice_number = "25908454"    TRANSACTION_NUMBER = "126125908454"   →  MATCH
  invoice_number = "6153004273"  TRANSACTION_NUMBER = "6153004273089"  →  MATCH
  invoice_number = "25908454"    TRANSACTION_NUMBER = "999999999"      →  NO MATCH
```

```python
matches = invoice_report[
    invoice_report['TRANSACTION_NUMBER'].str.lower().str.contains(
        invoice_number.strip().lower(), regex=False
    )
    & (invoice_report['TRANSACTION_DATE'] == invoice_date_as_DD_MM_YYYY)
]
```
```
IF len(matches) == 1:  → write output fields. STOP.
ELSE:                  → proceed to Step 4.
```

---

### Step 4 — Customer name + date + amount  (last resort)

Reached when all prior steps (1a → 1b → 2 → 3) failed to find exactly 1 match.

> ⚠️ **Confirm trigger condition with document owner.**
> This document assumes Step 4 runs whenever steps 1a–3 all failed (output is still null).
> If Step 4 should only run when the INPUT `invoice_number` is null/empty, update the entry condition.

> ℹ️ 30% of customer+date+amount combos are not unique in the report — Step 4 will frequently return 2+ matches and output null.

```python
matches = invoice_report[
    (invoice_report['BILL_CUSTOMER_NAME'].str.strip().str.lower()
     == customer_name.strip().lower())
    & (invoice_report['TRANSACTION_DATE'] == invoice_date_as_DD_MM_YYYY)
    & (invoice_report['TOTAL_AMOUNTS'] == float(invoice_amount))
]
```
```
IF len(matches) == 1:
    → write output fields. STOP.

ELSE (len == 0 or >= 2):
    fusion_invoice_number = null
    fusion_invoice_date   = null
    fusion_invoice_amount = null
```

---

## EXECUTION CHECKLIST  (run for every record)

- [ ] **Rule 1** — Check file age → run Oracle or use cache
- [ ] **Rule 2** — Check `payment_reference` → Scenario A (A1 → A2 only if A1 returns 2+) or Scenario B → populate receipt fields
- [ ] **Rule 3** — Run 1a → 1b → 2 → 3 → 4 in order, stop at first single match → populate invoice fields

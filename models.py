from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List, Union


# ── Input Models (AI-extracted payload) ──

class InvoiceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    Line_ID: Optional[int] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    invoice_amount: Optional[float] = None
    customer_invoice_number: Optional[str] = None
    store_no: Optional[str] = Field(None, alias="storeNo")
    description: Optional[str] = None

    @field_validator(
        "invoice_number", "invoice_date", "customer_invoice_number",
        "store_no", "description",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, v):
        if v == "":
            return None
        if v is not None:
            return str(v).strip()
        return v


class ReceiptRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    customer_name: str
    payment_reference: Optional[str] = None
    payment_date: Optional[str] = None
    header_id: Optional[int] = None
    total_amount: Optional[float] = None
    confidence_label: Optional[str] = None
    confidence_score: Optional[Union[int, float]] = None
    invoices: List[InvoiceItem] = []

    @field_validator("customer_name", mode="before")
    @classmethod
    def customer_name_not_empty(cls, v):
        if not v or str(v).strip() == "":
            raise ValueError("customer_name is required and cannot be empty")
        return str(v).strip()

    @field_validator(
        "payment_reference", "payment_date", "confidence_label",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v


# ── Output Models (Validated / Fused) ──

class FusedInvoiceItem(BaseModel):
    Line_ID: Optional[int] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    invoice_amount: Optional[float] = None
    customer_invoice_number: Optional[str] = None
    store_no: Optional[str] = None
    description: Optional[str] = None
    fusion_invoice_number: Optional[str] = None
    fusion_invoice_date: Optional[str] = None
    fusion_invoice_amount: Optional[float] = None
    match_step: Optional[str] = None


class MatchedRecord(BaseModel):
    customer_name: str
    payment_reference: Optional[str] = None
    payment_date: Optional[str] = None
    header_id: Optional[int] = None
    total_amount: Optional[float] = None
    confidence_label: Optional[str] = None
    confidence_score: Optional[Union[int, float]] = None
    fusion_receipt_number: Optional[str] = None
    fusion_receipt_date: Optional[str] = None
    fusion_customer_name: Optional[str] = None
    receipt_match_scenario: Optional[str] = None
    invoices: List[FusedInvoiceItem] = []

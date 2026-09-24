from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high", "urgent"]
InvestigationCategory = Literal[
    "billing_discrepancy",
    "billing_verified",
    "duplicate_charge",
    "access_issue",
    "cancellation_request",
    "needs_more_information",
]
RecommendedAction = Literal[
    "issue_partial_credit",
    "refund_duplicate_charge",
    "reset_credentials",
    "approve_cancellation",
    "request_more_information",
    "no_action",
    "escalate",
]


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    account_reference: str | None = Field(default=None, max_length=100)


class CustomerRead(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class TicketCreate(BaseModel):
    customer_id: int
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    status: TicketStatus = "open"
    priority: TicketPriority = "medium"


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None


class TicketRead(TicketCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    plan_name: str
    active_seats: int
    monthly_rate: Decimal
    status: str


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    invoice_number: str
    amount: Decimal
    seats_billed: int
    status: str
    issued_at: datetime


class KnowledgeArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    content: str


class EvidenceItem(BaseModel):
    source_type: Literal["ticket", "customer", "account", "invoice", "knowledge_article"]
    source_id: str
    detail: str


class InvestigationResult(BaseModel):
    category: InvestigationCategory
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    recommended_action: RecommendedAction
    requires_approval: bool


class RecommendationRead(InvestigationResult):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    provider: str
    created_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    event_type: str
    message: str
    event_metadata: dict
    created_at: datetime

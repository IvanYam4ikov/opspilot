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
    "review_invoice",
    "reset_credentials",
    "approve_cancellation",
    "request_more_information",
    "no_action",
    "escalate",
]
WorkflowState = Literal[
    "pending_approval",
    "ready",
    "approved",
    "rejected",
    "executing",
    "completed",
    "failed",
]
UserRole = Literal["operator", "approver", "admin"]
JobStatus = Literal["queued", "running", "completed", "failed"]


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


class ApprovalDecisionCreate(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ApprovalDecisionRead(ApprovalDecisionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int
    ticket_id: int
    decision: Literal["approved", "rejected"]
    reviewer: str
    created_at: datetime


class ActionExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int
    ticket_id: int
    action: RecommendedAction
    idempotency_key: str
    status: Literal["executing", "completed", "failed"]
    attempts: int
    external_reference: str | None
    result: dict
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class RecommendationRead(InvestigationResult):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    provider: str
    created_at: datetime
    workflow_state: WorkflowState
    approval: ApprovalDecisionRead | None = None
    execution: ActionExecutionRead | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    event_type: str
    message: str
    event_metadata: dict
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    role: UserRole


class TokenRead(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserRead


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: Literal["investigation", "action_execution"]
    status: JobStatus
    ticket_id: int | None
    recommendation_id: int | None
    requested_by_id: int
    idempotency_key: str | None
    result: dict
    error: str | None
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

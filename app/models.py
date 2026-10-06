from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    account_reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="customer")
    account: Mapped["Account | None"] = relationship(back_populates="customer")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(30), default="medium", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="ticket")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="ticket")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), unique=True, index=True)
    plan_name: Mapped[str] = mapped_column(String(100))
    active_seats: Mapped[int]
    monthly_rate: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped[Customer] = relationship(back_populates="account")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    seats_billed: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default="paid")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="invoices")


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    category: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[list[dict]] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(String(100))
    requires_approval: Mapped[bool]
    provider: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="recommendations")
    approval: Mapped["ApprovalDecision | None"] = relationship(
        back_populates="recommendation", uselist=False
    )
    execution: Mapped["ActionExecution | None"] = relationship(
        back_populates="recommendation", uselist=False
    )

    @property
    def workflow_state(self) -> str:
        if self.execution is not None:
            return self.execution.status
        if self.approval is not None:
            return self.approval.decision
        return "pending_approval" if self.requires_approval else "ready"


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id"), unique=True, index=True
    )
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    reviewer: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recommendation: Mapped[Recommendation] = relationship(back_populates="approval")


class ActionExecution(Base):
    __tablename__ = "action_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id"), unique=True, index=True
    )
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="executing", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    external_reference: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    recommendation: Mapped[Recommendation] = relationship(back_populates="execution")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="audit_events")

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import actions
from app.config import settings
from app.database import Base, engine, get_db
from app.investigation import generate_recommendation, retrieve_context
from app.models import (
    ActionExecution,
    ApprovalDecision,
    AuditEvent,
    Customer,
    Recommendation,
    Ticket,
)
from app.schemas import (
    ActionExecutionRead,
    ApprovalDecisionCreate,
    AuditEventRead,
    CustomerCreate,
    CustomerRead,
    RecommendationRead,
    TicketCreate,
    TicketRead,
    TicketUpdate,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="OpsPilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
    customer = Customer(**payload.model_dump())
    db.add(customer)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Email or account reference already exists"
        ) from exc
    db.refresh(customer)
    return customer


@app.get("/customers", response_model=list[CustomerRead])
def list_customers(db: Session = Depends(get_db)) -> list[Customer]:
    return list(db.scalars(select(Customer).order_by(Customer.name)))


@app.get("/customers/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.get("/tickets", response_model=list[TicketRead])
def list_tickets(
    ticket_status: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    db: Session = Depends(get_db),
) -> list[Ticket]:
    query = select(Ticket).order_by(Ticket.created_at.desc())
    if ticket_status:
        query = query.where(Ticket.status == ticket_status)
    if priority:
        query = query.where(Ticket.priority == priority)
    return list(db.scalars(query))


@app.get("/tickets/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.post("/tickets", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)) -> Ticket:
    if db.get(Customer, payload.customer_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    ticket = Ticket(**payload.model_dump())
    db.add(ticket)
    db.flush()
    db.add(
        AuditEvent(
            ticket_id=ticket.id,
            event_type="ticket_created",
            message="Ticket received",
            event_metadata={"priority": ticket.priority},
        )
    )
    db.commit()
    db.refresh(ticket)
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=TicketRead)
def update_ticket(ticket_id: int, payload: TicketUpdate, db: Session = Depends(get_db)) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(ticket, field, value)
    if changes:
        db.add(
            AuditEvent(
                ticket_id=ticket.id,
                event_type="ticket_updated",
                message="Ticket updated",
                event_metadata=changes,
            )
        )
    db.commit()
    db.refresh(ticket)
    return ticket


@app.post(
    "/tickets/{ticket_id}/investigate",
    response_model=RecommendationRead,
    status_code=status.HTTP_201_CREATED,
)
def investigate_ticket(ticket_id: int, db: Session = Depends(get_db)) -> Recommendation:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    db.add(
        AuditEvent(
            ticket_id=ticket.id,
            event_type="investigation_started",
            message="Investigation started",
            event_metadata={},
        )
    )
    try:
        context = retrieve_context(db, ticket)
        result, provider = generate_recommendation(context)
    except (RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    recommendation = Recommendation(
        ticket_id=ticket.id,
        provider=provider,
        **result.model_dump(mode="json"),
    )
    db.add(recommendation)
    db.flush()
    db.add_all(
        [
            AuditEvent(
                ticket_id=ticket.id,
                event_type="evidence_retrieved",
                message=f"Retrieved {len(result.evidence)} evidence sources",
                event_metadata={"sources": [item.source_id for item in result.evidence]},
            ),
            AuditEvent(
                ticket_id=ticket.id,
                event_type="recommendation_generated",
                message=f"Recommended action: {result.recommended_action}",
                event_metadata={
                    "recommendation_id": recommendation.id,
                    "confidence": result.confidence,
                    "provider": provider,
                },
            ),
        ]
    )
    db.commit()
    db.refresh(recommendation)
    return recommendation


def _get_recommendation(db: Session, ticket_id: int, recommendation_id: int) -> Recommendation:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None or recommendation.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return recommendation


def _record_decision(
    db: Session,
    ticket_id: int,
    recommendation_id: int,
    payload: ApprovalDecisionCreate,
    decision_value: str,
) -> Recommendation:
    recommendation = _get_recommendation(db, ticket_id, recommendation_id)
    if recommendation.execution is not None:
        raise HTTPException(status_code=409, detail="An executed recommendation cannot be reviewed")
    if recommendation.approval is not None:
        if recommendation.approval.decision == decision_value:
            return recommendation
        raise HTTPException(status_code=409, detail="The recommendation already has a decision")

    decision = ApprovalDecision(
        recommendation_id=recommendation.id,
        ticket_id=ticket_id,
        decision=decision_value,
        reviewer=payload.reviewer,
        note=payload.note,
    )
    recommendation.approval = decision
    db.add_all(
        [
            decision,
            AuditEvent(
                ticket_id=ticket_id,
                event_type=f"recommendation_{decision_value}",
                message=f"Recommendation {decision_value} by {payload.reviewer}",
                event_metadata={
                    "recommendation_id": recommendation.id,
                    "reviewer": payload.reviewer,
                    "note": payload.note,
                },
            ),
        ]
    )
    db.commit()
    db.refresh(recommendation)
    return recommendation


@app.post(
    "/tickets/{ticket_id}/recommendations/{recommendation_id}/approve",
    response_model=RecommendationRead,
)
def approve_recommendation(
    ticket_id: int,
    recommendation_id: int,
    payload: ApprovalDecisionCreate,
    db: Session = Depends(get_db),
) -> Recommendation:
    return _record_decision(db, ticket_id, recommendation_id, payload, "approved")


@app.post(
    "/tickets/{ticket_id}/recommendations/{recommendation_id}/reject",
    response_model=RecommendationRead,
)
def reject_recommendation(
    ticket_id: int,
    recommendation_id: int,
    payload: ApprovalDecisionCreate,
    db: Session = Depends(get_db),
) -> Recommendation:
    return _record_decision(db, ticket_id, recommendation_id, payload, "rejected")


@app.post(
    "/tickets/{ticket_id}/recommendations/{recommendation_id}/execute",
    response_model=ActionExecutionRead,
)
def execute_recommendation(
    ticket_id: int,
    recommendation_id: int,
    idempotency_key: str = Header(min_length=8, max_length=200, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> ActionExecution:
    recommendation = _get_recommendation(db, ticket_id, recommendation_id)
    decision = recommendation.approval
    if decision is not None and decision.decision == "rejected":
        raise HTTPException(status_code=409, detail="Rejected recommendations cannot be executed")
    if recommendation.requires_approval and (
        decision is None or decision.decision != "approved"
    ):
        raise HTTPException(status_code=409, detail="Approval is required before execution")

    execution = db.scalar(
        select(ActionExecution).where(ActionExecution.idempotency_key == idempotency_key)
    )
    if execution is not None and execution.recommendation_id != recommendation.id:
        raise HTTPException(status_code=409, detail="Idempotency key belongs to another action")
    if execution is not None and execution.status == "completed":
        return execution
    if execution is not None and execution.status == "executing":
        raise HTTPException(status_code=409, detail="Action execution is already in progress")

    recommendation_execution = recommendation.execution
    if recommendation_execution is not None and execution is None:
        raise HTTPException(
            status_code=409,
            detail="This recommendation already used a different idempotency key",
        )

    if execution is None:
        execution = ActionExecution(
            recommendation_id=recommendation.id,
            ticket_id=ticket_id,
            action=recommendation.recommended_action,
            idempotency_key=idempotency_key,
            status="executing",
            attempts=1,
            result={},
        )
        recommendation.execution = execution
        db.add(execution)
    else:
        execution.status = "executing"
        execution.error = None
        execution.attempts += 1

    db.add(
        AuditEvent(
            ticket_id=ticket_id,
            event_type="action_execution_started",
            message=f"Executing action: {recommendation.recommended_action}",
            event_metadata={
                "recommendation_id": recommendation.id,
                "idempotency_key": idempotency_key,
                "attempt": execution.attempts,
            },
        )
    )
    db.commit()
    db.refresh(execution)

    ticket = db.get(Ticket, ticket_id)
    if ticket is None:  # Defensive: the foreign key should make this impossible.
        raise HTTPException(status_code=404, detail="Ticket not found")
    try:
        result = actions.execute_simulated_action(ticket, recommendation, idempotency_key)
    except RuntimeError as exc:
        execution.status = "failed"
        execution.error = str(exc)
        db.add(
            AuditEvent(
                ticket_id=ticket_id,
                event_type="action_execution_failed",
                message=f"Action execution failed: {exc}",
                event_metadata={
                    "recommendation_id": recommendation.id,
                    "attempt": execution.attempts,
                },
            )
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    execution.status = "completed"
    execution.external_reference = result.external_reference
    execution.result = result.details
    execution.error = None
    execution.completed_at = datetime.now(UTC)
    ticket.status = (
        "in_progress"
        if recommendation.recommended_action
        in {"request_more_information", "escalate", "review_invoice"}
        else "resolved"
    )
    db.add(
        AuditEvent(
            ticket_id=ticket_id,
            event_type="action_execution_completed",
            message=f"Completed action: {recommendation.recommended_action}",
            event_metadata={
                "recommendation_id": recommendation.id,
                "external_reference": result.external_reference,
                "idempotency_key": idempotency_key,
            },
        )
    )
    db.commit()
    db.refresh(execution)
    return execution


@app.get("/tickets/{ticket_id}/recommendations", response_model=list[RecommendationRead])
def list_recommendations(ticket_id: int, db: Session = Depends(get_db)) -> list[Recommendation]:
    if db.get(Ticket, ticket_id) is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.ticket_id == ticket_id)
            .order_by(Recommendation.created_at.desc())
        )
    )


@app.get("/tickets/{ticket_id}/events", response_model=list[AuditEventRead])
def list_audit_events(ticket_id: int, db: Session = Depends(get_db)) -> list[AuditEvent]:
    if db.get(Ticket, ticket_id) is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.ticket_id == ticket_id)
            .order_by(AuditEvent.created_at)
        )
    )

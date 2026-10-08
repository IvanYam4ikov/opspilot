import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import authenticate_user, create_access_token, get_current_user, require_roles
from app.config import settings
from app.database import Base, engine, get_db
from app.models import (
    ApprovalDecision,
    AuditEvent,
    Customer,
    Job,
    Recommendation,
    Ticket,
    User,
)
from app.schemas import (
    ApprovalDecisionCreate,
    AuditEventRead,
    CustomerCreate,
    CustomerRead,
    JobRead,
    LoginRequest,
    RecommendationRead,
    TicketCreate,
    TicketRead,
    TicketUpdate,
    TokenRead,
    UserRead,
)

logger = logging.getLogger("opspilot.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="OpsPilot API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login", response_model=TokenRead)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(db, str(payload.email), payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token, expires_in = create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user,
    }


@app.get("/auth/me", response_model=UserRead)
def current_user(user: User = Depends(get_current_user)) -> User:
    return user


@app.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("operator", "admin")),
) -> Customer:
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
def list_customers(
    db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[Customer]:
    return list(db.scalars(select(Customer).order_by(Customer.name)))


@app.get("/customers/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.get("/tickets", response_model=list[TicketRead])
def list_tickets(
    ticket_status: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Ticket]:
    query = select(Ticket).order_by(Ticket.created_at.desc())
    if ticket_status:
        query = query.where(Ticket.status == ticket_status)
    if priority:
        query = query.where(Ticket.priority == priority)
    return list(db.scalars(query))


@app.get("/tickets/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.post("/tickets", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("operator", "admin")),
) -> Ticket:
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
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("operator", "admin")),
) -> Ticket:
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
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def investigate_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("operator", "admin")),
) -> Job:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    existing = db.scalar(
        select(Job)
        .where(
            Job.job_type == "investigation",
            Job.ticket_id == ticket_id,
            Job.status.in_(("queued", "running")),
        )
        .order_by(Job.created_at.desc())
    )
    if existing is not None:
        return existing
    job = Job(
        job_type="investigation",
        status="queued",
        ticket_id=ticket_id,
        requested_by_id=user.id,
        payload={},
        result={},
    )
    db.add(job)
    db.flush()
    db.add(
        AuditEvent(
            ticket_id=ticket.id,
            event_type="investigation_queued",
            message="Investigation queued",
            event_metadata={"job_id": job.id, "requested_by": user.email},
        )
    )
    db.commit()
    db.refresh(job)
    return job


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
    user: User,
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
        reviewer=user.display_name,
        note=payload.note,
    )
    recommendation.approval = decision
    db.add_all(
        [
            decision,
            AuditEvent(
                ticket_id=ticket_id,
                event_type=f"recommendation_{decision_value}",
                message=f"Recommendation {decision_value} by {user.display_name}",
                event_metadata={
                    "recommendation_id": recommendation.id,
                    "reviewer": user.display_name,
                    "reviewer_user_id": user.id,
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
    user: User = Depends(require_roles("approver", "admin")),
) -> Recommendation:
    return _record_decision(db, ticket_id, recommendation_id, payload, "approved", user)


@app.post(
    "/tickets/{ticket_id}/recommendations/{recommendation_id}/reject",
    response_model=RecommendationRead,
)
def reject_recommendation(
    ticket_id: int,
    recommendation_id: int,
    payload: ApprovalDecisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("approver", "admin")),
) -> Recommendation:
    return _record_decision(db, ticket_id, recommendation_id, payload, "rejected", user)


@app.post(
    "/tickets/{ticket_id}/recommendations/{recommendation_id}/execute",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_recommendation(
    ticket_id: int,
    recommendation_id: int,
    idempotency_key: str = Header(min_length=8, max_length=200, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("operator", "approver", "admin")),
) -> Job:
    recommendation = _get_recommendation(db, ticket_id, recommendation_id)
    decision = recommendation.approval
    if decision is not None and decision.decision == "rejected":
        raise HTTPException(status_code=409, detail="Rejected recommendations cannot be executed")
    if recommendation.requires_approval and (decision is None or decision.decision != "approved"):
        raise HTTPException(status_code=409, detail="Approval is required before execution")

    existing_job = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing_job is not None:
        if existing_job.recommendation_id != recommendation.id:
            raise HTTPException(status_code=409, detail="Idempotency key belongs to another action")
        if existing_job.status == "failed":
            existing_job.status = "queued"
            existing_job.attempts = 0
            existing_job.error = None
            existing_job.completed_at = None
            db.commit()
            db.refresh(existing_job)
        return existing_job

    if recommendation.execution is not None:
        raise HTTPException(
            status_code=409,
            detail="This recommendation already used a different idempotency key",
        )

    job = Job(
        job_type="action_execution",
        status="queued",
        ticket_id=ticket_id,
        recommendation_id=recommendation.id,
        requested_by_id=user.id,
        idempotency_key=idempotency_key,
        payload={"action": recommendation.recommended_action},
        result={},
    )
    db.add(job)
    db.flush()
    db.add(
        AuditEvent(
            ticket_id=ticket_id,
            event_type="action_execution_queued",
            message=f"Queued action: {recommendation.recommended_action}",
            event_metadata={
                "job_id": job.id,
                "recommendation_id": recommendation.id,
                "idempotency_key": idempotency_key,
                "requested_by": user.email,
            },
        )
    )
    db.commit()
    db.refresh(job)
    return job


@app.get("/tickets/{ticket_id}/recommendations", response_model=list[RecommendationRead])
def list_recommendations(
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Recommendation]:
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
def list_audit_events(
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[AuditEvent]:
    if db.get(Ticket, ticket_id) is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.ticket_id == ticket_id)
            .order_by(AuditEvent.created_at)
        )
    )


@app.get("/jobs/{job_id}", response_model=JobRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/ops/metrics")
def operational_metrics(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("approver", "admin")),
) -> dict:
    jobs = list(db.scalars(select(Job)))
    completed_durations = [
        float(job.result["duration_ms"])
        for job in jobs
        if job.status == "completed" and "duration_ms" in job.result
    ]
    status_counts = {
        value: int(db.scalar(select(func.count()).where(Job.status == value)) or 0)
        for value in ("queued", "running", "completed", "failed")
    }
    return {
        "jobs": {
            "total": len(jobs),
            "by_status": status_counts,
            "average_duration_ms": (
                round(sum(completed_durations) / len(completed_durations), 2)
                if completed_durations
                else None
            ),
        },
        "recommendations": int(db.scalar(select(func.count(Recommendation.id))) or 0),
        "approval_decisions": int(db.scalar(select(func.count(ApprovalDecision.id))) or 0),
    }

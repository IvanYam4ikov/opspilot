from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.investigation import generate_recommendation, retrieve_context
from app.models import AuditEvent, Customer, Recommendation, Ticket
from app.schemas import (
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

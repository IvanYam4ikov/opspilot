from datetime import UTC, datetime

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.evaluation_cases import EVALUATION_CASES
from app.models import Account, AuditEvent, Customer, Invoice, KnowledgeArticle, Ticket


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        customer = db.scalar(select(Customer).where(Customer.email == "ops@acme.example"))
        if customer is None:
            customer = Customer(
                name="Acme Analytics",
                email="ops@acme.example",
                account_reference="ACME-001",
            )
            db.add(customer)
            db.flush()

        if db.scalar(select(Account).where(Account.customer_id == customer.id)) is None:
            db.add(
                Account(
                    customer_id=customer.id,
                    plan_name="Growth Annual",
                    active_seats=10,
                    monthly_rate=3200,
                    status="active",
                )
            )

        if db.scalar(select(Invoice.id).where(Invoice.customer_id == customer.id)) is None:
            db.add(
                Invoice(
                    customer_id=customer.id,
                    invoice_number="INV-1044",
                    amount=4500,
                    seats_billed=15,
                    status="paid",
                    issued_at=datetime(2026, 8, 15, tzinfo=UTC),
                )
            )

        if db.scalar(select(KnowledgeArticle.id).limit(1)) is None:
            db.add_all(
                [
                    KnowledgeArticle(
                        title="Correcting seat-count billing errors",
                        category="billing",
                        content=(
                            "When an invoice bills more seats than the active subscription, "
                            "verify both records and propose a credit for the difference. "
                            "Credits require human approval."
                        ),
                    ),
                    KnowledgeArticle(
                        title="Requesting additional diagnostic information",
                        category="support",
                        content=(
                            "If logs and account records do not establish a root cause, request "
                            "timestamps, request IDs, and the exact error response."
                        ),
                    ),
                ]
            )

        billing_title = "Invoice amount appears incorrect"
        if db.scalar(select(Ticket.id).where(Ticket.title == billing_title)) is None:
            tickets = [
                Ticket(
                    customer_id=customer.id,
                    title=billing_title,
                    description="We were charged $4,500 but expected $3,200.",
                    priority="high",
                ),
            ]
            api_ticket = db.scalar(
                select(Ticket.id).where(Ticket.title == "API authentication error")
            )
            if api_ticket is None:
                tickets.append(
                    Ticket(
                        customer_id=customer.id,
                        title="API authentication error",
                        description="Production sync started returning HTTP 401 this morning.",
                        priority="medium",
                    )
                )
            db.add_all(tickets)
            db.flush()
            db.add_all(
                [
                    AuditEvent(
                        ticket_id=ticket.id,
                        event_type="ticket_created",
                        message="Ticket received",
                        event_metadata={"source": "seed"},
                    )
                    for ticket in tickets
                ]
            )
        seed_evaluation_cases(db)
        db.commit()
        print("Demo data and AI evaluation tickets are ready.")


def seed_evaluation_cases(db) -> None:
    for case in EVALUATION_CASES:
        customer = db.scalar(select(Customer).where(Customer.email == case.customer_email))
        if customer is None:
            customer = Customer(
                name=case.customer_name,
                email=case.customer_email,
                account_reference=case.account_reference,
            )
            db.add(customer)
            db.flush()

        if case.plan_name and db.scalar(
            select(Account.id).where(Account.customer_id == customer.id)
        ) is None:
            db.add(
                Account(
                    customer_id=customer.id,
                    plan_name=case.plan_name,
                    active_seats=case.active_seats,
                    monthly_rate=case.monthly_rate,
                    status="active",
                )
            )

        for invoice in case.invoices:
            if db.scalar(
                select(Invoice.id).where(Invoice.invoice_number == invoice.number)
            ) is None:
                db.add(
                    Invoice(
                        customer_id=customer.id,
                        invoice_number=invoice.number,
                        amount=invoice.amount,
                        seats_billed=invoice.seats_billed,
                        status="paid",
                        issued_at=invoice.issued_at,
                    )
                )

        if db.scalar(select(Ticket.id).where(Ticket.title == case.title)) is None:
            ticket = Ticket(
                customer_id=customer.id,
                title=case.title,
                description=case.description,
                priority=case.priority,
            )
            db.add(ticket)
            db.flush()
            db.add(
                AuditEvent(
                    ticket_id=ticket.id,
                    event_type="ticket_created",
                    message="Evaluation ticket received",
                    event_metadata={"source": "eval_seed", "case": case.key},
                )
            )


if __name__ == "__main__":
    seed()

from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.evaluation_cases import EVALUATION_CASES
from app.investigation import generate_recommendation, retrieve_context
from app.models import Account, Invoice, KnowledgeArticle, Ticket
from app.seed import seed_evaluation_cases


def create_customer(client):
    response = client.post(
        "/customers",
        json={"name": "Acme", "email": "ops@acme.example", "account_reference": "A-1"},
    )
    assert response.status_code == 201
    return response.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ticket_lifecycle(client):
    customer = create_customer(client)
    created = client.post(
        "/tickets",
        json={
            "customer_id": customer["id"],
            "title": "Invoice discrepancy",
            "description": "Expected $3,200, charged $4,500.",
            "priority": "high",
        },
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    listed = client.get("/tickets", params={"status": "open", "priority": "high"})
    assert [ticket["id"] for ticket in listed.json()] == [ticket_id]

    updated = client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"


def test_ticket_requires_existing_customer(client):
    response = client.post(
        "/tickets",
        json={"customer_id": 999, "title": "Help", "description": "Something broke"},
    )
    assert response.status_code == 404


def test_list_customers(client):
    customer = create_customer(client)

    response = client.get("/customers")

    assert response.status_code == 200
    assert response.json() == [customer]


def test_investigation_generates_evidence_and_audit_events(client):
    customer = create_customer(client)
    ticket = client.post(
        "/tickets",
        json={
            "customer_id": customer["id"],
            "title": "Invoice is wrong",
            "description": "We were charged $4,500 instead of $3,200.",
            "priority": "high",
        },
    ).json()
    with SessionLocal() as db:
        db.add_all(
            [
                Account(
                    customer_id=customer["id"],
                    plan_name="Growth",
                    active_seats=10,
                    monthly_rate=3200,
                ),
                Invoice(
                    customer_id=customer["id"],
                    invoice_number="INV-TEST",
                    amount=4500,
                    seats_billed=15,
                    status="paid",
                    issued_at=datetime(2026, 8, 15, tzinfo=UTC),
                ),
                KnowledgeArticle(
                    title="Seat billing corrections",
                    category="billing",
                    content="Verify the account and invoice, then propose a credit.",
                ),
            ]
        )
        db.commit()

    response = client.post(f"/tickets/{ticket['id']}/investigate")

    assert response.status_code == 201
    result = response.json()
    assert result["category"] == "billing_discrepancy"
    assert result["recommended_action"] == "issue_partial_credit"
    assert result["requires_approval"] is True
    assert result["provider"] == "demo"
    assert len(result["evidence"]) == 3

    recommendations = client.get(f"/tickets/{ticket['id']}/recommendations").json()
    assert recommendations[0]["id"] == result["id"]
    events = client.get(f"/tickets/{ticket['id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "ticket_created",
        "investigation_started",
        "evidence_retrieved",
        "recommendation_generated",
    ]


def test_investigation_handles_insufficient_evidence(client):
    customer = create_customer(client)
    ticket = client.post(
        "/tickets",
        json={
            "customer_id": customer["id"],
            "title": "Login problem",
            "description": "A user cannot log in.",
        },
    ).json()

    response = client.post(f"/tickets/{ticket['id']}/investigate")

    assert response.status_code == 201
    assert response.json()["category"] == "needs_more_information"
    assert response.json()["recommended_action"] == "request_more_information"


def test_demo_provider_passes_seeded_eval_suite(client):
    with SessionLocal() as db:
        seed_evaluation_cases(db)
        db.commit()

        for case in EVALUATION_CASES:
            ticket = db.scalar(select(Ticket).where(Ticket.title == case.title))
            assert ticket is not None
            result, provider = generate_recommendation(retrieve_context(db, ticket))
            evidence_types = {item.source_type for item in result.evidence}

            assert provider == "demo"
            assert result.category == case.expected_category
            assert result.recommended_action == case.expected_action
            assert result.requires_approval == case.expected_approval
            assert case.required_evidence_types.issubset(evidence_types)

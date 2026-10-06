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


def create_billing_recommendation(client):
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
    recommendation = client.post(f"/tickets/{ticket['id']}/investigate").json()
    return ticket, recommendation


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
    ticket, result = create_billing_recommendation(client)
    assert result["category"] == "billing_discrepancy"
    assert result["recommended_action"] == "issue_partial_credit"
    assert result["requires_approval"] is True
    assert result["provider"] == "demo"
    assert result["workflow_state"] == "pending_approval"
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


def test_approval_and_execution_are_audited_and_idempotent(client):
    ticket, recommendation = create_billing_recommendation(client)
    path = f"/tickets/{ticket['id']}/recommendations/{recommendation['id']}"

    blocked = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-001"})
    assert blocked.status_code == 409

    approved = client.post(
        f"{path}/approve",
        json={"reviewer": "Jordan Lee", "note": "Invoice evidence verified."},
    )
    assert approved.status_code == 200
    assert approved.json()["workflow_state"] == "approved"
    assert approved.json()["approval"]["reviewer"] == "Jordan Lee"

    duplicate_approval = client.post(
        f"{path}/approve",
        json={"reviewer": "Jordan Lee", "note": "Retry"},
    )
    assert duplicate_approval.status_code == 200
    assert duplicate_approval.json()["approval"]["id"] == approved.json()["approval"]["id"]

    executed = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-001"})
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    assert executed.json()["attempts"] == 1
    assert executed.json()["external_reference"].startswith("SIM-")

    duplicate_execution = client.post(
        f"{path}/execute", headers={"Idempotency-Key": "credit-001"}
    )
    assert duplicate_execution.status_code == 200
    assert duplicate_execution.json()["id"] == executed.json()["id"]
    assert duplicate_execution.json()["attempts"] == 1

    refreshed_ticket = client.get(f"/tickets/{ticket['id']}").json()
    assert refreshed_ticket["status"] == "resolved"
    events = client.get(f"/tickets/{ticket['id']}/events").json()
    event_types = [event["event_type"] for event in events]
    assert event_types[-3:] == [
        "recommendation_approved",
        "action_execution_started",
        "action_execution_completed",
    ]


def test_rejected_recommendation_cannot_execute(client):
    ticket, recommendation = create_billing_recommendation(client)
    path = f"/tickets/{ticket['id']}/recommendations/{recommendation['id']}"

    rejected = client.post(
        f"{path}/reject",
        json={"reviewer": "Jordan Lee", "note": "Needs manual investigation."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["workflow_state"] == "rejected"

    execution = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-002"})
    assert execution.status_code == 409


def test_failed_execution_can_retry_with_the_same_key(client, monkeypatch):
    from app import actions

    ticket, recommendation = create_billing_recommendation(client)
    path = f"/tickets/{ticket['id']}/recommendations/{recommendation['id']}"
    client.post(f"{path}/approve", json={"reviewer": "Jordan Lee"})

    def fail_once(*_args, **_kwargs):
        raise RuntimeError("Simulated billing service unavailable")

    original_execute = actions.execute_simulated_action
    monkeypatch.setattr("app.main.actions.execute_simulated_action", fail_once)
    failed = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-003"})
    assert failed.status_code == 502

    monkeypatch.setattr("app.main.actions.execute_simulated_action", original_execute)
    retried = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-003"})
    assert retried.status_code == 200
    assert retried.json()["status"] == "completed"
    assert retried.json()["attempts"] == 2

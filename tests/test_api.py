from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.evaluation_cases import EVALUATION_CASES
from app.investigation import generate_recommendation, retrieve_context
from app.jobs import process_job
from app.models import Account, Invoice, KnowledgeArticle, Ticket
from app.seed import seed_evaluation_cases


def login(client, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


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
    queued = client.post(f"/tickets/{ticket['id']}/investigate")
    assert queued.status_code == 202
    completed = process_job(queued.json()["id"])
    assert completed.status == "completed"
    recommendation = client.get(f"/tickets/{ticket['id']}/recommendations").json()[0]
    return ticket, recommendation


def test_health_and_authentication(client):
    assert client.get("/health").json() == {"status": "ok"}
    client.headers.pop("Authorization")
    assert client.get("/tickets").status_code == 401
    assert (
        client.post(
            "/auth/login", json={"email": "admin@opspilot.example", "password": "wrong-password"}
        ).status_code
        == 401
    )


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
    listed_ids = [item["id"] for item in client.get("/tickets", params={"status": "open"}).json()]
    assert listed_ids == [ticket_id]
    updated = client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})
    assert updated.json()["status"] == "in_progress"


def test_ticket_requires_existing_customer(client):
    response = client.post(
        "/tickets", json={"customer_id": 999, "title": "Help", "description": "Something broke"}
    )
    assert response.status_code == 404


def test_investigation_runs_as_a_durable_job(client):
    ticket, result = create_billing_recommendation(client)
    assert result["category"] == "billing_discrepancy"
    assert result["recommended_action"] == "issue_partial_credit"
    assert result["provider"] == "demo"
    assert len(result["evidence"]) == 3
    events = client.get(f"/tickets/{ticket['id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "ticket_created",
        "investigation_queued",
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
    queued = client.post(f"/tickets/{ticket['id']}/investigate")
    assert queued.status_code == 202
    process_job(queued.json()["id"])
    result = client.get(f"/tickets/{ticket['id']}/recommendations").json()[0]
    assert result["category"] == "needs_more_information"
    assert result["recommended_action"] == "request_more_information"


def test_demo_provider_passes_seeded_eval_suite(client):
    with SessionLocal() as db:
        seed_evaluation_cases(db)
        db.commit()
        for case in EVALUATION_CASES:
            ticket = db.scalar(select(Ticket).where(Ticket.title == case.title))
            result, provider = generate_recommendation(retrieve_context(db, ticket))
            evidence_types = {item.source_type for item in result.evidence}
            assert provider == "demo"
            assert result.category == case.expected_category
            assert result.recommended_action == case.expected_action
            assert case.required_evidence_types.issubset(evidence_types)


def test_role_based_approval_and_async_idempotent_execution(client):
    ticket, recommendation = create_billing_recommendation(client)
    path = f"/tickets/{ticket['id']}/recommendations/{recommendation['id']}"
    operator = login(client, "operator@opspilot.example", "demo-operator")
    denied = client.post(
        f"{path}/approve",
        json={"note": "verified"},
        headers={"Authorization": f"Bearer {operator}"},
    )
    assert denied.status_code == 403

    approved = client.post(f"{path}/approve", json={"note": "Invoice evidence verified."})
    assert approved.status_code == 200
    assert approved.json()["approval"]["reviewer"] == "Demo Administrator"

    queued = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-001"})
    assert queued.status_code == 202
    completed = process_job(queued.json()["id"])
    assert completed.status == "completed"
    duplicate = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-001"})
    assert duplicate.json()["id"] == queued.json()["id"]
    refreshed = client.get(f"/tickets/{ticket['id']}").json()
    assert refreshed["status"] == "resolved"


def test_rejected_recommendation_cannot_execute(client):
    ticket, recommendation = create_billing_recommendation(client)
    path = f"/tickets/{ticket['id']}/recommendations/{recommendation['id']}"
    assert client.post(f"{path}/reject", json={"note": "Needs review"}).status_code == 200
    execution = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-002"})
    assert execution.status_code == 409


def test_failed_job_retries_and_can_be_resubmitted(client, monkeypatch):
    ticket, recommendation = create_billing_recommendation(client)
    path = f"/tickets/{ticket['id']}/recommendations/{recommendation['id']}"
    client.post(f"{path}/approve", json={})
    queued = client.post(f"{path}/execute", headers={"Idempotency-Key": "credit-003"}).json()

    def fail(*_args, **_kwargs):
        raise RuntimeError("Simulated billing service unavailable")

    monkeypatch.setattr("app.jobs.actions.execute_simulated_action", fail)
    for _ in range(3):
        failed = process_job(queued["id"])
    assert failed.status == "failed"
    assert failed.attempts == 3


def test_metrics_are_restricted_to_approvers(client):
    assert client.get("/ops/metrics").status_code == 200
    operator = login(client, "operator@opspilot.example", "demo-operator")
    response = client.get("/ops/metrics", headers={"Authorization": f"Bearer {operator}"})
    assert response.status_code == 403

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


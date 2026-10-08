import os

os.environ["DATABASE_URL"] = "sqlite:///./test_opspilot.db"
os.environ["AUTH_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.seed import seed_demo_users


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_demo_users(db)
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        response = test_client.post(
            "/auth/login",
            json={"email": "admin@opspilot.example", "password": "demo-admin"},
        )
        test_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        yield test_client

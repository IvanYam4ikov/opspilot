from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Customer, Ticket


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(Customer.id).limit(1)) is not None:
            print("Database already contains customers; seed skipped.")
            return

        customer = Customer(
            name="Acme Analytics",
            email="ops@acme.example",
            account_reference="ACME-001",
        )
        db.add(customer)
        db.flush()
        db.add_all(
            [
                Ticket(
                    customer_id=customer.id,
                    title="Invoice amount appears incorrect",
                    description="We were charged $4,500 but expected $3,200.",
                    priority="high",
                ),
                Ticket(
                    customer_id=customer.id,
                    title="API authentication error",
                    description="Production sync started returning HTTP 401 this morning.",
                    priority="medium",
                ),
            ]
        )
        db.commit()
        print("Created one customer and two tickets.")


if __name__ == "__main__":
    seed()


"""Create the OpsPilot baseline schema.

Revision ID: 0001_baseline
Revises:
"""

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_all is intentionally idempotent so existing local demo volumes can adopt Alembic.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

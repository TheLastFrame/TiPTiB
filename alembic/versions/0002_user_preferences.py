"""user preferences

Revision ID: 0002_user_preferences
Revises: 0001_initial
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_user_preferences"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"))
    op.add_column("users", sa.Column("timezone", sa.String(length=80), nullable=False, server_default="Europe/Vienna"))


def downgrade() -> None:
    op.drop_column("users", "timezone")
    op.drop_column("users", "currency")

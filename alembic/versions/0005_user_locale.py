"""user locale

Revision ID: 0005_user_locale
Revises: 0004_item_reason_amount
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_user_locale"
down_revision = "0004_item_reason_amount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=20), nullable=False, server_default="de_AT"))


def downgrade() -> None:
    op.drop_column("users", "locale")

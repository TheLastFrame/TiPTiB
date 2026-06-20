"""item reason and amount

Revision ID: 0004_item_reason_amount
Revises: 0003_wishlist_archived
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_item_reason_amount"
down_revision = "0003_wishlist_archived"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("amount", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("items", "amount")
    op.drop_column("items", "reason")

"""wishlist archived flag

Revision ID: 0003_wishlist_archived
Revises: 0002_user_preferences
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_wishlist_archived"
down_revision = "0002_user_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wishlists", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("wishlists", "archived")

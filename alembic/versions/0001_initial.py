"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

item_status = sa.Enum("idea", "planned", "saving", "ready", "bought", "skipped", name="itemstatus")
cadence = sa.Enum("daily", "weekly", "monthly", name="recurrencecadence")
entry_kind = sa.Enum("manual", "recurring", "adjustment", name="savingsentrykind")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "wishlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_wishlist_user_name"),
    )
    op.create_index("ix_wishlists_user_id", "wishlists", ["user_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )
    op.create_index("ix_categories_user_id", "categories", ["user_id"])

    op.create_table(
        "saving_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_account_user_name"),
    )
    op.create_index("ix_saving_accounts_user_id", "saving_accounts", ["user_id"])

    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wishlist_id", sa.Integer(), sa.ForeignKey("wishlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("url", sa.String(500)),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("status", item_status, nullable=False),
        sa.Column("price_min", sa.Numeric(12, 2)),
        sa.Column("price_avg", sa.Numeric(12, 2)),
        sa.Column("price_max", sa.Numeric(12, 2)),
        sa.Column("actual_price", sa.Numeric(12, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_items_user_id", "items", ["user_id"])
    op.create_index("ix_items_wishlist_id", "items", ["wishlist_id"])
    op.create_index("ix_items_category_id", "items", ["category_id"])
    op.create_index("ix_items_rank", "items", ["rank"])
    op.create_index("ix_items_status", "items", ["status"])

    op.create_table(
        "savings_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("saving_accounts.id", ondelete="SET NULL")),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("cadence", cadence, nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id"),
    )
    op.create_index("ix_savings_rules_user_id", "savings_rules", ["user_id"])
    op.create_index("ix_savings_rules_item_id", "savings_rules", ["item_id"])
    op.create_index("ix_savings_rules_account_id", "savings_rules", ["account_id"])
    op.create_index("ix_savings_rules_next_run_at", "savings_rules", ["next_run_at"])

    op.create_table(
        "savings_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("saving_accounts.id", ondelete="SET NULL")),
        sa.Column("savings_rule_id", sa.Integer(), sa.ForeignKey("savings_rules.id", ondelete="SET NULL")),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("kind", entry_kind, nullable=False),
        sa.Column("note", sa.String(250)),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("savings_rule_id", "scheduled_for", name="uq_rule_scheduled_entry"),
    )
    op.create_index("ix_savings_entries_user_id", "savings_entries", ["user_id"])
    op.create_index("ix_savings_entries_item_id", "savings_entries", ["item_id"])
    op.create_index("ix_savings_entries_account_id", "savings_entries", ["account_id"])
    op.create_index("ix_savings_entries_savings_rule_id", "savings_entries", ["savings_rule_id"])
    op.create_index("ix_savings_entries_scheduled_for", "savings_entries", ["scheduled_for"])


def downgrade() -> None:
    op.drop_table("savings_entries")
    op.drop_table("savings_rules")
    op.drop_table("items")
    op.drop_table("saving_accounts")
    op.drop_table("categories")
    op.drop_table("wishlists")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

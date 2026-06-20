from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ItemStatus(str, enum.Enum):
    idea = "idea"
    planned = "planned"
    saving = "saving"
    ready = "ready"
    bought = "bought"
    skipped = "skipped"


class RecurrenceCadence(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class SavingsEntryKind(str, enum.Enum):
    manual = "manual"
    recurring = "recurring"
    adjustment = "adjustment"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Vienna")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    wishlists: Mapped[list[Wishlist]] = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list[Category]] = relationship(back_populates="user", cascade="all, delete-orphan")
    saving_accounts: Mapped[list[SavingAccount]] = relationship(back_populates="user", cascade="all, delete-orphan")
    items: Mapped[list[Item]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Wishlist(Base):
    __tablename__ = "wishlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_wishlist_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="wishlists")
    items: Mapped[list[Item]] = relationship(back_populates="wishlist", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_category_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(20), default="#8b8f78")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="categories")
    items: Mapped[list[Item]] = relationship(back_populates="category")


class SavingAccount(Base):
    __tablename__ = "saving_accounts"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_account_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="saving_accounts")
    savings_entries: Mapped[list[SavingsEntry]] = relationship(back_populates="account")
    savings_rules: Mapped[list[SavingsRule]] = relationship(back_populates="account")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    wishlist_id: Mapped[int] = mapped_column(ForeignKey("wishlists.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    rank: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), default=ItemStatus.idea, index=True)
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    actual_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="items")
    wishlist: Mapped[Wishlist] = relationship(back_populates="items")
    category: Mapped[Category | None] = relationship(back_populates="items")
    savings_entries: Mapped[list[SavingsEntry]] = relationship(back_populates="item", cascade="all, delete-orphan")
    savings_rule: Mapped[SavingsRule | None] = relationship(back_populates="item", cascade="all, delete-orphan")


class SavingsRule(Base):
    __tablename__ = "savings_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), unique=True, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("saving_accounts.id", ondelete="SET NULL"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    cadence: Mapped[RecurrenceCadence] = mapped_column(Enum(RecurrenceCadence))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="savings_rule")
    account: Mapped[SavingAccount | None] = relationship(back_populates="savings_rules")


class SavingsEntry(Base):
    __tablename__ = "savings_entries"
    __table_args__ = (UniqueConstraint("savings_rule_id", "scheduled_for", name="uq_rule_scheduled_entry"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("saving_accounts.id", ondelete="SET NULL"), index=True)
    savings_rule_id: Mapped[int | None] = mapped_column(ForeignKey("savings_rules.id", ondelete="SET NULL"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    kind: Mapped[SavingsEntryKind] = mapped_column(Enum(SavingsEntryKind), default=SavingsEntryKind.manual)
    note: Mapped[str | None] = mapped_column(String(250))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="savings_entries")
    account: Mapped[SavingAccount | None] = relationship(back_populates="savings_entries")

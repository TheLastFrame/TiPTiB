from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Item,
    ItemStatus,
    RecurrenceCadence,
    SavingAccount,
    SavingsEntry,
    SavingsEntryKind,
    SavingsRule,
    User,
    Wishlist,
)


ACTIVE_STATUSES = (ItemStatus.idea, ItemStatus.planned, ItemStatus.saving, ItemStatus.ready)
PLANNED_TOTAL_STATUSES = (ItemStatus.planned, ItemStatus.saving, ItemStatus.ready)
HISTORY_STATUSES = (ItemStatus.bought, ItemStatus.skipped)


def money(value: object | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def item_saved_total(db: Session, item_id: int) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(SavingsEntry.amount), 0)).where(SavingsEntry.item_id == item_id))
    return money(total)


def item_target(item: Item) -> Decimal:
    return money(item.actual_price or item.price_avg or item.price_max or item.price_min)


def progress_percent(saved: Decimal, target: Decimal) -> int:
    if target <= 0:
        return 0
    return min(100, int((saved / target) * 100))


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ensure_defaults(db: Session, user: User) -> None:
    has_list = db.scalar(select(func.count(Wishlist.id)).where(Wishlist.user_id == user.id))
    if not has_list:
        db.add(Wishlist(user_id=user.id, name="General", description="Everyday wishes and buy plans"))
    has_account = db.scalar(select(func.count(SavingAccount.id)).where(SavingAccount.user_id == user.id))
    if not has_account:
        db.add(SavingAccount(user_id=user.id, name="Cash", is_default=True))
    db.commit()


def next_rank(db: Session, user_id: int, wishlist_id: int) -> int:
    current = db.scalar(
        select(func.coalesce(func.max(Item.rank), 0)).where(Item.user_id == user_id, Item.wishlist_id == wishlist_id)
    )
    return int(current or 0) + 1


def account_breakdown(db: Session, user_id: int) -> list[tuple[str, Decimal]]:
    rows = db.execute(
        select(SavingAccount.name, func.coalesce(func.sum(SavingsEntry.amount), 0))
        .join(SavingsEntry, SavingsEntry.account_id == SavingAccount.id, isouter=True)
        .where(SavingAccount.user_id == user_id, SavingAccount.archived.is_(False))
        .group_by(SavingAccount.id)
        .order_by(SavingAccount.is_default.desc(), SavingAccount.name)
    ).all()
    return [(name, money(total)) for name, total in rows]


def apply_ready_status(db: Session, item: Item) -> None:
    if item.status != ItemStatus.saving:
        return
    target = item_target(item)
    if target > 0 and item_saved_total(db, item.id) >= target:
        item.status = ItemStatus.ready


def add_savings_entry(
    db: Session,
    *,
    user_id: int,
    item: Item,
    amount: Decimal,
    account_id: int | None,
    kind: SavingsEntryKind,
    note: str | None = None,
    savings_rule_id: int | None = None,
    scheduled_for: datetime | None = None,
) -> SavingsEntry:
    entry = SavingsEntry(
        user_id=user_id,
        item_id=item.id,
        account_id=account_id,
        amount=amount,
        kind=kind,
        note=note,
        savings_rule_id=savings_rule_id,
        scheduled_for=scheduled_for,
    )
    db.add(entry)
    db.flush()
    apply_ready_status(db, item)
    db.commit()
    db.refresh(entry)
    return entry


def advance_run_at(run_at: datetime, cadence: RecurrenceCadence) -> datetime:
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    if cadence == RecurrenceCadence.daily:
        return run_at + timedelta(days=1)
    if cadence == RecurrenceCadence.weekly:
        return run_at + timedelta(weeks=1)
    month = run_at.month + 1
    year = run_at.year
    if month > 12:
        month = 1
        year += 1
    day = min(run_at.day, 28)
    return run_at.replace(year=year, month=month, day=day)


def process_due_savings_rules(db: Session, now: datetime | None = None) -> int:
    now = as_utc(now or datetime.now(timezone.utc))
    count = 0
    rules = db.scalars(
        select(SavingsRule)
        .join(Item, Item.id == SavingsRule.item_id)
        .where(SavingsRule.active.is_(True), SavingsRule.next_run_at <= now, Item.status == ItemStatus.saving)
        .order_by(SavingsRule.next_run_at)
    ).all()
    for rule in rules:
        rule.next_run_at = as_utc(rule.next_run_at)
        while rule.next_run_at <= now:
            existing = db.scalar(
                select(SavingsEntry.id).where(
                    SavingsEntry.savings_rule_id == rule.id,
                    SavingsEntry.scheduled_for == rule.next_run_at,
                )
            )
            scheduled_for = rule.next_run_at
            if not existing:
                db.add(
                    SavingsEntry(
                        user_id=rule.user_id,
                        item_id=rule.item_id,
                        account_id=rule.account_id,
                        savings_rule_id=rule.id,
                        amount=rule.amount,
                        kind=SavingsEntryKind.recurring,
                        note=f"{rule.cadence.value} recurring deposit",
                        scheduled_for=scheduled_for,
                    )
                )
                count += 1
            rule.next_run_at = advance_run_at(rule.next_run_at, rule.cadence)
        apply_ready_status(db, rule.item)
    db.commit()
    return count

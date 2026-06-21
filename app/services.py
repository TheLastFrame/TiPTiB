from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re

from babel.core import UnknownLocaleError
from babel.numbers import NumberFormatError, get_currency_symbol, parse_decimal

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


MONEY_SPACE_RE = re.compile(r"[\s\u00a0\u202f]+")


@dataclass(frozen=True)
class GoalReachEstimate:
    reached_at: datetime
    deposit_count: int
    remaining: Decimal


@dataclass(frozen=True)
class ProjectedDeposit:
    scheduled_for: datetime
    amount: Decimal
    cumulative: Decimal


def _currency_tokens(currency: str | None, locale: str | None) -> list[str]:
    tokens = ["€", "$", "US$", "CA$", "C$", "£"]
    if currency:
        tokens.append(currency.upper())
        try:
            tokens.append(get_currency_symbol(currency.upper(), locale=locale))
        except (UnknownLocaleError, ValueError):
            pass
    return sorted({token for token in tokens if token}, key=len, reverse=True)


def _strip_currency_tokens(value: str, currency: str | None, locale: str | None) -> str:
    cleaned = value.strip()
    changed = True
    while changed:
        changed = False
        for token in _currency_tokens(currency, locale):
            if cleaned.upper().startswith(token.upper()):
                cleaned = cleaned[len(token) :].strip()
                changed = True
            if cleaned.upper().endswith(token.upper()):
                cleaned = cleaned[: -len(token)].strip()
                changed = True
    return cleaned


def _normalize_decimal_text(value: str) -> str:
    cleaned = MONEY_SPACE_RE.sub("", value)
    if not cleaned:
        raise ValueError("empty money amount")
    sign = ""
    if cleaned[0] in "+-":
        sign = cleaned[0]
        cleaned = cleaned[1:]
    if not cleaned or not re.fullmatch(r"\d[\d.,]*", cleaned):
        raise ValueError("invalid money amount")

    dot_count = cleaned.count(".")
    comma_count = cleaned.count(",")
    if dot_count and comma_count:
        decimal_sep = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
        grouping_sep = "," if decimal_sep == "." else "."
        integer, fraction = cleaned.rsplit(decimal_sep, 1)
        if not fraction.isdigit() or len(fraction) > 2:
            raise ValueError("invalid money amount")
        groups = integer.split(grouping_sep)
        if not groups[0].isdigit() or not 1 <= len(groups[0]) <= 3:
            raise ValueError("invalid money amount")
        if any(not group.isdigit() or len(group) != 3 for group in groups[1:]):
            raise ValueError("invalid money amount")
        return f"{sign}{''.join(groups)}.{fraction}"

    separator = "." if dot_count else "," if comma_count else ""
    if not separator:
        return f"{sign}{cleaned}"

    parts = cleaned.split(separator)
    if any(not part.isdigit() for part in parts):
        raise ValueError("invalid money amount")
    if len(parts) == 2 and len(parts[1]) <= 2:
        return f"{sign}{parts[0]}.{parts[1]}"
    if len(parts[0]) > 3 or any(len(part) != 3 for part in parts[1:]):
        raise ValueError("invalid money amount")
    return f"{sign}{''.join(parts)}"


def parse_money(value: object | None, *, locale: str | None = None, currency: str | None = None) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    if not isinstance(value, str):
        return Decimal(str(value)).quantize(Decimal("0.01"))

    cleaned = _strip_currency_tokens(value, currency, locale)
    try:
        return Decimal(_normalize_decimal_text(cleaned)).quantize(Decimal("0.01"))
    except ValueError:
        if "." in cleaned or "," in cleaned:
            raise
        if locale:
            parsed = parse_decimal(cleaned, locale=locale)
            return parsed.quantize(Decimal("0.01"))
        raise


def money(value: object | None, *, locale: str | None = None, currency: str | None = None) -> Decimal:
    try:
        return parse_money(value, locale=locale, currency=currency)
    except NumberFormatError as exc:
        raise ValueError("invalid money amount") from exc


def item_saved_total(db: Session, item_id: int) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(SavingsEntry.amount), 0)).where(SavingsEntry.item_id == item_id))
    return money(total)


def planned_saved_total(db: Session, user_id: int, wishlist_id: int | None = None) -> Decimal:
    query = (
        select(func.coalesce(func.sum(SavingsEntry.amount), 0))
        .join(Item, Item.id == SavingsEntry.item_id)
        .where(Item.user_id == user_id, Item.status.in_(PLANNED_TOTAL_STATUSES))
    )
    if wishlist_id is not None:
        query = query.where(Item.wishlist_id == wishlist_id)
    return money(db.scalar(query))


def item_target(item: Item) -> Decimal:
    amount = max(1, int(item.amount or 1))
    return item_unit_price(item) * amount


def item_unit_price(item: Item) -> Decimal:
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


def goal_reach_estimate(
    *,
    saved: Decimal,
    target: Decimal,
    rule: SavingsRule | None,
    now: datetime | None = None,
) -> GoalReachEstimate | None:
    if target <= 0 or saved >= target or rule is None or not rule.active:
        return None

    deposit_amount = money(rule.amount)
    if deposit_amount <= 0:
        return None

    remaining = money(target - saved)
    run_at = as_utc(rule.next_run_at)
    now = as_utc(now or datetime.now(timezone.utc))
    while run_at <= now:
        run_at = advance_run_at(run_at, rule.cadence)

    deposit_count = 0
    covered = Decimal("0.00")
    reached_at = run_at
    while covered < remaining:
        deposit_count += 1
        covered += deposit_amount
        reached_at = run_at
        run_at = advance_run_at(run_at, rule.cadence)

    return GoalReachEstimate(reached_at=reached_at, deposit_count=deposit_count, remaining=remaining)


def projected_recurring_deposits(
    *,
    saved: Decimal,
    target: Decimal,
    rule: SavingsRule | None,
    now: datetime | None = None,
) -> list[ProjectedDeposit]:
    if target <= 0 or saved >= target or rule is None or not rule.active:
        return []

    deposit_amount = money(rule.amount)
    if deposit_amount <= 0:
        return []

    run_at = as_utc(rule.next_run_at)
    now = as_utc(now or datetime.now(timezone.utc))
    while run_at <= now:
        run_at = advance_run_at(run_at, rule.cadence)

    cumulative = money(saved)
    deposits = []
    while cumulative < target:
        cumulative = money(cumulative + deposit_amount)
        deposits.append(ProjectedDeposit(scheduled_for=run_at, amount=deposit_amount, cumulative=cumulative))
        run_at = advance_run_at(run_at, rule.cadence)
    return deposits


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

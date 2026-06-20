from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Item, ItemStatus, RecurrenceCadence, SavingAccount, SavingsRule, User, Wishlist
from app.services import (
    account_breakdown,
    goal_reach_estimate,
    item_saved_total,
    item_target,
    item_unit_price,
    money,
    process_due_savings_rules,
)


def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_recurring_savings_create_ledger_entries_once():
    db = session()
    user = User(username="a", password_hash="x", display_name="A")
    db.add(user)
    db.flush()
    wishlist = Wishlist(user_id=user.id, name="House")
    account = SavingAccount(user_id=user.id, name="ING", is_default=True)
    db.add_all([wishlist, account])
    db.flush()
    item = Item(
        user_id=user.id,
        wishlist_id=wishlist.id,
        title="Sofa",
        rank=1,
        status=ItemStatus.saving,
        price_avg=Decimal("300.00"),
    )
    db.add(item)
    db.flush()
    db.add(
        SavingsRule(
            user_id=user.id,
            item_id=item.id,
            account_id=account.id,
            amount=Decimal("25.00"),
            cadence=RecurrenceCadence.weekly,
            next_run_at=datetime.now(timezone.utc) - timedelta(days=15),
            active=True,
        )
    )
    db.commit()

    created = process_due_savings_rules(db, datetime.now(timezone.utc))
    created_again = process_due_savings_rules(db, datetime.now(timezone.utc))

    assert created == 3
    assert created_again == 0
    assert item_saved_total(db, item.id) == Decimal("75.00")
    assert account_breakdown(db, user.id) == [("ING", Decimal("75.00"))]


def test_recurring_savings_mark_item_ready_when_target_reached():
    db = session()
    user = User(username="b", password_hash="x", display_name="B")
    db.add(user)
    db.flush()
    wishlist = Wishlist(user_id=user.id, name="Gadgets")
    db.add(wishlist)
    db.flush()
    item = Item(
        user_id=user.id,
        wishlist_id=wishlist.id,
        title="Headphones",
        rank=1,
        status=ItemStatus.saving,
        price_avg=Decimal("50.00"),
    )
    db.add(item)
    db.flush()
    db.add(
        SavingsRule(
            user_id=user.id,
            item_id=item.id,
            amount=Decimal("50.00"),
            cadence=RecurrenceCadence.daily,
            next_run_at=datetime.now(timezone.utc) - timedelta(days=1),
            active=True,
        )
    )
    db.commit()

    process_due_savings_rules(db, datetime.now(timezone.utc))
    db.refresh(item)

    assert item.status == ItemStatus.ready


def test_item_target_multiplies_by_amount_and_defaults_to_one():
    base_item = Item(title="Lamp", rank=1, price_avg=Decimal("25.00"))
    assert item_target(base_item) == Decimal("25.00")

    multi_item = Item(title="Chairs", rank=2, amount=4, price_avg=Decimal("25.00"))
    assert item_unit_price(multi_item) == Decimal("25.00")
    assert item_target(multi_item) == Decimal("100.00")

    actual_first_item = Item(
        title="Discount shelves",
        rank=3,
        amount=3,
        price_avg=Decimal("50.00"),
        actual_price=Decimal("12.00"),
    )
    assert item_target(actual_first_item) == Decimal("36.00")


def test_goal_reach_estimate_projects_daily_weekly_and_monthly_rules():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    daily = goal_reach_estimate(
        saved=Decimal("0.00"),
        target=Decimal("30.00"),
        rule=SavingsRule(
            amount=Decimal("10.00"),
            cadence=RecurrenceCadence.daily,
            next_run_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            active=True,
        ),
        now=now,
    )
    weekly = goal_reach_estimate(
        saved=Decimal("90.00"),
        target=Decimal("100.00"),
        rule=SavingsRule(
            amount=Decimal("25.00"),
            cadence=RecurrenceCadence.weekly,
            next_run_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
            active=True,
        ),
        now=now,
    )
    monthly = goal_reach_estimate(
        saved=Decimal("0.00"),
        target=Decimal("50.00"),
        rule=SavingsRule(
            amount=Decimal("20.00"),
            cadence=RecurrenceCadence.monthly,
            next_run_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
            active=True,
        ),
        now=now,
    )

    assert daily is not None
    assert daily.reached_at == datetime(2026, 1, 4, tzinfo=timezone.utc)
    assert daily.deposit_count == 3
    assert weekly is not None
    assert weekly.reached_at == datetime(2026, 1, 8, tzinfo=timezone.utc)
    assert weekly.deposit_count == 1
    assert monthly is not None
    assert monthly.reached_at == datetime(2026, 3, 28, tzinfo=timezone.utc)
    assert monthly.deposit_count == 3


def test_goal_reach_estimate_returns_none_without_projectable_rate():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    active_rule = SavingsRule(
        amount=Decimal("10.00"),
        cadence=RecurrenceCadence.weekly,
        next_run_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
        active=True,
    )
    inactive_rule = SavingsRule(
        amount=Decimal("10.00"),
        cadence=RecurrenceCadence.weekly,
        next_run_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
        active=False,
    )
    zero_rule = SavingsRule(
        amount=Decimal("0.00"),
        cadence=RecurrenceCadence.weekly,
        next_run_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
        active=True,
    )

    assert goal_reach_estimate(saved=Decimal("0.00"), target=Decimal("100.00"), rule=None, now=now) is None
    assert goal_reach_estimate(saved=Decimal("100.00"), target=Decimal("100.00"), rule=active_rule, now=now) is None
    assert goal_reach_estimate(saved=Decimal("0.00"), target=Decimal("0.00"), rule=active_rule, now=now) is None
    assert goal_reach_estimate(saved=Decimal("0.00"), target=Decimal("100.00"), rule=inactive_rule, now=now) is None
    assert goal_reach_estimate(saved=Decimal("0.00"), target=Decimal("100.00"), rule=zero_rule, now=now) is None


def test_money_accepts_plain_german_and_currency_formats():
    assert money("100.10", locale="de_AT", currency="EUR") == Decimal("100.10")
    assert money("100,10", locale="de_AT", currency="EUR") == Decimal("100.10")
    assert money("100,10 €", locale="de_AT", currency="EUR") == Decimal("100.10")
    assert money("€ 100,10", locale="de_AT", currency="EUR") == Decimal("100.10")
    assert money("1 000,10", locale="de_AT", currency="EUR") == Decimal("1000.10")
    assert money("1.000,10", locale="de_AT", currency="EUR") == Decimal("1000.10")


def test_money_accepts_us_and_canadian_formats():
    assert money("$1,000.10", locale="en_US", currency="USD") == Decimal("1000.10")
    assert money("CA$1,000.10", locale="en_CA", currency="CAD") == Decimal("1000.10")
    assert money("1 000,10 $", locale="fr_CA", currency="CAD") == Decimal("1000.10")


def test_money_rejects_malformed_text():
    for value in ("nope", "12,34,56", "1.00.10", "100,100,10 €"):
        try:
            money(value, locale="de_AT", currency="EUR")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{value!r} should not parse as money")

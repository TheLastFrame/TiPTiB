from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Item, ItemStatus, RecurrenceCadence, SavingAccount, SavingsRule, User, Wishlist
from app.services import account_breakdown, item_saved_total, item_target, item_unit_price, process_due_savings_rules


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

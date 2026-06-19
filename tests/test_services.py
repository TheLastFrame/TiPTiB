from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Item, ItemStatus, RecurrenceCadence, SavingAccount, SavingsRule, User, Wishlist
from app.services import account_breakdown, item_saved_total, process_due_savings_rules


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

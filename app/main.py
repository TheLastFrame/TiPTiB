from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.auth import authenticate_user, create_user, current_user, login_user, logout_user, users_exist
from app.config import get_settings
from app.database import SessionLocal, get_db, init_db
from app.models import (
    Category,
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
from app.scheduler import start_scheduler, stop_scheduler
from app.services import (
    ACTIVE_STATUSES,
    PLANNED_TOTAL_STATUSES,
    account_breakdown,
    add_savings_entry,
    ensure_defaults,
    item_saved_total,
    item_target,
    money,
    next_rank,
    progress_percent,
    process_due_savings_rules,
)

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def money_filter(value: object | None) -> str:
    amount = money(value)
    return f"{amount:,.2f} {settings.default_currency}".replace(",", " ")


templates.env.filters["money"] = money_filter
templates.env.globals["item_statuses"] = list(ItemStatus)
templates.env.globals["cadences"] = list(RecurrenceCadence)
templates.env.globals["settings"] = settings


def render(request: Request, name: str, context: dict[str, object] | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        name=name,
        request=request,
        context=context or {},
        status_code=status_code,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        if settings.bootstrap_username and settings.bootstrap_password and not users_exist(db):
            user = create_user(
                db,
                username=settings.bootstrap_username,
                password=settings.bootstrap_password,
                display_name=settings.bootstrap_username,
                is_admin=True,
            )
            ensure_defaults(db, user)
    finally:
        db.close()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def redirect(path: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(path, status_code=status_code)


def decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return money(value)
    except (InvalidOperation, ValueError):
        return None


def scoped_category(db: Session, user: User, category_id: int | None) -> Category | None:
    if not category_id:
        return None
    category = db.get(Category, category_id)
    if not category or category.user_id != user.id:
        raise HTTPException(status_code=404)
    return category


def scoped_account(db: Session, user: User, account_id: int | None) -> SavingAccount | None:
    if not account_id:
        return None
    account = db.get(SavingAccount, account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status_code=404)
    return account


def scoped_item(db: Session, user: User, item_id: int) -> Item:
    item = db.scalar(
        select(Item)
        .options(
            selectinload(Item.wishlist),
            selectinload(Item.category),
            selectinload(Item.savings_entries).selectinload(SavingsEntry.account),
            selectinload(Item.savings_rule).selectinload(SavingsRule.account),
        )
        .where(Item.id == item_id, Item.user_id == user.id)
    )
    if not item:
        raise HTTPException(status_code=404)
    return item


def scoped_wishlist(db: Session, user: User, wishlist_id: int) -> Wishlist:
    wishlist = db.scalar(select(Wishlist).where(Wishlist.id == wishlist_id, Wishlist.user_id == user.id))
    if not wishlist:
        raise HTTPException(status_code=404)
    return wishlist


def common_context(db: Session, user: User) -> dict[str, object]:
    return {
        "user": user,
        "wishlists": db.scalars(select(Wishlist).where(Wishlist.user_id == user.id).order_by(Wishlist.name)).all(),
        "categories": db.scalars(
            select(Category).where(Category.user_id == user.id, Category.archived.is_(False)).order_by(Category.name)
        ).all(),
        "accounts": db.scalars(
            select(SavingAccount)
            .where(SavingAccount.user_id == user.id, SavingAccount.archived.is_(False))
            .order_by(SavingAccount.is_default.desc(), SavingAccount.name)
        ).all(),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Annotated[Session, Depends(get_db)]):
    if not users_exist(db):
        return redirect("/setup")
    if not request.session.get("user_id"):
        return redirect("/login")
    return redirect("/dashboard")


@app.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    if users_exist(db):
        return redirect("/login")
    return render(request, "setup.html")


@app.post("/setup")
def setup(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    if users_exist(db):
        return redirect("/login")
    user = create_user(db, username=username, password=password, display_name=display_name or username, is_admin=True)
    ensure_defaults(db, user)
    login_user(request, user)
    return redirect("/dashboard")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    if not users_exist(db):
        return redirect("/setup")
    return render(request, "login.html", {"error": None})


@app.post("/login")
def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user = authenticate_user(db, username, password)
    if not user:
        return render(request, "login.html", {"error": "Check your username and password."}, status_code=400)
    ensure_defaults(db, user)
    login_user(request, user)
    return redirect("/dashboard")


@app.post("/logout")
def logout(request: Request):
    logout_user(request)
    return redirect("/login")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    process_due_savings_rules(db)
    ensure_defaults(db, user)
    active_items = db.scalars(
        select(Item)
        .where(Item.user_id == user.id, Item.status.in_(ACTIVE_STATUSES))
        .order_by(Item.updated_at.desc())
        .limit(6)
    ).all()
    ready_items = db.scalars(
        select(Item).where(Item.user_id == user.id, Item.status == ItemStatus.ready).order_by(Item.rank).limit(5)
    ).all()
    upcoming_rules = db.scalars(
        select(SavingsRule)
        .options(selectinload(SavingsRule.item), selectinload(SavingsRule.account))
        .where(SavingsRule.user_id == user.id, SavingsRule.active.is_(True))
        .order_by(SavingsRule.next_run_at)
        .limit(5)
    ).all()
    planned_total = sum(
        (
            item_target(item)
            for item in db.scalars(
                select(Item).where(Item.user_id == user.id, Item.status.in_(PLANNED_TOTAL_STATUSES))
            ).all()
        ),
        Decimal("0.00"),
    )
    saved_total = money(db.scalar(select(func.coalesce(func.sum(SavingsEntry.amount), 0)).where(SavingsEntry.user_id == user.id)))
    context = common_context(db, user) | {
        "request": request,
        "active": "dashboard",
        "planned_total": planned_total,
        "saved_total": saved_total,
        "ready_count": db.scalar(select(func.count(Item.id)).where(Item.user_id == user.id, Item.status == ItemStatus.ready)),
        "ready_items": ready_items,
        "recent_items": active_items,
        "upcoming_rules": upcoming_rules,
        "account_breakdown": account_breakdown(db, user.id),
    }
    return render(request, "dashboard.html", context)


@app.get("/lists", response_class=HTMLResponse)
def lists(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    rows = []
    for wishlist in db.scalars(select(Wishlist).where(Wishlist.user_id == user.id).order_by(Wishlist.name)).all():
        items = db.scalars(select(Item).where(Item.user_id == user.id, Item.wishlist_id == wishlist.id, Item.status.in_(ACTIVE_STATUSES))).all()
        total = sum((item_target(item) for item in items if item.status in PLANNED_TOTAL_STATUSES), Decimal("0.00"))
        saved = money(
            db.scalar(
                select(func.coalesce(func.sum(SavingsEntry.amount), 0))
                .join(Item, Item.id == SavingsEntry.item_id)
                .where(Item.user_id == user.id, Item.wishlist_id == wishlist.id)
            )
        )
        rows.append(
            {
                "wishlist": wishlist,
                "item_count": len(items),
                "total": total,
                "saved": saved,
                "progress": progress_percent(saved, total),
            }
        )
    return render(request, "lists.html", common_context(db, user) | {"active": "lists", "rows": rows})


@app.post("/lists")
def create_list(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
):
    db.add(Wishlist(user_id=user.id, name=name.strip(), description=description.strip() or None))
    db.commit()
    return redirect("/lists")


@app.get("/lists/{wishlist_id}", response_class=HTMLResponse)
def list_detail(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    wishlist_id: int,
    status: str = "",
    category_id: int = 0,
    account_id: int = 0,
):
    wishlist = scoped_wishlist(db, user, wishlist_id)
    query = (
        select(Item)
        .options(selectinload(Item.category), selectinload(Item.savings_entries).selectinload(SavingsEntry.account), selectinload(Item.savings_rule))
        .where(Item.user_id == user.id, Item.wishlist_id == wishlist.id)
        .order_by(Item.rank, Item.created_at)
    )
    if status:
        query = query.where(Item.status == ItemStatus(status))
    else:
        query = query.where(Item.status.in_(ACTIVE_STATUSES))
    if category_id:
        query = query.where(Item.category_id == category_id)
    items = db.scalars(query).all()
    if account_id:
        items = [item for item in items if any(entry.account_id == account_id for entry in item.savings_entries)]
    item_cards = [
        {
            "item": item,
            "saved": item_saved_total(db, item.id),
            "target": item_target(item),
            "progress": progress_percent(item_saved_total(db, item.id), item_target(item)),
        }
        for item in items
    ]
    return render(
        request,
        "list_detail.html",
        common_context(db, user)
        | {
            "active": "lists",
            "wishlist": wishlist,
            "item_cards": item_cards,
            "selected_status": status,
            "selected_category_id": category_id,
            "selected_account_id": account_id,
        },
    )


@app.post("/items")
def create_item(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    wishlist_id: Annotated[int, Form()],
    title: Annotated[str, Form()],
    category_id: Annotated[int, Form()] = 0,
    status: Annotated[str, Form()] = ItemStatus.idea.value,
    price_min: Annotated[str, Form()] = "",
    price_avg: Annotated[str, Form()] = "",
    price_max: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    wishlist = scoped_wishlist(db, user, wishlist_id)
    category = scoped_category(db, user, category_id)
    item = Item(
        user_id=user.id,
        wishlist_id=wishlist.id,
        category_id=category.id if category else None,
        title=title.strip(),
        status=ItemStatus(status),
        rank=next_rank(db, user.id, wishlist.id),
        price_min=decimal_or_none(price_min),
        price_avg=decimal_or_none(price_avg),
        price_max=decimal_or_none(price_max),
        url=url.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(item)
    db.commit()
    return redirect(f"/items/{item.id}")


@app.get("/items/new", response_class=HTMLResponse)
def new_item(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    wishlist_id: int = 0,
):
    ensure_defaults(db, user)
    return render(
        request,
        "item_form.html",
        common_context(db, user) | {"active": "add", "item": None, "wishlist_id": wishlist_id},
    )


@app.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    item_id: int,
    tab: str = "overview",
):
    item = scoped_item(db, user, item_id)
    saved = item_saved_total(db, item.id)
    target = item_target(item)
    selected_tab = tab if tab in {"overview", "budget", "details"} else "overview"
    return render(
        request,
        "item_detail.html",
        common_context(db, user)
        | {
            "active": "lists",
            "item": item,
            "selected_tab": selected_tab,
            "saved": saved,
            "target": target,
            "progress": progress_percent(saved, target),
        },
    )


@app.post("/items/{item_id}")
def update_item(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    item_id: int,
    title: Annotated[str, Form()],
    wishlist_id: Annotated[int, Form()],
    category_id: Annotated[int, Form()] = 0,
    status: Annotated[str, Form()] = ItemStatus.idea.value,
    rank: Annotated[int, Form()] = 0,
    price_min: Annotated[str, Form()] = "",
    price_avg: Annotated[str, Form()] = "",
    price_max: Annotated[str, Form()] = "",
    actual_price: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    item = scoped_item(db, user, item_id)
    wishlist = scoped_wishlist(db, user, wishlist_id)
    item.title = title.strip()
    item.wishlist_id = wishlist.id
    category = scoped_category(db, user, category_id)
    item.category_id = category.id if category else None
    item.status = ItemStatus(status)
    item.rank = rank
    item.price_min = decimal_or_none(price_min)
    item.price_avg = decimal_or_none(price_avg)
    item.price_max = decimal_or_none(price_max)
    item.actual_price = decimal_or_none(actual_price)
    item.url = url.strip() or None
    item.notes = notes.strip() or None
    db.commit()
    return redirect(f"/items/{item.id}")


@app.post("/items/{item_id}/savings")
def create_savings_entry(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    item_id: int,
    amount: Annotated[str, Form()],
    account_id: Annotated[int, Form()] = 0,
    note: Annotated[str, Form()] = "",
):
    item = scoped_item(db, user, item_id)
    account = scoped_account(db, user, account_id)
    add_savings_entry(
        db,
        user_id=user.id,
        item=item,
        amount=money(amount),
        account_id=account.id if account else None,
        kind=SavingsEntryKind.manual,
        note=note.strip() or None,
    )
    return redirect(f"/items/{item.id}?tab=budget")


@app.post("/items/{item_id}/recurring-rule")
def upsert_recurring_rule(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    item_id: int,
    amount: Annotated[str, Form()],
    cadence: Annotated[str, Form()],
    account_id: Annotated[int, Form()] = 0,
    next_run_at: Annotated[str, Form()] = "",
    active: Annotated[str | None, Form()] = None,
):
    item = scoped_item(db, user, item_id)
    account = scoped_account(db, user, account_id)
    run_at = datetime.fromisoformat(next_run_at) if next_run_at else datetime.now(timezone.utc)
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    rule = item.savings_rule or SavingsRule(user_id=user.id, item_id=item.id)
    rule.amount = money(amount)
    rule.cadence = RecurrenceCadence(cadence)
    rule.account_id = account.id if account else None
    rule.next_run_at = run_at
    rule.active = active == "on"
    item.status = ItemStatus.saving if item.status in (ItemStatus.idea, ItemStatus.planned) else item.status
    db.add(rule)
    db.commit()
    return redirect(f"/items/{item.id}?tab=budget")


@app.post("/categories")
def create_category(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    name: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#8b8f78",
):
    db.add(Category(user_id=user.id, name=name.strip(), color=color))
    db.commit()
    return redirect("/settings")


@app.get("/accounts", response_class=HTMLResponse)
def accounts(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    rows = []
    for account in db.scalars(select(SavingAccount).where(SavingAccount.user_id == user.id).order_by(SavingAccount.archived, SavingAccount.name)).all():
        total = money(db.scalar(select(func.coalesce(func.sum(SavingsEntry.amount), 0)).where(SavingsEntry.account_id == account.id)))
        rows.append({"account": account, "total": total})
    return render(request, "accounts.html", common_context(db, user) | {"active": "accounts", "rows": rows})


@app.post("/accounts")
def create_account(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    name: Annotated[str, Form()],
    is_default: Annotated[str | None, Form()] = None,
):
    if is_default:
        db.query(SavingAccount).filter(SavingAccount.user_id == user.id).update({"is_default": False})
    db.add(SavingAccount(user_id=user.id, name=name.strip(), is_default=bool(is_default)))
    db.commit()
    return redirect("/accounts")


@app.post("/accounts/{account_id}")
def update_account(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    account_id: int,
    name: Annotated[str, Form()],
    archived: Annotated[str | None, Form()] = None,
    is_default: Annotated[str | None, Form()] = None,
):
    account = db.get(SavingAccount, account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status_code=404)
    if is_default:
        db.query(SavingAccount).filter(SavingAccount.user_id == user.id).update({"is_default": False})
    account.name = name.strip()
    account.archived = bool(archived)
    account.is_default = bool(is_default)
    db.commit()
    return redirect("/accounts")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    return render(request, "settings.html", common_context(db, user) | {"active": "settings"})


@app.post("/settings/users")
def create_user_from_settings(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    if not user.is_admin:
        raise HTTPException(status_code=403)
    new_user = create_user(db, username=username, password=password, display_name=display_name or username)
    ensure_defaults(db, new_user)
    return redirect("/settings")


@app.get("/manifest.webmanifest")
def manifest() -> dict[str, object]:
    return {
        "name": "TiPTiB",
        "short_name": "TiPTiB",
        "description": "Today I plan, Tomorrow I buy.",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#f3fbf6",
        "theme_color": "#0f766e",
        "icons": [{"src": "/static/icons/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }

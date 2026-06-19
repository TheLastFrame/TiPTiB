from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth import (
    authenticate_user,
    check_login_rate_limit,
    create_user,
    current_user,
    login_user,
    logout_user,
    record_login_result,
    users_exist,
)
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
from app.security import (
    get_csrf_token,
    security_headers,
    validate_csrf,
    validate_first_run_setup_allowed,
    validate_security_settings,
)

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def money_filter(value: object | None) -> str:
    amount = money(value)
    return f"{amount:,.2f} {settings.default_currency}".replace(",", " ")


templates.env.filters["money"] = money_filter
templates.env.globals["item_statuses"] = list(ItemStatus)
templates.env.globals["cadences"] = list(RecurrenceCadence)
templates.env.globals["settings"] = settings


def render(request: Request, name: str, context: dict[str, object] | None = None, status_code: int = 200):
    template_context = dict(context or {})
    template_context.setdefault("csrf_token", get_csrf_token(request))
    return templates.TemplateResponse(
        name=name,
        request=request,
        context=template_context,
        status_code=status_code,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings(settings)
    init_db()
    db = SessionLocal()
    try:
        has_users = users_exist(db)
        validate_first_run_setup_allowed(settings, has_users)
        if settings.bootstrap_username and settings.bootstrap_password and not has_users:
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
    https_only=settings.secure_session_cookie,
    max_age=settings.session_max_age_seconds,
)
if settings.allowed_host_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in security_headers(settings).items():
        response.headers.setdefault(header, value)
    return response


def redirect(path: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(path, status_code=status_code)


def decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return money(value)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid money amount.")


def decimal_required(value: str, field: str = "amount") -> Decimal:
    if not value.strip():
        raise HTTPException(status_code=400, detail=f"Invalid {field}.")
    try:
        return money(value)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}.") from exc


def item_status_or_400(value: str) -> ItemStatus:
    try:
        return ItemStatus(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid item status.") from exc


def cadence_or_400(value: str) -> RecurrenceCadence:
    try:
        return RecurrenceCadence(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid recurrence cadence.") from exc


def parse_datetime_or_400(value: str) -> datetime:
    try:
        run_at = datetime.fromisoformat(value) if value else datetime.now(timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid next run date.") from exc
    if run_at.tzinfo is None:
        return run_at.replace(tzinfo=timezone.utc)
    return run_at


def external_url_or_none(value: str) -> str | None:
    url = value.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Links must use http or https.")
    return url


def color_or_400(value: str) -> str:
    if not COLOR_RE.fullmatch(value.strip()):
        raise HTTPException(status_code=400, detail="Invalid color.")
    return value.strip()


def required_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} is required.")
    return cleaned


def commit_or_400(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=detail) from exc


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


def sort_price_value(item: Item, sort_by: str) -> Decimal | int | None:
    """Price sort fallbacks are product behavior, not DB convenience.

    max_price: max -> avg -> actual -> min
    actual_price: actual -> avg -> min -> max
    """
    if sort_by == "max_price":
        return item.price_max or item.price_avg or item.actual_price or item.price_min
    if sort_by == "actual_price":
        return item.actual_price or item.price_avg or item.price_min or item.price_max
    return item.rank


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
    if settings.is_production and not settings.allow_web_setup:
        raise HTTPException(status_code=403, detail="Web setup is disabled.")
    return render(request, "setup.html", {"error": None})


@app.post("/setup")
def setup(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    csrf: Annotated[None, Depends(validate_csrf)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    if users_exist(db):
        return redirect("/login")
    if settings.is_production and not settings.allow_web_setup:
        raise HTTPException(status_code=403, detail="Web setup is disabled.")
    try:
        user = create_user(db, username=username, password=password, display_name=display_name or username, is_admin=True)
    except ValueError as exc:
        return render(request, "setup.html", {"error": str(exc)}, status_code=400)
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
    csrf: Annotated[None, Depends(validate_csrf)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    check_login_rate_limit(request, username)
    user = authenticate_user(db, username, password)
    if not user:
        record_login_result(request, username, success=False)
        return render(request, "login.html", {"error": "Check your username and password."}, status_code=400)
    record_login_result(request, username, success=True)
    ensure_defaults(db, user)
    login_user(request, user)
    return redirect("/dashboard")


@app.post("/logout")
def logout(request: Request, csrf: Annotated[None, Depends(validate_csrf)]):
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
    csrf: Annotated[None, Depends(validate_csrf)],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
):
    db.add(Wishlist(user_id=user.id, name=required_text(name, "Wishlist name"), description=description.strip() or None))
    commit_or_400(db, "A wishlist with that name already exists.")
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
    show_sum: bool = False,
    sort_by: str = "rank",
    sort_dir: str = "asc",
):
    wishlist = scoped_wishlist(db, user, wishlist_id)
    selected_status = status if status in {item_status.value for item_status in ItemStatus} else ""
    selected_category_id = category_id
    if selected_category_id and not db.scalar(
        select(Category.id).where(Category.id == selected_category_id, Category.user_id == user.id)
    ):
        selected_category_id = 0
    selected_account_id = account_id
    if selected_account_id and not db.scalar(
        select(SavingAccount.id).where(SavingAccount.id == selected_account_id, SavingAccount.user_id == user.id)
    ):
        selected_account_id = 0
    selected_sort_by = sort_by if sort_by in {"rank", "max_price", "actual_price"} else "rank"
    selected_sort_dir = sort_dir if sort_dir in {"asc", "desc"} else "asc"
    total_active_items = db.scalar(
        select(func.count(Item.id)).where(
            Item.user_id == user.id,
            Item.wishlist_id == wishlist.id,
            Item.status.in_(ACTIVE_STATUSES),
        )
    )
    filters_applied = bool(selected_status or selected_category_id or selected_account_id)
    query = (
        select(Item)
        .options(selectinload(Item.category), selectinload(Item.savings_entries).selectinload(SavingsEntry.account), selectinload(Item.savings_rule))
        .where(Item.user_id == user.id, Item.wishlist_id == wishlist.id)
        .order_by(Item.rank, Item.created_at)
    )
    if selected_status:
        query = query.where(Item.status == ItemStatus(selected_status))
    else:
        query = query.where(Item.status.in_(ACTIVE_STATUSES))
    if selected_category_id:
        query = query.where(Item.category_id == selected_category_id)
    items = db.scalars(query).all()
    if selected_account_id:
        items = [item for item in items if any(entry.account_id == selected_account_id for entry in item.savings_entries)]
    def sort_key(item: Item):
        value = sort_price_value(item, selected_sort_by)
        if value is None:
            return (1, Decimal("0.00"))
        if selected_sort_dir == "desc":
            return (0, -value)
        return (0, value)

    items = sorted(items, key=sort_key)
    item_cards = []
    for item in items:
        saved = item_saved_total(db, item.id)
        target = item_target(item)
        item_cards.append(
            {
                "item": item,
                "saved": saved,
                "target": target,
                "progress": progress_percent(saved, target),
            }
        )
    filtered_target_total = sum((card["target"] for card in item_cards), Decimal("0.00"))
    filtered_saved_total = sum((card["saved"] for card in item_cards), Decimal("0.00"))
    return render(
        request,
        "list_detail.html",
        common_context(db, user)
        | {
            "active": "lists",
            "wishlist": wishlist,
            "item_cards": item_cards,
            "selected_status": selected_status,
            "selected_category_id": selected_category_id,
            "selected_account_id": selected_account_id,
            "selected_sort_by": selected_sort_by,
            "selected_sort_dir": selected_sort_dir,
            "next_sort_dir": "desc" if selected_sort_dir == "asc" else "asc",
            "filters_applied": filters_applied,
            "total_active_items": total_active_items or 0,
            "show_sum": show_sum,
            "filtered_item_count": len(item_cards),
            "filtered_target_total": filtered_target_total,
            "filtered_saved_total": filtered_saved_total,
            "filtered_progress": progress_percent(filtered_saved_total, filtered_target_total),
        },
    )


@app.post("/items")
def create_item(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    csrf: Annotated[None, Depends(validate_csrf)],
    wishlist_id: Annotated[int, Form()],
    title: Annotated[str, Form()],
    category_id: Annotated[int, Form()] = 0,
    status: Annotated[str, Form()] = ItemStatus.idea.value,
    price_min: Annotated[str, Form()] = "",
    price_avg: Annotated[str, Form()] = "",
    price_max: Annotated[str, Form()] = "",
    actual_price: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    wishlist = scoped_wishlist(db, user, wishlist_id)
    category = scoped_category(db, user, category_id)
    item = Item(
        user_id=user.id,
        wishlist_id=wishlist.id,
        category_id=category.id if category else None,
        title=required_text(title, "Item title"),
        status=item_status_or_400(status),
        rank=next_rank(db, user.id, wishlist.id),
        price_min=decimal_or_none(price_min),
        price_avg=decimal_or_none(price_avg),
        price_max=decimal_or_none(price_max),
        actual_price=decimal_or_none(actual_price),
        url=external_url_or_none(url),
        notes=notes.strip() or None,
    )
    db.add(item)
    commit_or_400(db, "Unable to create item.")
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
    csrf: Annotated[None, Depends(validate_csrf)],
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
    item.title = required_text(title, "Item title")
    item.wishlist_id = wishlist.id
    category = scoped_category(db, user, category_id)
    item.category_id = category.id if category else None
    item.status = item_status_or_400(status)
    item.rank = rank
    item.price_min = decimal_or_none(price_min)
    item.price_avg = decimal_or_none(price_avg)
    item.price_max = decimal_or_none(price_max)
    item.actual_price = decimal_or_none(actual_price)
    item.url = external_url_or_none(url)
    item.notes = notes.strip() or None
    commit_or_400(db, "Unable to update item.")
    return redirect(f"/items/{item.id}")


@app.post("/items/{item_id}/savings")
def create_savings_entry(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    csrf: Annotated[None, Depends(validate_csrf)],
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
        amount=decimal_required(amount),
        account_id=account.id if account else None,
        kind=SavingsEntryKind.manual,
        note=note.strip() or None,
    )
    return redirect(f"/items/{item.id}?tab=budget")


@app.post("/items/{item_id}/recurring-rule")
def upsert_recurring_rule(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    csrf: Annotated[None, Depends(validate_csrf)],
    item_id: int,
    amount: Annotated[str, Form()],
    cadence: Annotated[str, Form()],
    account_id: Annotated[int, Form()] = 0,
    next_run_at: Annotated[str, Form()] = "",
    active: Annotated[str | None, Form()] = None,
):
    item = scoped_item(db, user, item_id)
    account = scoped_account(db, user, account_id)
    run_at = parse_datetime_or_400(next_run_at)
    rule = item.savings_rule or SavingsRule(user_id=user.id, item_id=item.id)
    rule.amount = decimal_required(amount)
    rule.cadence = cadence_or_400(cadence)
    rule.account_id = account.id if account else None
    rule.next_run_at = run_at
    rule.active = active == "on"
    item.status = ItemStatus.saving if item.status in (ItemStatus.idea, ItemStatus.planned) else item.status
    db.add(rule)
    commit_or_400(db, "Unable to save recurring rule.")
    return redirect(f"/items/{item.id}?tab=budget")


@app.post("/categories")
def create_category(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    csrf: Annotated[None, Depends(validate_csrf)],
    name: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#8b8f78",
):
    db.add(Category(user_id=user.id, name=required_text(name, "Category name"), color=color_or_400(color)))
    commit_or_400(db, "A category with that name already exists.")
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
    csrf: Annotated[None, Depends(validate_csrf)],
    name: Annotated[str, Form()],
    is_default: Annotated[str | None, Form()] = None,
):
    if is_default:
        db.query(SavingAccount).filter(SavingAccount.user_id == user.id).update({"is_default": False})
    db.add(SavingAccount(user_id=user.id, name=required_text(name, "Account name"), is_default=bool(is_default)))
    commit_or_400(db, "An account with that name already exists.")
    return redirect("/accounts")


@app.post("/accounts/{account_id}")
def update_account(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    csrf: Annotated[None, Depends(validate_csrf)],
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
    account.name = required_text(name, "Account name")
    account.archived = bool(archived)
    account.is_default = bool(is_default)
    commit_or_400(db, "An account with that name already exists.")
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
    csrf: Annotated[None, Depends(validate_csrf)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    if not user.is_admin:
        raise HTTPException(status_code=403)
    try:
        new_user = create_user(db, username=username, password=password, display_name=display_name or username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

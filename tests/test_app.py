import html
import json
import os
import re
import tempfile

os.environ["TIPTIB_DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["TIPTIB_SECRET_KEY"] = "test-secret"
os.environ["TIPTIB_SCHEDULER_ENABLED"] = "false"
os.environ["TIPTIB_RUN_MIGRATIONS_ON_STARTUP"] = "false"

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app.auth import reset_login_throttle  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import security_headers, validate_first_run_setup_allowed, validate_security_settings  # noqa: E402
from app.version import RELEASES_URL, SOURCE_URL, load_version_info  # noqa: E402

ADMIN_PASSWORD = "long-test-password"


@pytest.fixture(autouse=True)
def reset_db():
    reset_login_throttle()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    reset_login_throttle()


def extract_csrf(response_text: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response_text)
    assert match, response_text
    return match.group(1)


def csrf_from(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    return extract_csrf(response.text)


def with_csrf(token: str, data: dict[str, object] | None = None) -> dict[str, object]:
    return {"csrf_token": token} | dict(data or {})


def created_item_id(location: str) -> int:
    return int(location.rstrip("/").split("/")[-1])


def chart_payload(response_text: str) -> dict[str, object]:
    match = re.search(r"data-chart='([^']+)'", response_text)
    assert match, response_text
    return json.loads(html.unescape(match.group(1)))


def setup_admin(client: TestClient) -> None:
    token = csrf_from(client, "/setup")
    response = client.post(
        "/setup",
        data=with_csrf(token, {"display_name": "Fabian", "username": "fabian", "password": ADMIN_PASSWORD}),
        follow_redirects=False,
    )
    assert response.status_code == 303


def login(client: TestClient, username: str = "fabian", password: str = ADMIN_PASSWORD) -> None:
    token = csrf_from(client, "/login")
    response = client.post(
        "/login",
        data=with_csrf(token, {"username": username, "password": password}),
        follow_redirects=False,
    )
    assert response.status_code == 303


def logout(client: TestClient) -> None:
    token = csrf_from(client, "/settings")
    response = client.post("/logout", data=with_csrf(token), follow_redirects=False)
    assert response.status_code == 303


def test_setup_login_create_item_and_pwa_routes():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Set up TiPTiB" in response.text
        assert "data-back-button" not in response.text

        setup_admin(client)

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "buy plan" in response.text
        assert "data-back-button" not in response.text

        token = csrf_from(client, "/items/new")
        response = client.get("/items/new")
        assert response.status_code == 200
        assert "data-back-button" not in response.text
        assert 'name="rank"' in response.text

        response = client.get("/lists")
        assert response.status_code == 200
        assert "Your plans" in response.text
        assert 'href="/lists/1"' in response.text
        assert "data-back-button" not in response.text

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Maybe someday", "status": "idea", "price_avg": "999"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        created_item_url = response.headers["location"]
        created_item = client.get(created_item_url)
        assert 'data-back-button aria-label="Go back" data-back-url="/lists/1"' in created_item.text
        assert "#1" in created_item.text
        response = client.get("/dashboard")
        assert "999.00 EUR" not in response.text
        response = client.get("/lists")
        assert "999.00 EUR planned" not in response.text

        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {
                    "wishlist_id": 1,
                    "title": "Dining table",
                    "status": "planned",
                    "price_min": "300",
                    "price_avg": "450",
                    "price_max": "700",
                    "amount": "2",
                    "rank": "7",
                    "reason": "Big enough for dinner with friends",
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/items/")
        ranked_item = client.get(response.headers["location"])
        assert "#7" in ranked_item.text

        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {
                    "wishlist_id": 1,
                    "title": "Desk lamp",
                    "status": "planned",
                    "price_min": "20",
                    "price_avg": "35",
                    "price_max": "80",
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {
                    "wishlist_id": 1,
                    "title": "Fallback speaker",
                    "status": "planned",
                    "price_avg": "650",
                    "actual_price": "15",
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {
                    "wishlist_id": 1,
                    "title": "Actual-first shelf",
                    "status": "planned",
                    "price_min": "120",
                    "price_max": "900",
                    "actual_price": "40",
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/lists/1")
        assert response.status_code == 200
        assert "Dining table" in response.text
        assert 'data-back-button aria-label="Go back"' in response.text
        assert 'data-back-url="/lists"' in response.text
        assert 'href="/items/2"' in response.text
        assert '<details class="filter-drawer">' in response.text
        assert '<option value="" selected>Active</option>' in response.text
        assert '<option value="all" >All statuses</option>' in response.text
        for status in ("idea", "planned", "saving", "ready", "bought", "skipped"):
            assert f'<option value="{status}"' in response.text
        assert "shown</span>" not in response.text
        assert "data-submit-on-change" in response.text
        assert "onchange=" not in response.text
        assert "onclick=" not in response.text

        response = client.get("/lists/1?show_sum=true")
        assert response.status_code == 200
        assert "Filtered sum" in response.text
        assert "1 989.00 EUR" in response.text

        response = client.get("/lists/1?status=planned&show_sum=true")
        assert response.status_code == 200
        assert "4/5 shown" in response.text
        assert "990.00 EUR" in response.text
        assert "999.00 EUR" not in response.text

        response = client.get("/lists/1?status=planned&sort_by=max_price&sort_dir=desc")
        assert response.status_code == 200
        assert response.text.index("Dining table") < response.text.index("Actual-first shelf")
        assert response.text.index("Actual-first shelf") < response.text.index("Fallback speaker")

        response = client.get("/lists/1?status=planned&sort_by=max_price&sort_dir=asc")
        assert response.status_code == 200
        assert response.text.index("Desk lamp") < response.text.index("Dining table")

        response = client.get("/lists/1?status=planned&sort_by=actual_price&sort_dir=asc")
        assert response.status_code == 200
        assert response.text.index("Fallback speaker") < response.text.index("Desk lamp")
        assert response.text.index("Desk lamp") < response.text.index("Actual-first shelf")

        response = client.get("/lists/1?status=planned&sort_by=actual_price&sort_dir=desc")
        assert response.status_code == 200
        assert response.text.index("Dining table") < response.text.index("Desk lamp")

        item_url = response = client.get("/items/1")
        assert item_url.status_code == 200
        assert "Overview" in item_url.text
        assert 'data-back-button aria-label="Go back"' in item_url.text
        assert 'data-back-url="/lists/1"' in item_url.text
        assert "Open budget" not in item_url.text
        assert "0% saved" not in item_url.text
        assert "Amount</span>" not in item_url.text
        budget_response = client.get("/items/1?tab=budget")
        assert budget_response.status_code == 200
        assert "Recurring deposit" in budget_response.text
        details_response = client.get("/items/1?tab=details")
        assert details_response.status_code == 200
        assert "Save item" in details_response.text

        item_url = client.get("/items/2")
        assert item_url.status_code == 200
        assert "900.00 EUR" in item_url.text
        assert "Single price</span><strong>450.00 EUR</strong>" in item_url.text
        assert "Big enough for dinner with friends" in item_url.text
        assert "Amount</span><strong>2</strong>" in item_url.text

        token = csrf_from(client, "/items/2?tab=details")
        response = client.post(
            "/items/2",
            data=with_csrf(
                token,
                {
                    "title": "Dining table",
                    "wishlist_id": 1,
                    "rank": 2,
                    "status": "bought",
                    "price_min": "300",
                    "price_avg": "450",
                    "price_max": "700",
                    "actual_price": "425",
                    "amount": "2",
                    "reason": "Big enough for dinner with friends",
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        response = client.get("/history")
        assert response.status_code == 200
        assert "Dining table" in response.text
        assert 'data-back-button aria-label="Go back"' in response.text

        response = client.get("/lists/1")
        assert response.status_code == 200
        assert "Dining table" not in response.text
        assert "Maybe someday" in response.text

        response = client.get("/lists/1?status=all")
        assert response.status_code == 200
        assert "Dining table" in response.text
        assert "Maybe someday" in response.text
        assert "5/5 shown" in response.text
        assert '<option value="all" selected>All statuses</option>' in response.text

        response = client.get("/lists/1?status=bought")
        assert response.status_code == 200
        assert "Dining table" in response.text
        assert "Maybe someday" not in response.text
        assert "1/5 shown" in response.text

        response = client.get("/lists/1?status=not-a-status")
        assert response.status_code == 200
        assert "Dining table" not in response.text
        assert "Maybe someday" in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "USD", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        response = client.get("/settings")
        assert "USD" in response.text
        assert "UTC" in response.text
        assert "data-back-button" not in response.text

        response = client.get("/accounts")
        assert response.status_code == 200
        assert "data-back-button" not in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/password",
            data=with_csrf(token, {"current_password": ADMIN_PASSWORD, "new_password": "new-long-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        response = client.get("/login")
        assert response.status_code == 200
        assert "data-back-button" not in response.text
        login(client, password="new-long-password")

        manifest = client.get("/manifest.webmanifest").json()
        assert manifest["short_name"] == "TiPTiB"
        assert manifest["share_target"] == {
            "action": "/items/new",
            "method": "GET",
            "params": {"title": "title", "text": "text", "url": "url"},
        }
        assert client.get("/static/sw.js").status_code == 200
        app_js = client.get("/static/app.js")
        assert app_js.status_code == 200
        assert 'window.addEventListener("pageshow"' in app_js.text
        assert 'window.location.pathname === "/lists"' in app_js.text
        assert "window.location.reload()" in app_js.text


def test_saved_planning_summaries_exclude_bought_and_skipped_items():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Active camera", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        active_item_id = created_item_id(response.headers["location"])

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bought headphones", "status": "bought", "price_avg": "80"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        bought_item_id = created_item_id(response.headers["location"])

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Skipped tablet", "status": "skipped", "price_avg": "120"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        skipped_item_id = created_item_id(response.headers["location"])

        token = csrf_from(client, f"/items/{active_item_id}?tab=budget")
        response = client.post(
            f"/items/{active_item_id}/savings",
            data=with_csrf(token, {"amount": "25", "account_id": 1, "note": "Active saved"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, f"/items/{bought_item_id}?tab=budget")
        response = client.post(
            f"/items/{bought_item_id}/savings",
            data=with_csrf(token, {"amount": "40", "account_id": 1, "note": "Bought saved"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, f"/items/{skipped_item_id}?tab=budget")
        response = client.post(
            f"/items/{skipped_item_id}/savings",
            data=with_csrf(token, {"amount": "60", "account_id": 1, "note": "Skipped saved"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "Virtually saved</span><strong>25.00 EUR</strong>" in response.text
        assert "Planned</span><strong>100.00 EUR</strong>" in response.text
        assert "Cash</span><strong>125.00 EUR</strong>" in response.text

        response = client.get("/lists")
        assert response.status_code == 200
        assert '<div class="row"><span>100.00 EUR planned</span><strong>25.00 EUR</strong></div>' in response.text
        assert "125.00 EUR</strong></div>" not in response.text

        response = client.get("/lists/1?status=all&show_sum=true")
        assert response.status_code == 200
        assert "Bought headphones" in response.text
        assert "Skipped tablet" in response.text
        assert '<span class="chip">25.00 EUR saved</span>' in response.text
        assert '<span class="chip">125.00 EUR saved</span>' not in response.text


def test_recurring_rule_visibility_and_blank_next_run_preserves_schedule():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "EUR", "timezone_name": "Europe/Vienna"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Savings camera", "status": "planned", "price_avg": "500"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(
                token,
                {"amount": "25", "cadence": "monthly", "account_id": 0, "next_run_at": "2026-01-01T00:00", "active": "on"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get(f"/items/{item_id}?tab=budget")
        assert response.status_code == 200
        assert "Active" in response.text
        assert "next run: 2026-01-01 00:00" in response.text
        assert 'name="next_run_at" type="datetime-local" value="2026-01-01T00:00"' in response.text
        assert re.search(r'<input type="checkbox" name="active" checked>', response.text)

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(token, {"amount": "25", "cadence": "monthly", "account_id": 0, "next_run_at": ""}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get(f"/items/{item_id}?tab=budget")
        assert response.status_code == 200
        assert "Inactive" in response.text
        assert "next run: 2026-01-01 00:00" in response.text
        assert 'name="next_run_at" type="datetime-local" value="2026-01-01T00:00"' in response.text
        assert not re.search(r'<input type="checkbox" name="active" checked>', response.text)

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(token, {"amount": "25", "cadence": "monthly", "account_id": 0, "next_run_at": "", "active": "on"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get(f"/items/{item_id}?tab=budget")
        assert response.status_code == 200
        assert "Active" in response.text
        assert "next run: 2026-01-01 00:00" in response.text
        assert re.search(r'<input type="checkbox" name="active" checked>', response.text)


def test_dashboard_upcoming_deposits_show_next_run():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "EUR", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Coffee grinder", "status": "planned", "price_avg": "160"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(
                token,
                {"amount": "10", "cadence": "weekly", "account_id": 0, "next_run_at": "2026-08-03T04:05", "active": "on"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "Coffee grinder" in response.text
        assert "next run: 2026-08-03 04:05" in response.text

        response = client.get(f"/items/{item_id}")
        assert response.status_code == 200
        assert "Funded by</span><strong>2026-11-16 04:05</strong>" in response.text

        response = client.get(f"/items/{item_id}?tab=budget")
        assert response.status_code == 200
        assert "Funded by 2026-11-16 04:05" in response.text


def test_share_target_prefills_new_item_form():
    with TestClient(app) as client:
        setup_admin(client)

        url = "https://www.amazon.de/dp/B08N5WRWNW?tag=wishlist"
        response = client.get("/items/new", params={"title": "Echo Dot", "url": url})

        assert response.status_code == 200
        assert f'name="title" required placeholder="Dining table" value="{html.escape("Echo Dot")}"' in response.text
        assert f'name="url" type="url" value="{html.escape(url)}"' in response.text
        assert client.get("/lists/1").text.count("Echo Dot") == 0


def test_share_target_prefills_amazon_url_from_text():
    with TestClient(app) as client:
        setup_admin(client)

        amazon_text = "Check this out https://www.amazon.com/dp/B0TEST1234?ref_=share"
        response = client.get("/items/new", params={"title": "USB-C Charger", "text": amazon_text})

        assert response.status_code == 200
        assert 'name="title" required placeholder="Dining table" value="USB-C Charger"' in response.text
        assert 'name="url" type="url" value="https://www.amazon.com/dp/B0TEST1234?ref_=share"' in response.text
        assert ">Check this out</textarea>" in response.text


def test_share_target_ignores_unsafe_links_and_falls_back_to_text_title():
    with TestClient(app) as client:
        setup_admin(client)

        response = client.get("/items/new", params={"title": "javascript:alert(1)", "text": "Kitchen shelf"})

        assert response.status_code == 200
        assert 'name="title" required placeholder="Dining table" value="Kitchen shelf"' in response.text
        assert 'name="url" type="url" value="javascript:' not in response.text
        assert 'name="url" type="url" value=""' in response.text


def test_locale_preference_dropdown_and_persistence():
    with TestClient(app) as client:
        setup_admin(client)

        response = client.get("/settings")
        assert response.status_code == 200
        assert '<option value="en_US" >€1,234.56 - English (United States)</option>' in response.text
        assert '<option value="en_CA" >€1,234.56 - English (Canada)</option>' in response.text
        assert 'option value="fr_CA"' in response.text

        token = extract_csrf(response.text)
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "USD", "locale_name": "en_CA", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/settings")
        assert "USD · English (Canada) · UTC" in response.text
        assert '<option value="en_CA" selected>US$1,234.56 - English (Canada)</option>' in response.text

        token = extract_csrf(response.text)
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "USD", "locale_name": "en_XX", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Choose a supported locale." in response.text


def test_money_forms_accept_comma_decimal_and_currency_symbols():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {"wishlist_id": 1, "title": "Locale sofa", "status": "planned", "price_avg": "1 000,10 €"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        item_response = client.get(f"/items/{item_id}")
        assert item_response.status_code == 200
        assert "1 000.10 EUR" in item_response.text

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "100,10 €"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert "100.10 EUR" in budget_response.text


def test_budget_deposit_history_chart_uses_cumulative_deposits():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Chart camera", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        empty_response = client.get(f"/items/{item_id}?tab=budget")
        assert empty_response.status_code == 200
        assert "No deposits yet." in empty_response.text
        assert "data-deposit-chart" not in empty_response.text

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "25", "account_id": 1, "note": "First push"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "10.50", "account_id": 1, "note": "Second push"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert '<script src="/static/vendor/chart.umd.min.js" defer></script>' in budget_response.text
        assert "data-deposit-chart" in budget_response.text
        assert "Savings history" in budget_response.text
        assert "First push" in budget_response.text
        assert "Second push" in budget_response.text

        chart = chart_payload(budget_response.text)
        assert chart["target"] == 100.0
        assert chart["targetLabel"] == "100.00 EUR"
        assert chart["projectedPoints"] == []
        assert [point["amount"] for point in chart["points"]] == [25.0, 10.5]
        assert [point["cumulative"] for point in chart["points"]] == [25.0, 35.5]
        assert [point["amountLabel"] for point in chart["points"]] == ["25.00 EUR", "10.50 EUR"]
        assert [point["cumulativeLabel"] for point in chart["points"]] == ["25.00 EUR", "35.50 EUR"]
        assert all(point["kind"] == "manual" for point in chart["points"])
        assert all(point["account"] == "Cash" for point in chart["points"])


def test_manual_deposit_can_be_backdated_with_optional_date():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "EUR", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Backdated camera", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "25", "account_id": 1, "note": "Old envelope", "deposit_date": "2024-02-03"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert "manual · 2024-02-03 00:00 · Cash · Old envelope" in budget_response.text

        chart = chart_payload(budget_response.text)
        assert [point["label"] for point in chart["points"]] == ["2024-02-03 00:00"]
        assert [point["amount"] for point in chart["points"]] == [25.0]
        assert [point["cumulative"] for point in chart["points"]] == [25.0]


def test_manual_deposit_rejects_invalid_optional_date_and_preserves_values():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Invalid date camera", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "25", "account_id": 1, "note": "Keep me", "deposit_date": "not-a-date"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Invalid deposit date." in response.text
        assert 'name="amount" value="25"' in response.text
        assert 'name="deposit_date" type="date" value="not-a-date"' in response.text
        assert 'name="note" placeholder="Optional note" value="Keep me"' in response.text


def test_budget_deposit_history_chart_includes_recurring_estimate_overlay():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "EUR", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Forecast camera", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "40", "account_id": 1, "note": "Saved already"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(
                token,
                {"amount": "25", "cadence": "weekly", "account_id": 1, "next_run_at": "2099-01-01T00:00", "active": "on"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert "data-deposit-estimate-toggle" in budget_response.text
        chart = chart_payload(budget_response.text)
        assert [point["cumulative"] for point in chart["points"]] == [40.0]
        assert [point["amount"] for point in chart["projectedPoints"]] == [25.0, 25.0, 25.0]
        assert [point["cumulative"] for point in chart["projectedPoints"]] == [65.0, 90.0, 115.0]
        assert all(point["kind"] == "recurring" for point in chart["projectedPoints"])
        assert all(point["account"] == "Cash" for point in chart["projectedPoints"])
        assert chart["labels"][-3:] == [point["label"] for point in chart["projectedPoints"]]


def test_budget_deposit_history_chart_renders_with_estimate_only():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Future sofa", "status": "planned", "price_avg": "60"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(
                token,
                {"amount": "20", "cadence": "monthly", "account_id": 0, "next_run_at": "2099-01-01T00:00", "active": "on"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert '<script src="/static/vendor/chart.umd.min.js" defer></script>' in budget_response.text
        assert "data-deposit-chart" in budget_response.text
        assert "data-deposit-estimate-toggle" in budget_response.text
        assert "No deposits yet." in budget_response.text
        chart = chart_payload(budget_response.text)
        assert chart["points"] == []
        assert [point["cumulative"] for point in chart["projectedPoints"]] == [20.0, 40.0, 60.0]


def test_budget_deposit_history_chart_omits_estimate_without_projectable_rule():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Inactive forecast", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(token, {"amount": "25", "cadence": "weekly", "account_id": 0, "next_run_at": "2099-01-01T00:00"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert "data-deposit-chart" not in budget_response.text
        assert "data-deposit-estimate-toggle" not in budget_response.text

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Targetless forecast", "status": "planned"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(
                token,
                {"amount": "25", "cadence": "weekly", "account_id": 0, "next_run_at": "2099-01-01T00:00", "active": "on"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert "data-deposit-chart" not in budget_response.text
        assert "data-deposit-estimate-toggle" not in budget_response.text

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Funded forecast", "status": "planned", "price_avg": "50"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "50", "account_id": 1}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(
                token,
                {"amount": "25", "cadence": "weekly", "account_id": 0, "next_run_at": "2099-01-01T00:00", "active": "on"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert "data-deposit-chart" in budget_response.text
        assert "data-deposit-estimate-toggle" not in budget_response.text
        assert chart_payload(budget_response.text)["projectedPoints"] == []


def test_savings_entry_can_be_deleted_from_budget_history():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Delete camera", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "25", "account_id": 1, "note": "First push"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "10.50", "account_id": 1, "note": "Second push"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        delete_match = re.search(
            rf"First push</p>\s*</div>\s*<form method=\"post\" action=\"/items/{item_id}/savings/(\d+)/delete\"",
            budget_response.text,
        )
        assert delete_match, budget_response.text

        token = extract_csrf(budget_response.text)
        response = client.post(
            f"/items/{item_id}/savings/{delete_match.group(1)}/delete",
            data=with_csrf(token),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"/items/{item_id}?tab=budget"

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert budget_response.status_code == 200
        assert "First push" not in budget_response.text
        assert "Second push" in budget_response.text
        assert "10.50 EUR / 100.00 EUR" in budget_response.text

        match = re.search(r"data-chart='([^']+)'", budget_response.text)
        assert match, budget_response.text
        chart = json.loads(html.unescape(match.group(1)))
        assert [point["amount"] for point in chart["points"]] == [10.5]
        assert [point["cumulative"] for point in chart["points"]] == [10.5]


def test_users_cannot_delete_each_others_savings_entries():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Private ledger", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "25", "note": "Mine"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        entry_match = re.search(rf"/items/{item_id}/savings/(\d+)/delete", budget_response.text)
        assert entry_match, budget_response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ada", "username": "ada", "password": "long-ada-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, username="ada", password="long-ada-password")

        token = csrf_from(client, "/items/new")
        response = client.post(
            f"/items/{item_id}/savings/{entry_match.group(1)}/delete",
            data=with_csrf(token),
            follow_redirects=False,
        )
        assert response.status_code == 404


def test_deleting_savings_entry_reverts_ready_item_below_target():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Ready camera", "status": "saving", "price_avg": "50"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "50", "note": "Fully funded"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert "status-ready" in budget_response.text
        entry_match = re.search(rf"/items/{item_id}/savings/(\d+)/delete", budget_response.text)
        assert entry_match, budget_response.text

        token = extract_csrf(budget_response.text)
        response = client.post(
            f"/items/{item_id}/savings/{entry_match.group(1)}/delete",
            data=with_csrf(token),
            follow_redirects=False,
        )
        assert response.status_code == 303

        budget_response = client.get(f"/items/{item_id}?tab=budget")
        assert "status-saving" in budget_response.text
        assert "0.00 EUR / 50.00 EUR" in budget_response.text
        assert "No deposits yet." in budget_response.text


def test_users_cannot_see_each_others_items():
    with TestClient(app) as client:
        setup_admin(client)
        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Private sofa", "status": "planned", "price_avg": "200"}),
            follow_redirects=False,
        )
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ada", "username": "ada", "password": "long-ada-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, username="ada", password="long-ada-password")

        response = client.get(f"/items/{item_id}")
        assert response.status_code == 404


def test_categories_can_be_renamed_recolored_and_archived():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        response = client.post(
            "/categories",
            data=with_csrf(token, {"name": "Furniture", "color": "#8b8f78"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {"wishlist_id": 1, "title": "Dining chair", "category_id": 1, "status": "planned", "price_avg": "120"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, "/settings")
        response = client.post(
            "/categories/1",
            data=with_csrf(token, {"name": "Seating", "color": "#123456"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/settings")
        assert "Seating" in response.text
        assert "#123456" in response.text
        item_response = client.get(f"/items/{item_id}")
        assert item_response.status_code == 200
        assert "Seating" in item_response.text
        assert "Furniture" not in item_response.text

        token = extract_csrf(response.text)
        response = client.post(
            "/categories/1",
            data=with_csrf(token, {"name": "Seating", "color": "#123456", "archived": "on"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/settings")
        assert "Seating" not in response.text
        response = client.get("/items/new")
        assert '<option value="1">Seating</option>' not in response.text
        token = extract_csrf(response.text)
        response = client.post(
            "/items",
            data=with_csrf(
                token,
                {"wishlist_id": 1, "title": "Archived category item", "category_id": 1, "status": "planned", "price_avg": "10"},
            ),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Choose an active category." in response.text
        item_response = client.get(f"/items/{item_id}")
        assert "Seating" in item_response.text


def test_accounts_overview_hides_edit_forms_until_requested():
    with TestClient(app) as client:
        setup_admin(client)
        response = client.get("/accounts")

        assert response.status_code == 200
        assert "data-account-edit-toggle" in response.text
        assert "data-account-edit-form hidden" in response.text
        assert 'href="/accounts/1"' in response.text


def test_account_update_error_opens_affected_edit_form():
    with TestClient(app) as client:
        setup_admin(client)
        token = csrf_from(client, "/accounts")
        response = client.post("/accounts", data=with_csrf(token, {"name": "ING"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/accounts")
        response = client.post("/accounts/2", data=with_csrf(token, {"name": "Cash"}), follow_redirects=False)

        assert response.status_code == 400
        assert "An account with that name already exists." in response.text
        assert (
            '<form class="form inline-edit-form account-edit-form" method="post" action="/accounts/2" data-account-edit-form >'
            in response.text
        )


def test_account_detail_groups_savings_by_item_for_that_account():
    with TestClient(app) as client:
        setup_admin(client)
        token = csrf_from(client, "/accounts")
        response = client.post("/accounts", data=with_csrf(token, {"name": "Trade Republic"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Camera", "status": "saving", "price_avg": "200"}),
            follow_redirects=False,
        )
        camera_id = created_item_id(response.headers["location"])
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Tripod", "status": "saving", "price_avg": "80"}),
            follow_redirects=False,
        )
        tripod_id = created_item_id(response.headers["location"])
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Cash only", "status": "saving", "price_avg": "40"}),
            follow_redirects=False,
        )
        cash_only_id = created_item_id(response.headers["location"])

        token = csrf_from(client, f"/items/{camera_id}?tab=budget")
        assert (
            client.post(
                f"/items/{camera_id}/savings",
                data=with_csrf(token, {"amount": "25", "account_id": 2}),
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                f"/items/{camera_id}/savings",
                data=with_csrf(token, {"amount": "10.50", "account_id": 2}),
                follow_redirects=False,
            ).status_code
            == 303
        )
        token = csrf_from(client, f"/items/{tripod_id}?tab=budget")
        assert (
            client.post(
                f"/items/{tripod_id}/savings",
                data=with_csrf(token, {"amount": "15", "account_id": 2}),
                follow_redirects=False,
            ).status_code
            == 303
        )
        token = csrf_from(client, f"/items/{cash_only_id}?tab=budget")
        assert (
            client.post(
                f"/items/{cash_only_id}/savings",
                data=with_csrf(token, {"amount": "99", "account_id": 1}),
                follow_redirects=False,
            ).status_code
            == 303
        )

        response = client.get("/accounts/2")

        assert response.status_code == 200
        assert "Trade Republic" in response.text
        assert "50.50 EUR" in response.text
        assert "Camera" in response.text
        assert "General" in response.text
        assert '<span class="pill status-saving">saving</span>' in response.text
        assert "35.50 EUR" in response.text
        assert f'href="/items/{camera_id}?tab=budget"' in response.text
        assert "Tripod" in response.text
        assert "15.00 EUR" in response.text
        assert "Cash only" not in response.text


def test_account_detail_scopes_to_current_user():
    with TestClient(app) as client:
        setup_admin(client)
        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ana", "username": "ana", "password": "another-long-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, username="ana", password="another-long-password")

        response = client.get("/accounts/1")

        assert response.status_code == 404


def test_category_update_validation_and_ownership():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        assert client.post("/categories", data=with_csrf(token, {"name": "Furniture", "color": "#8b8f78"})).status_code == 200
        token = csrf_from(client, "/settings")
        response = client.post("/categories", data=with_csrf(token, {"name": "Decor", "color": "#f6c344"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/settings")
        response = client.post("/categories/1", data=with_csrf(token, {"name": "Furniture", "color": "red"}), follow_redirects=False)
        assert response.status_code == 400
        assert "Invalid color." in response.text

        token = csrf_from(client, "/settings")
        response = client.post("/categories/1", data=with_csrf(token, {"name": "Decor", "color": "#8b8f78"}), follow_redirects=False)
        assert response.status_code == 400
        assert "A category with that name already exists." in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ada", "username": "ada", "password": "long-ada-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, username="ada", password="long-ada-password")

        response = client.get("/settings")
        assert response.status_code == 200
        assert "<h2>Add user</h2>" not in response.text
        assert "Create private user" not in response.text
        assert 'action="/settings/users"' not in response.text
        assert "Only admins can add users." not in response.text

        token = extract_csrf(response.text)
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Grace", "username": "grace", "password": "long-grace-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 403

        token = csrf_from(client, "/settings")
        response = client.post("/categories/1", data=with_csrf(token, {"name": "Nope", "color": "#8b8f78"}), follow_redirects=False)
        assert response.status_code == 404


def test_item_can_move_to_another_active_list():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/lists")
        response = client.post("/lists", data=with_csrf(token, {"name": "Travel"}), follow_redirects=False)
        assert response.status_code == 303
        response = client.post("/lists", data=with_csrf(token, {"name": "Office"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Desk mat", "status": "planned", "price_avg": "20"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 2, "title": "Packing cubes", "status": "planned", "price_avg": "30"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get(f"/items/{item_id}")
        assert response.status_code == 200
        assert 'data-item-move-toggle aria-label="Move item"' in response.text
        assert 'data-item-move-form hidden' in response.text
        assert '<option value="2" >Travel</option>' in response.text
        assert '<option value="3" >Office</option>' in response.text
        assert '<option value="1"' not in response.text

        token = extract_csrf(response.text)
        response = client.post(f"/items/{item_id}/move", data=with_csrf(token, {"wishlist_id": 2}), follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/lists/2"
        old_list = client.get("/lists/1")
        new_list = client.get("/lists/2")
        assert "Desk mat" not in old_list.text
        assert "Desk mat" in new_list.text
        assert "Packing cubes" in new_list.text
        moved_item = client.get(f"/items/{item_id}")
        assert "Travel" in moved_item.text
        assert "Rank</span><strong>#2</strong>" in moved_item.text


def test_item_move_rejects_archived_same_and_inaccessible_lists():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/lists")
        response = client.post("/lists", data=with_csrf(token, {"name": "Travel"}), follow_redirects=False)
        assert response.status_code == 303
        response = client.post("/lists", data=with_csrf(token, {"name": "Archive me"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/lists")
        response = client.post("/lists/3/archive", data=with_csrf(token, {"archived": "true"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Lamp", "status": "planned", "price_avg": "40"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        response = client.get(f"/items/{item_id}")
        assert '<option value="2" >Travel</option>' in response.text
        assert '<option value="3"' not in response.text
        token = extract_csrf(response.text)

        response = client.post(f"/items/{item_id}/move", data=with_csrf(token, {"wishlist_id": 3}), follow_redirects=False)
        assert response.status_code == 400
        assert "Choose an active wishlist." in response.text
        assert 'data-item-move-form ' in response.text
        assert 'data-item-move-form hidden' not in response.text

        response = client.post(f"/items/{item_id}/move", data=with_csrf(token, {"wishlist_id": 1}), follow_redirects=False)
        assert response.status_code == 400
        assert "Choose a different wishlist." in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ada", "username": "ada", "password": "long-ada-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        response = client.post(f"/items/{item_id}/move", data=with_csrf(token, {"wishlist_id": 4}), follow_redirects=False)
        assert response.status_code == 400
        assert "Choose an active wishlist." in response.text

        logout(client)
        login(client, username="ada", password="long-ada-password")
        token = csrf_from(client, "/lists")
        response = client.post(f"/items/{item_id}/move", data=with_csrf(token, {"wishlist_id": 4}), follow_redirects=False)
        assert response.status_code == 404


def test_manage_lists_from_overview_and_detail():
    with TestClient(app) as client:
        setup_admin(client)

        response = client.get("/lists/1")
        assert response.status_code == 200
        assert 'data-list-edit-toggle aria-label="Rename list"' in response.text

        token = csrf_from(client, "/lists/1")
        response = client.post(
            "/lists/1",
            data=with_csrf(token, {"name": "Home upgrades", "description": "Make the place nicer"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/lists/1"
        response = client.get("/lists")
        assert "Home upgrades" in response.text
        response = client.get("/lists/1")
        assert "Make the place nicer" in response.text
        assert 'data-back-url="/lists"' in response.text

        token = csrf_from(client, "/lists")
        response = client.post("/lists", data=with_csrf(token, {"name": "Travel"}), follow_redirects=False)
        assert response.status_code == 303

        token = csrf_from(client, "/lists/1")
        response = client.post("/lists/1", data=with_csrf(token, {"name": "Travel"}), follow_redirects=False)
        assert response.status_code == 400

        token = csrf_from(client, "/items/new")
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 2, "title": "Suitcase", "status": "planned", "price_avg": "100"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]
        item_response = client.get(f"/items/{item_id}")
        assert 'data-back-url="/lists/2"' in item_response.text

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "25"}),
            follow_redirects=False,
        )
        assert response.status_code == 303

        token = csrf_from(client, "/lists")
        response = client.post("/lists/2/archive", data=with_csrf(token, {"archived": "true"}), follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/lists?show_archived=true"

        response = client.get("/lists")
        assert "Travel" not in response.text
        response = client.get("/lists?show_archived=true")
        assert "Travel" in response.text
        assert "archived" in response.text

        response = client.get("/items/new")
        assert '<option value="2"' not in response.text
        token = extract_csrf(response.text)
        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 2, "title": "Archived item", "status": "planned", "price_avg": "10"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Choose an active wishlist." in response.text

        token = csrf_from(client, "/lists?show_archived=true")
        response = client.post("/lists/2/archive", data=with_csrf(token, {"archived": "false"}), follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/lists"
        response = client.get("/lists")
        assert "Travel" in response.text

        token = csrf_from(client, "/lists")
        response = client.post("/lists/2/delete", data=with_csrf(token), follow_redirects=False)
        assert response.status_code == 303
        response = client.get("/lists")
        assert "Travel" not in response.text
        assert client.get(f"/items/{item_id}").status_code == 404
        assert client.get("/lists/2").status_code == 404


def test_users_cannot_manage_each_others_lists():
    with TestClient(app) as client:
        setup_admin(client)

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ada", "username": "ada", "password": "long-ada-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, username="ada", password="long-ada-password")

        token = csrf_from(client, "/lists")
        response = client.post("/lists/1", data=with_csrf(token, {"name": "Nope"}), follow_redirects=False)
        assert response.status_code == 404
        response = client.post("/lists/1/archive", data=with_csrf(token, {"archived": "true"}), follow_redirects=False)
        assert response.status_code == 404
        response = client.post("/lists/1/delete", data=with_csrf(token), follow_redirects=False)
        assert response.status_code == 404


def test_version_info_falls_back_when_file_is_missing(tmp_path):
    version_info = load_version_info(tmp_path / "missing-version.json")

    assert version_info.version == "0.25.0"
    assert version_info.commit == ""
    assert version_info.build_date == ""
    assert version_info.source_url == SOURCE_URL
    assert version_info.releases_url == RELEASES_URL


def test_version_info_reads_stamped_file(tmp_path):
    version_file = tmp_path / "VERSION.json"
    version_file.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "commit": "abcdef1234567890",
                "build_date": "2026-06-21T17:00:00Z",
                "source_url": "https://example.test/repo",
                "releases_url": "https://example.test/releases",
            }
        ),
        encoding="utf-8",
    )

    version_info = load_version_info(version_file)

    assert version_info.version == "1.2.3"
    assert version_info.commit == "abcdef1234567890"
    assert version_info.build_date == "2026-06-21T17:00:00Z"
    assert version_info.source_url == "https://example.test/repo"
    assert version_info.releases_url == "https://example.test/releases"


def test_settings_shows_version_and_admin_update_links_only_for_admins():
    with TestClient(app) as client:
        setup_admin(client)

        response = client.get("/settings")
        assert response.status_code == 200
        assert "Installed version" in response.text
        assert "0.25.0" in response.text
        assert f'href="{RELEASES_URL}"' in response.text
        assert f'href="{SOURCE_URL}"' in response.text
        assert "Check for updates" in response.text
        assert "Repository" in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Ada", "username": "ada", "password": "long-ada-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, username="ada", password="long-ada-password")

        response = client.get("/settings")
        assert response.status_code == 200
        assert "Installed version" in response.text
        assert "0.25.0" in response.text
        assert "Check for updates" not in response.text
        assert "Repository" not in response.text
        assert f'href="{RELEASES_URL}"' not in response.text
        assert f'href="{SOURCE_URL}"' not in response.text


def test_public_and_protected_route_boundaries():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.json() == {"status": "ok"}
        assert "content-security-policy" in response.headers
        assert client.get("/manifest.webmanifest").status_code == 200
        assert client.get("/static/app.js").status_code == 200

        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

        response = client.post("/lists", data={"name": "Nope"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_csrf_required_for_public_and_authenticated_posts():
    with TestClient(app) as client:
        response = client.post(
            "/setup",
            data={"display_name": "Fabian", "username": "fabian", "password": ADMIN_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 403

        setup_admin(client)
        response = client.post("/lists", data={"name": "No token"}, follow_redirects=False)
        assert response.status_code == 403

        token = csrf_from(client, "/lists")
        response = client.post("/lists", data=with_csrf(token, {"name": "With token"}), follow_redirects=False)
        assert response.status_code == 303

        response = client.post("/lists/1", data={"name": "No token"}, follow_redirects=False)
        assert response.status_code == 403
        response = client.post("/lists/1/archive", data={"archived": "true"}, follow_redirects=False)
        assert response.status_code == 403
        response = client.post("/lists/1/delete", follow_redirects=False)
        assert response.status_code == 403
        response = client.post("/items/1/move", data={"wishlist_id": 1}, follow_redirects=False)
        assert response.status_code == 403


def test_login_rate_limit_returns_429():
    with TestClient(app) as client:
        setup_admin(client)
        logout(client)
        token = csrf_from(client, "/login")

        for _ in range(5):
            response = client.post(
                "/login",
                data=with_csrf(token, {"username": "fabian", "password": "wrong-password"}),
                follow_redirects=False,
            )
            assert response.status_code == 400

        response = client.post(
            "/login",
            data=with_csrf(token, {"username": "fabian", "password": "wrong-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 429


def test_production_security_settings_and_secure_cookie():
    settings = Settings(environment="production", secret_key="x" * 32, allowed_hosts="tiptib.example.com")
    validate_security_settings(settings)
    assert settings.secure_session_cookie is True
    assert "Strict-Transport-Security" in security_headers(settings)

    with pytest.raises(RuntimeError):
        validate_security_settings(
            Settings(environment="production", secret_key="change-me-in-production", allowed_hosts="tiptib.example.com")
        )
    with pytest.raises(RuntimeError):
        validate_security_settings(Settings(environment="production", secret_key="x" * 32, allowed_hosts="*"))
    with pytest.raises(RuntimeError):
        validate_first_run_setup_allowed(settings, users_present=False)

    cookie_app = FastAPI()
    cookie_app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="tiptib_session",
        same_site="lax",
        https_only=settings.secure_session_cookie,
    )

    @cookie_app.get("/")
    def set_session(request: Request):
        request.session["user_id"] = 1
        return {"ok": True}

    with TestClient(cookie_app, base_url="https://tiptib.example.com") as client:
        response = client.get("/")
        set_cookie = response.headers["set-cookie"].lower()
        assert "secure" in set_cookie
        assert "samesite=lax" in set_cookie


def test_bad_inputs_are_controlled_responses():
    with TestClient(app) as client:
        setup_admin(client)
        token = csrf_from(client, "/items/new")

        response = client.get("/lists/1?status=not-a-status")
        assert response.status_code == 200

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bad status", "status": "not-a-status"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "text/html" in response.headers["content-type"]
        assert "Invalid item status." in response.text
        assert "Add a plan" in response.text

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bad money", "status": "planned", "price_avg": "nope"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Invalid money amount." in response.text
        assert "Bad money" in response.text

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bad link", "status": "planned", "url": "javascript:alert(1)"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Links must use http or https." in response.text

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bad rank", "status": "planned", "rank": "nope"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Rank must be a whole number." in response.text
        assert 'value="nope"' in response.text

        for bad_amount in ("nope", "1.5", "0", "-1"):
            response = client.post(
                "/items",
                data=with_csrf(
                    token,
                    {"wishlist_id": 1, "title": "Bad amount", "status": "planned", "price_avg": "10", "amount": bad_amount},
                ),
                follow_redirects=False,
            )
            assert response.status_code == 400
            assert "Amount must be a whole number of at least 1." in response.text
            assert f'value="{bad_amount}"' in response.text

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Good item", "status": "planned", "price_avg": "10", "amount": ""}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]
        response = client.get(f"/items/{item_id}")
        assert response.status_code == 200
        assert "Amount</span>" not in response.text

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(token, {"amount": "5", "cadence": "yearly", "next_run_at": "2026-01-01T00:00"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Recurring deposit" in response.text
        assert "Invalid recurrence cadence." in response.text

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/savings",
            data=with_csrf(token, {"amount": "nope", "account_id": 0}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Savings" in response.text
        assert "Invalid amount." in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/password",
            data=with_csrf(token, {"current_password": ADMIN_PASSWORD, "new_password": "short"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Settings" in response.text
        assert "Password must be at least 12 characters." in response.text
        assert "short" not in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/preferences",
            data=with_csrf(token, {"currency": "EURO", "timezone_name": "UTC"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Currency must be a 3-letter code." in response.text
        assert 'value="EURO"' in response.text
        response = client.get("/settings")
        assert "EURO" not in response.text

        token = csrf_from(client, "/settings")
        response = client.post("/categories", data=with_csrf(token, {"name": "Bad color", "color": "red"}), follow_redirects=False)
        assert response.status_code == 400
        assert "Invalid color." in response.text
        assert "Settings" in response.text

        token = csrf_from(client, "/settings")
        response = client.post("/categories", data=with_csrf(token, {"name": "Furniture", "color": "#8b8f78"}), follow_redirects=False)
        assert response.status_code == 303
        token = csrf_from(client, "/settings")
        response = client.post("/categories", data=with_csrf(token, {"name": "Furniture", "color": "#8b8f78"}), follow_redirects=False)
        assert response.status_code == 400
        assert "A category with that name already exists." in response.text

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/users",
            data=with_csrf(token, {"display_name": "Fabian Again", "username": "fabian", "password": "another-long-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Username already exists." in response.text
        assert "another-long-password" not in response.text

        token = csrf_from(client, "/lists")
        response = client.post("/lists", data=with_csrf(token, {"name": "General"}), follow_redirects=False)
        assert response.status_code == 400
        assert "Your plans" in response.text
        assert "A wishlist with that name already exists." in response.text

        token = csrf_from(client, "/accounts")
        response = client.post("/accounts", data=with_csrf(token, {"name": "Cash"}), follow_redirects=False)
        assert response.status_code == 400
        assert "Saving accounts" in response.text
        assert "An account with that name already exists." in response.text

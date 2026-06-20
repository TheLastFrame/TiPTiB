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

        setup_admin(client)

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "buy plan" in response.text

        token = csrf_from(client, "/items/new")
        response = client.get("/lists")
        assert response.status_code == 200
        assert "Your plans" in response.text
        assert 'href="/lists/1"' in response.text

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Maybe someday", "status": "idea", "price_avg": "999"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
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
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/items/")

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
        assert 'href="/items/2"' in response.text
        assert '<details class="filter-drawer">' in response.text
        assert "shown</span>" not in response.text
        assert "data-submit-on-change" in response.text
        assert "onchange=" not in response.text
        assert "onclick=" not in response.text

        response = client.get("/lists/1?show_sum=true")
        assert response.status_code == 200
        assert "Filtered sum" in response.text
        assert "1 539.00 EUR" in response.text

        response = client.get("/lists/1?status=planned&show_sum=true")
        assert response.status_code == 200
        assert "4/5 shown" in response.text
        assert "540.00 EUR" in response.text
        assert "999.00 EUR" not in response.text

        response = client.get("/lists/1?status=planned&sort_by=max_price&sort_dir=desc")
        assert response.status_code == 200
        assert response.text.index("Actual-first shelf") < response.text.index("Dining table")
        assert response.text.index("Dining table") < response.text.index("Fallback speaker")

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
        assert "Open budget" not in item_url.text
        assert "0% saved" not in item_url.text
        budget_response = client.get("/items/1?tab=budget")
        assert budget_response.status_code == 200
        assert "Recurring deposit" in budget_response.text
        details_response = client.get("/items/1?tab=details")
        assert details_response.status_code == 200
        assert "Save item" in details_response.text

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
                },
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        response = client.get("/history")
        assert response.status_code == 200
        assert "Dining table" in response.text

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

        token = csrf_from(client, "/settings")
        response = client.post(
            "/settings/password",
            data=with_csrf(token, {"current_password": ADMIN_PASSWORD, "new_password": "new-long-password"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        logout(client)
        login(client, password="new-long-password")

        assert client.get("/manifest.webmanifest").json()["short_name"] == "TiPTiB"
        assert client.get("/static/sw.js").status_code == 200
        assert client.get("/static/app.js").status_code == 200


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

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bad money", "status": "planned", "price_avg": "nope"}),
            follow_redirects=False,
        )
        assert response.status_code == 400

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Bad link", "status": "planned", "url": "javascript:alert(1)"}),
            follow_redirects=False,
        )
        assert response.status_code == 400

        response = client.post(
            "/items",
            data=with_csrf(token, {"wishlist_id": 1, "title": "Good item", "status": "planned", "price_avg": "10"}),
            follow_redirects=False,
        )
        assert response.status_code == 303
        item_id = response.headers["location"].split("/")[-1]

        token = csrf_from(client, f"/items/{item_id}?tab=budget")
        response = client.post(
            f"/items/{item_id}/recurring-rule",
            data=with_csrf(token, {"amount": "5", "cadence": "yearly", "next_run_at": "2026-01-01T00:00"}),
            follow_redirects=False,
        )
        assert response.status_code == 400

        token = csrf_from(client, "/settings")
        response = client.post("/categories", data=with_csrf(token, {"name": "Bad color", "color": "red"}), follow_redirects=False)
        assert response.status_code == 400

        token = csrf_from(client, "/lists")
        response = client.post("/lists", data=with_csrf(token, {"name": "General"}), follow_redirects=False)
        assert response.status_code == 400

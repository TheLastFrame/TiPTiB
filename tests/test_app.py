import os
import tempfile

os.environ["TIPTIB_DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["TIPTIB_SECRET_KEY"] = "test-secret"
os.environ["TIPTIB_SCHEDULER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def setup_admin(client: TestClient) -> None:
    client.post(
        "/setup",
        data={"display_name": "Fabian", "username": "fabian", "password": "secret"},
        follow_redirects=False,
    )


def test_setup_login_create_item_and_pwa_routes():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Set up TiPTiB" in response.text

        response = client.post("/setup", data={"display_name": "Fabian", "username": "fabian", "password": "secret"}, follow_redirects=False)
        assert response.status_code == 303

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "Today’s buy plan" in response.text

        response = client.get("/lists")
        assert response.status_code == 200
        assert "Your plans" in response.text
        assert 'href="/lists/1"' in response.text

        response = client.post(
            "/items",
            data={"wishlist_id": 1, "title": "Maybe someday", "status": "idea", "price_avg": "999"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        response = client.get("/dashboard")
        assert "999.00 EUR" not in response.text
        response = client.get("/lists")
        assert "999.00 EUR planned" not in response.text

        response = client.post(
            "/items",
            data={
                "wishlist_id": 1,
                "title": "Dining table",
                "status": "planned",
                "price_min": "300",
                "price_avg": "450",
                "price_max": "700",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/items/")

        response = client.post(
            "/items",
            data={
                "wishlist_id": 1,
                "title": "Desk lamp",
                "status": "planned",
                "price_min": "20",
                "price_avg": "35",
                "price_max": "80",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(
            "/items",
            data={
                "wishlist_id": 1,
                "title": "Fallback speaker",
                "status": "planned",
                "price_avg": "650",
                "actual_price": "15",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(
            "/items",
            data={
                "wishlist_id": 1,
                "title": "Actual-first shelf",
                "status": "planned",
                "price_min": "120",
                "price_max": "900",
                "actual_price": "40",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.get("/lists/1")
        assert response.status_code == 200
        assert "Dining table" in response.text
        assert 'href="/items/2"' in response.text
        assert '<details class="filter-drawer">' in response.text
        assert "shown</span>" not in response.text
        assert 'onchange="this.form.submit()"' in response.text

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

        assert client.get("/manifest.webmanifest").json()["short_name"] == "TiPTiB"
        assert client.get("/static/sw.js").status_code == 200


def test_users_cannot_see_each_others_items():
    with TestClient(app) as client:
        setup_admin(client)
        response = client.post(
            "/items",
            data={"wishlist_id": 1, "title": "Private sofa", "status": "planned", "price_avg": "200"},
            follow_redirects=False,
        )
        item_id = response.headers["location"].split("/")[-1]

        client.post(
            "/settings/users",
            data={"display_name": "Ada", "username": "ada", "password": "secret"},
            follow_redirects=False,
        )
        client.post("/logout")
        client.post("/login", data={"username": "ada", "password": "secret"})

        response = client.get(f"/items/{item_id}")
        assert response.status_code == 404

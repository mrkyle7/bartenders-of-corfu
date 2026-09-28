"""Host-based routing between the cheetahmoongames.com home page and the game.

Uses a small stand-in app with the same middleware, so these tests run without
Supabase.
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.landing import LandingHostMiddleware

LANDING = "http://cheetahmoongames.com"
GAME = "http://bartenders.cheetahmoongames.com"


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def game_home():
        return PlainTextResponse("bartenders lobby")

    @app.get("/game")
    async def game_page():
        return PlainTextResponse("bartenders game")

    @app.post("/login")
    async def login():
        return PlainTextResponse("logged in")

    @app.get("/health")
    async def health():
        return {"isAvailable": True}

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.add_middleware(LandingHostMiddleware)
    return app


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("LANDING_HOST", "cheetahmoongames.com")
    monkeypatch.setenv("BARTENDERS_URL", "https://bartenders.cheetahmoongames.com/")


def _client(base_url: str) -> TestClient:
    return TestClient(_app(), base_url=base_url, follow_redirects=False)


# --- Positive ----------------------------------------------------------------


def test_landing_host_serves_the_home_page(configured):
    resp = _client(LANDING).get("/")
    assert resp.status_code == 200
    assert "Cheetah Moon Games" in resp.text
    assert "https://bartenders.cheetahmoongames.com/" in resp.text
    assert "https://boxer.cheetahmoongames.com/" in resp.text


def test_old_game_links_redirect_to_the_bartenders_subdomain(configured):
    resp = _client(LANDING).get("/game?id=abc-123")
    assert resp.status_code == 307
    assert (
        resp.headers["location"]
        == "https://bartenders.cheetahmoongames.com/game?id=abc-123"
    )


def test_redirect_keeps_the_method_for_posts(configured):
    resp = _client(LANDING).post("/login", json={"username": "x"})
    assert resp.status_code == 307
    assert resp.headers["location"] == "https://bartenders.cheetahmoongames.com/login"


def test_landing_host_retires_the_old_service_worker(configured):
    resp = _client(LANDING).get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert "unregister" in resp.text


def test_landing_host_still_serves_static_images_and_health(configured):
    client = _client(LANDING)
    assert client.get("/static/bartenders.png").status_code == 200
    assert client.get("/health").json() == {"isAvailable": True}


def test_host_match_ignores_port_and_case(configured):
    resp = _client("http://CheetahMoonGames.com:8080").get("/")
    assert "Cheetah Moon Games" in resp.text


# --- Negative ----------------------------------------------------------------


def test_bartenders_subdomain_is_unchanged(configured):
    client = _client(GAME)
    assert client.get("/").text == "bartenders lobby"
    assert client.get("/game?id=abc").text == "bartenders game"
    # The retiring service worker is only served on the landing host.
    assert client.get("/sw.js").status_code == 404


def test_without_landing_host_the_app_behaves_as_before(monkeypatch):
    monkeypatch.delenv("LANDING_HOST", raising=False)
    client = _client(LANDING)
    assert client.get("/").text == "bartenders lobby"
    assert client.get("/game").text == "bartenders game"


def test_landing_host_without_a_target_returns_404(monkeypatch):
    monkeypatch.setenv("LANDING_HOST", "cheetahmoongames.com")
    monkeypatch.delenv("BARTENDERS_URL", raising=False)
    resp = _client(LANDING).get("/game")
    assert resp.status_code == 404

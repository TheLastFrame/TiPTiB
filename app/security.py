from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import Form, HTTPException, Request, status

from app.config import Settings

CSRF_SESSION_KEY = "csrf_token"
PUBLIC_POST_PATHS = {"/login", "/setup"}
DEFAULT_SECRET_KEYS = {"change-me-in-production", "change-this-secret", "test-secret"}


def validate_security_settings(settings: Settings) -> None:
    if bool(settings.bootstrap_username) != bool(settings.bootstrap_password):
        raise RuntimeError("TIPTIB_BOOTSTRAP_USERNAME and TIPTIB_BOOTSTRAP_PASSWORD must be set together.")
    if not settings.is_production:
        return
    if settings.secret_key in DEFAULT_SECRET_KEYS or len(settings.secret_key) < 32:
        raise RuntimeError("TIPTIB_SECRET_KEY must be a unique random value with at least 32 characters in production.")
    if "*" in settings.allowed_host_list:
        raise RuntimeError("TIPTIB_ALLOWED_HOSTS must list public hostnames in production.")


def validate_first_run_setup_allowed(settings: Settings, users_present: bool) -> None:
    if users_present:
        return
    if settings.bootstrap_username and settings.bootstrap_password:
        return
    if settings.allow_web_setup:
        return
    if settings.is_production:
        raise RuntimeError(
            "Refusing to expose first-run web setup in production. Set bootstrap credentials or "
            "TIPTIB_ALLOW_WEB_SETUP=true intentionally."
        )


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    if request.url.path not in PUBLIC_POST_PATHS and not request.session.get("user_id"):
        return
    expected = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(expected, str) or not csrf_token or not hmac.compare_digest(expected, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")


def security_headers(settings: Settings) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "X-Frame-Options": "DENY",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "manifest-src 'self'; "
            "worker-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        ),
    }
    if settings.secure_session_cookie:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers

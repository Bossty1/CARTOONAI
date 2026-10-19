"""Authentication, ownership, sharing and rate-limiting helpers."""
from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import Header, Request, status

from ..core.config import Settings, get_settings
from ..core.errors import AppError

RATE_LIMITED_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def current_owner(x_owner_id: str | None = Header(default=None, alias="X-Owner-Id")) -> str:
    settings = get_settings()
    if settings.require_auth and not x_owner_id:
        raise AppError("OWNER_REQUIRED", "X-Owner-Id header is required.", status.HTTP_401_UNAUTHORIZED)
    return (x_owner_id or settings.default_owner).strip()[:128]


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    settings = get_settings()
    if not settings.require_auth:
        return
    if not x_api_key or x_api_key not in settings.api_key_set:
        raise AppError("UNAUTHORIZED", "A valid X-API-Key header is required.", status.HTTP_401_UNAUTHORIZED)


def enforce_rate_limit(bucket: str) -> None:
    settings = get_settings()
    if not settings.enable_rate_limit:
        return
    limit = max(1, settings.rate_limit_per_minute)
    now = time.monotonic()
    window = RATE_LIMITED_BUCKETS[bucket]
    while window and now - window[0] > 60.0:
        window.popleft()
    if len(window) >= limit:
        raise AppError(
            "RATE_LIMITED",
            f"Too many requests for this operation ({limit}/minute). Try again shortly.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    window.append(now)


def reset_rate_limits() -> None:
    RATE_LIMITED_BUCKETS.clear()


def client_key(request: Request, owner: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{owner}:{host}"


def create_share_token(asset_id: str, ttl_seconds: int, settings: Settings | None = None) -> tuple[str, int]:
    settings = settings or get_settings()
    expires_at = int(time.time()) + max(60, ttl_seconds)
    signature = hmac.new(
        settings.share_secret.encode("utf-8"), f"{asset_id}:{expires_at}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{expires_at}.{signature}", expires_at


def verify_share_token(asset_id: str, token: str | None, settings: Settings | None = None) -> bool:
    if not token or "." not in token:
        return False
    settings = settings or get_settings()
    expires_raw, _, signature = token.partition(".")
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    expected = hmac.new(
        settings.share_secret.encode("utf-8"), f"{asset_id}:{expires_at}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def is_publicly_reachable(base_url: str) -> bool:
    host = base_url.split("//")[-1].split("/")[0].split(":")[0].lower()
    return host not in {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}

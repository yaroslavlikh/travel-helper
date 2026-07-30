from __future__ import annotations

from app.core.http_security import SlidingWindowRateLimiter, security_headers


def test_sliding_window_limiter_returns_retry_after_without_request_content() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10)

    assert limiter.retry_after_seconds("recommend:127.0.0.1", now=0) is None
    assert limiter.retry_after_seconds("recommend:127.0.0.1", now=1) is None
    assert limiter.retry_after_seconds("recommend:127.0.0.1", now=2) == 9
    assert limiter.retry_after_seconds("recommend:127.0.0.1", now=11) is None


def test_security_headers_only_enable_hsts_for_production() -> None:
    assert "Strict-Transport-Security" not in security_headers(production=False)
    assert security_headers(production=True)["Strict-Transport-Security"].startswith("max-age=")

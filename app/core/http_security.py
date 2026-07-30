"""Small HTTP safeguards for the single-process closed-beta deployment."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import monotonic


@dataclass(slots=True)
class SlidingWindowRateLimiter:
    """Bound requests per direct client/path without retaining user content."""

    max_requests: int
    window_seconds: int
    _requests: dict[str, deque[float]] = field(default_factory=dict)

    def retry_after_seconds(self, key: str, *, now: float | None = None) -> int | None:
        current = monotonic() if now is None else now
        requests = self._requests.setdefault(key, deque())
        cutoff = current - self.window_seconds
        while requests and requests[0] <= cutoff:
            requests.popleft()
        if len(requests) >= self.max_requests:
            return max(1, int(requests[0] + self.window_seconds - current) + 1)
        requests.append(current)
        return None


def security_headers(*, production: bool) -> dict[str, str]:
    """Return conservative headers that do not require a proxy-specific configuration."""

    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers

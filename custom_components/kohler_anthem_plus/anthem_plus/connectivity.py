"""Small, transport-independent connectivity recovery policy.

No polling or I/O lives here. Callers schedule this policy only after a failure.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit


class RecoveryBackoff:
    """Successive 1/2/5 minute delays, slowing for unattended outages."""

    def __init__(self) -> None:
        self.since: float | None = None
        self.attempts = 0
        self.due: float | None = None
        self.long_reported = False

    def reset(self) -> None:
        self.since = self.due = None
        self.attempts = 0
        self.long_reported = False

    def fail(self, *, minimum: float = 0) -> float:
        now = time.monotonic()
        if self.since is None:
            self.since = now
        elapsed = now - self.since
        if elapsed >= 86400:
            delay = 3600
        elif elapsed >= 3600:
            delay = 900
        else:
            delay = (60, 120, 300)[min(self.attempts, 2)]
        self.attempts += 1
        delay = max(float(delay), minimum)
        self.due = now + delay
        return delay

    @property
    def remaining(self) -> float:
        return max(0.0, (self.due or 0) - time.monotonic())


def local_hostname(value: object) -> str | None:
    """Accept a plain .local hostname, never cloud-supplied paths/credentials."""
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value if "://" in value else f"http://{value}")
        host = url.hostname
        if (
            url.scheme != "http" or url.username or url.password
            or url.port not in (None, 80) or url.path not in ("", "/")
            or url.query or url.fragment or not host or not host.endswith(".local")
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host)
        ):
            return None
        return host
    except ValueError:
        return None


def error_label(error: BaseException) -> str:
    """A useful diagnostic without response bodies, URLs, or credentials."""
    status = getattr(error, "status", None)
    return f"{type(error).__name__}" + (f" (HTTP {status})" if status else "")

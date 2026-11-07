"""Admin-only access: the caller sends a Supabase access token, we ask Supabase who they are.

Only the public anon key is needed. The user's own token is used for the profile lookup, so row level
security decides what is visible: a learner can only ever read their own profile row.
"""

import time
from typing import Protocol

import httpx


class AuthError(Exception):
    """Raised with an HTTP status and a short safe message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Verifier(Protocol):
    def verify(self, token: str) -> str:
        """Return a stable user id for an allowed admin or raise AuthError."""


class SupabaseAdminVerifier:
    def __init__(
        self,
        url: str,
        anon_key: str,
        client: httpx.Client | None = None,
        cache_seconds: float = 60.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._anon = anon_key
        self._client = client or httpx.Client(timeout=5.0)
        self._ttl = cache_seconds
        self._cache: dict[str, tuple[float, str]] = {}

    def verify(self, token: str) -> str:
        now = time.monotonic()
        hit = self._cache.get(token)
        if hit and hit[0] > now:
            return hit[1]

        headers = {"apikey": self._anon, "Authorization": f"Bearer {token}"}
        try:
            who = self._client.get(f"{self._url}/auth/v1/user", headers=headers)
            if who.status_code != 200:
                raise AuthError(401, "Sign in again.")
            user_id = str(who.json().get("id", ""))
            if not user_id:
                raise AuthError(401, "Sign in again.")

            prof = self._client.get(
                f"{self._url}/rest/v1/profiles",
                headers=headers,
                params={"select": "role", "id": f"eq.{user_id}"},
            )
        except httpx.HTTPError:
            raise AuthError(503, "Could not reach the sign-in service.") from None

        rows = prof.json() if prof.status_code == 200 else []
        if not rows or rows[0].get("role") != "admin":
            raise AuthError(403, "Analytics is for administrators only.")

        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[token] = (now + self._ttl, user_id)
        return user_id


class RateLimiter:
    """Small in-memory limit per user to keep model costs predictable."""

    def __init__(self, max_calls: int, per_seconds: float) -> None:
        self._max = max_calls
        self._window = per_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self._hits.get(key, []) if now - t < self._window]
        if len(recent) >= self._max:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        return True

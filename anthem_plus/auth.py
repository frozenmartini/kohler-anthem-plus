"""Server-side Azure AD B2C sign-in for Kohler Konnect.

Kohler's B2C app registration only accepts a **custom-scheme** redirect URI
(``msauth.com.kohler.hermoth://auth``) — there is no localhost or web redirect, so the
usual "let the browser come back to us" OAuth dance is impossible. The previous approach
sent the user to the sign-in page in a browser and asked them to copy the final
``msauth://...?code=...`` URL back; modern browsers drop that navigation without ever
showing the URL, which made it unusable.

This module avoids the problem entirely by driving the B2C custom policy the way the
sign-in page's own JavaScript does, in-process:

1. ``GET /authorize`` with PKCE — collects session cookies plus the ``csrf`` token and
   ``transId`` from the page's ``SETTINGS`` blob.
2. ``POST /SelfAsserted`` with the username and password — returns a small JSON status.
3. ``GET /api/CombinedSigninAndSignup/confirmed`` **without following redirects** — B2C
   answers ``302 Location: msauth.com.kohler.hermoth://auth/?code=...``.
4. ``POST /token`` — exchanges that code, with the PKCE verifier, for tokens.

Step 3 is the whole trick: the unresolvable custom scheme is only ever a string in a
response header we read ourselves. No browser is involved, so nothing can block it, and
the user just types an email and password.

Verified live 2026-08-11: the redirect URI is accepted and strictly validated, step 2
returns ``AADB2C90053`` for bad credentials, and step 3 returns the expected 302.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    API_RESOURCE,
    B2C_AUTHORIZE_URL,
    B2C_CONFIRMED_URL,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    B2C_SELF_ASSERTED_URL,
    B2C_SIGNIN_POLICY,
    B2C_TOKEN_URL,
    CLIENT_ID,
    ERROR_BAD_CREDENTIALS,
    ERROR_REDIRECT_NOT_REGISTERED,
    TOKEN_EXPIRY_MARGIN_SECONDS,
)

# The sign-in page embeds its configuration as `var SETTINGS = {...};`.
_SETTINGS = re.compile(r"var SETTINGS = (\{.*?\});", re.S)
_B2C_ERROR_CODE = re.compile(r"AADB2C\d+")


class AuthError(Exception):
    """Base class for sign-in and token failures."""


class AuthUnavailable(AuthError):
    """Kohler's auth service could not be reached — the credential is not implicated.

    Kept distinct from every other :class:`AuthError` because the two demand opposite
    responses. A rejected credential can only be fixed by the user re-authenticating; an
    unreachable token endpoint fixes itself, and prompting for reauth on a transient
    network blip would be wrong. Callers deciding whether to start a reauth flow should
    exclude this one — see ``coordinator.credential_is_dead``.
    """


class InvalidCredentials(AuthError):
    """The email or password was rejected by Kohler."""


class SignInBlocked(AuthError):
    """Sign-in needs something this client cannot do (MFA, lockout, consent)."""


@dataclass
class TokenSet:
    """An access token plus the rotating refresh token that produced it."""

    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def expired(self) -> bool:
        """True when the access token is at or near expiry."""
        return time.time() >= self.expires_at - TOKEN_EXPIRY_MARGIN_SECONDS

    @property
    def tenant_id(self) -> str | None:
        """The account id Kohler keys every device call on.

        Carried as the ``oid`` claim (falling back to ``sub``) of the access token.
        """
        return decode_tenant_id(self.access_token)


def decode_tenant_id(access_token: str | None) -> str | None:
    """Extract the tenant/customer id from a B2C access token, or None."""
    if not access_token:
        return None
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return None
    return claims.get("oid") or claims.get("sub")


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _raise_for_b2c_error(text: str) -> None:
    """Translate a B2C error code embedded in a response into an exception."""
    match = _B2C_ERROR_CODE.search(text or "")
    if not match:
        return
    code = match.group(0)
    if code == ERROR_BAD_CREDENTIALS:
        raise InvalidCredentials(
            "Kohler rejected that email or password. Check them in the Konnect app."
        )
    if code == ERROR_REDIRECT_NOT_REGISTERED:
        raise AuthError(
            f"Kohler no longer accepts this app's redirect URI ({code}). The Konnect "
            "app registration has changed and this integration needs updating."
        )
    raise SignInBlocked(f"Kohler sign-in failed ({code}).")


class KohlerAuth:
    """Signs in to Kohler Konnect and keeps a usable access token.

    Holds the rotating refresh token in memory; callers persist it via
    :attr:`refresh_token` so a restart does not need the password again.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str | None = None,
    ) -> None:
        self._session = session
        self._tokens: TokenSet | None = None
        self._refresh_token = refresh_token

    @property
    def has_credentials(self) -> bool:
        """Whether a refresh token is held at all.

        False means the integration cannot obtain an access token by itself and needs the
        password again. It does **not** mean the token is still accepted by Kohler — only a
        real request can establish that.
        """
        return bool(self.refresh_token)

    @property
    def access_token_expires_at(self) -> float | None:
        """Unix time the current access token lapses, or None if none is held.

        Expiry here is routine, not a fault: the token is refreshed on demand by the next
        request that needs one. It is worth surfacing only because a refresh that *fails*
        is how a revoked account first shows itself.
        """
        return self._tokens.expires_at if self._tokens else None

    @property
    def refresh_token(self) -> str | None:
        """The current refresh token. B2C rotates this — always persist the latest."""
        return self._tokens.refresh_token if self._tokens else self._refresh_token

    @property
    def tenant_id(self) -> str | None:
        """The signed-in account's tenant id, once a token exists."""
        return self._tokens.tenant_id if self._tokens else None

    async def async_sign_in(self, username: str, password: str) -> TokenSet:
        """Sign in with an email and password, entirely server-side.

        Runs on a dedicated session rather than the caller's. Two reasons: the B2C
        transaction cookies are scoped to this sign-in and should not leak into a shared
        session, and — critically — the jar must be built with ``quote_cookie=False``.

        aiohttp's default jar re-quotes cookie values on the way out, which mangles
        Microsoft's ``x-ms-cpim-*`` cookies; B2C then rejects the credential POST with a
        bare ``400 Bad Request`` and no error code, which looks nothing like a cookie
        problem. Verified live: identical requests differing only in this flag get 400 vs
        200.
        """
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        async with aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(quote_cookie=False)
        ) as flow_session:
            csrf, trans_id, referer = await self._async_begin(
                flow_session, challenge, state
            )
            await self._async_submit_credentials(
                flow_session, csrf, trans_id, referer, username, password
            )
            code = await self._async_collect_code(flow_session, csrf, trans_id)
        # The token exchange carries no cookies, so it uses the caller's session.
        return await self._async_exchange_code(code, verifier)

    async def _async_begin(
        self, session: aiohttp.ClientSession, challenge: str, state: str
    ) -> tuple[str, str, str]:
        """Open the sign-in transaction; return (csrf, transId, referer)."""
        params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": B2C_REDIRECT_URI,
            "scope": B2C_SCOPE,
            "state": state,
            "nonce": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "response_mode": "query",
            "prompt": "login",
        }
        try:
            async with session.get(
                B2C_AUTHORIZE_URL, params=params, timeout=aiohttp.ClientTimeout(30)
            ) as resp:
                body = await resp.text()
                referer = str(resp.url)
        except aiohttp.ClientError as err:
            raise AuthError(f"Could not reach Kohler sign-in: {err}") from err

        _raise_for_b2c_error(body)
        match = _SETTINGS.search(body)
        if not match:
            raise AuthError(
                "Kohler's sign-in page did not look as expected; the flow may have "
                "changed."
            )
        try:
            settings: dict[str, Any] = json.loads(match.group(1))
            return settings["csrf"], settings["transId"], referer
        except (json.JSONDecodeError, KeyError) as err:
            raise AuthError(f"Could not read Kohler's sign-in parameters: {err}") from err

    async def _async_submit_credentials(
        self,
        session: aiohttp.ClientSession,
        csrf: str,
        trans_id: str,
        referer: str,
        username: str,
        password: str,
    ) -> None:
        """POST the credentials. Raises InvalidCredentials on rejection."""
        try:
            async with session.post(
                B2C_SELF_ASSERTED_URL,
                params={"tx": trans_id, "p": B2C_SIGNIN_POLICY},
                data={
                    "request_type": "RESPONSE",
                    "signInName": username,
                    "password": password,
                },
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": referer,
                },
                timeout=aiohttp.ClientTimeout(30),
            ) as resp:
                body = await resp.text()
        except aiohttp.ClientError as err:
            raise AuthError(f"Network error during sign-in: {err}") from err

        # This endpoint answers 200 with a JSON body whose "status" carries the result.
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            _raise_for_b2c_error(body)
            raise AuthError("Unexpected response from Kohler during sign-in.")
        if str(payload.get("status")) != "200":
            _raise_for_b2c_error(payload.get("errorCode") or body)
            raise InvalidCredentials(
                payload.get("message") or "Kohler rejected those credentials."
            )

    async def _async_collect_code(
        self, session: aiohttp.ClientSession, csrf: str, trans_id: str
    ) -> str:
        """Read the authorization code out of B2C's redirect, without following it.

        The Location header points at the app's custom scheme, which nothing can resolve.
        That is fine: the code is a query parameter on it and we only ever read the string.
        """
        try:
            async with session.get(
                B2C_CONFIRMED_URL,
                params={
                    "csrf_token": csrf,
                    "tx": trans_id,
                    "p": B2C_SIGNIN_POLICY,
                },
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(30),
            ) as resp:
                location = resp.headers.get("Location", "")
                if not location:
                    _raise_for_b2c_error(await resp.text())
                    raise AuthError("Kohler did not return a sign-in redirect.")
        except aiohttp.ClientError as err:
            raise AuthError(f"Network error completing sign-in: {err}") from err

        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        if "error" in query:
            description = query.get("error_description", [""])[0]
            _raise_for_b2c_error(description)
            raise SignInBlocked(description or query["error"][0])
        code = query.get("code", [""])[0]
        if not code:
            raise AuthError("Kohler's sign-in redirect carried no authorization code.")
        return code

    async def _async_exchange_code(self, code: str, verifier: str) -> TokenSet:
        """Trade the authorization code for tokens."""
        return await self._async_token_request(
            {
                "client_id": CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": B2C_REDIRECT_URI,
                "code_verifier": verifier,
                "scope": B2C_SCOPE,
            }
        )

    async def async_refresh(self, refresh_token: str | None = None) -> TokenSet:
        """Mint a fresh access token from the refresh token.

        B2C issues a NEW refresh token on every refresh and invalidates the old one, so the
        result must be persisted or the account is stranded once the old token expires.
        """
        token = refresh_token or self.refresh_token
        if not token:
            raise AuthError("No refresh token available; sign in again.")
        return await self._async_token_request(
            {
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": token,
                "scope": B2C_SCOPE,
            }
        )

    async def _async_token_request(self, data: dict[str, str]) -> TokenSet:
        """POST to the token endpoint and store the resulting TokenSet."""
        try:
            async with self._session.post(
                B2C_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(30),
            ) as resp:
                payload = await resp.json(content_type=None)
                if resp.status != 200:
                    detail = (
                        payload.get("error_description")
                        or payload.get("error")
                        or f"HTTP {resp.status}"
                    )
                    _raise_for_b2c_error(str(detail))
                    raise AuthError(f"Kohler token request failed: {detail}")
        except aiohttp.ClientError as err:
            raise AuthUnavailable(
                f"Network error during token request: {err}"
            ) from err

        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token") or self.refresh_token
        if not access_token or not refresh_token:
            raise AuthError("Kohler did not return a usable token pair.")

        self._tokens = TokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + float(payload.get("expires_in", 3600)),
        )
        self._refresh_token = refresh_token
        return self._tokens

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing it if needed."""
        if self._tokens is None or self._tokens.expired:
            await self.async_refresh()
        assert self._tokens is not None
        return self._tokens.access_token

"""OAuth 2.0 helpers for the four publishing platforms.

This module deliberately uses the authorization-code flow with PKCE and a
loopback callback instead of an SDK. The desktop app owns the browser hand-off;
the backend only exchanges codes and stores tokens in the OS credential store.
"""

from __future__ import annotations

import base64
import hashlib
import secrets as random_secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

META_VERSION = "v23.0"
CALLBACK_PATH = "/api/connections/callback"


def callback_url(base_url: str) -> str:
    """The loopback callback for the origin serving the app.

    The desktop shell owns the port and the browser dev server proxies the
    callback, so the redirect follows the request instead of a constant. A
    provider registration must match exactly, which is why the Accounts tab
    shows this same URL.
    """
    return base_url.rstrip("/") + CALLBACK_PATH


DEFAULT_REDIRECT = callback_url("http://127.0.0.1:8756")
PENDING_TTL_S = 600.0


class OAuthError(RuntimeError):
    """A provider or configuration error safe to show to the user."""

    def __init__(self, message: str, *, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class OAuthProvider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    scope_separator: str = " "
    client_id_param: str = "client_id"
    client_auth: str = "post"  # post | basic_if_secret
    pkce: bool = True
    manual_callback: bool = False
    refresh_mode: str = "refresh_token"  # refresh_token | fb_exchange_token | none
    extra_auth: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, OAuthProvider] = {
    "youtube": OAuthProvider(
        name="youtube",
        label="YouTube",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=(
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ),
        extra_auth={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    ),
    "x": OAuthProvider(
        name="x",
        label="X",
        authorize_url="https://twitter.com/i/oauth2/authorize",
        token_url="https://api.x.com/2/oauth2/token",
        scopes=("tweet.read", "tweet.write", "users.read", "media.write", "offline.access"),
        client_auth="basic_if_secret",
    ),
    "tiktok": OAuthProvider(
        name="tiktok",
        label="TikTok",
        authorize_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        scopes=("user.info.basic", "video.upload", "video.list"),
        scope_separator=",",
        client_id_param="client_key",
        manual_callback=True,
    ),
    "instagram": OAuthProvider(
        name="instagram",
        label="Instagram",
        authorize_url=f"https://www.facebook.com/{META_VERSION}/dialog/oauth",
        token_url=f"https://graph.facebook.com/{META_VERSION}/oauth/access_token",
        scopes=(
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_insights",
            "pages_show_list",
            "pages_read_engagement",
        ),
        scope_separator=",",
        manual_callback=True,
        refresh_mode="fb_exchange_token",
    ),
}


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scopes: list[str] = field(default_factory=list)
    token_type: str = "Bearer"
    raw: dict[str, Any] = field(default_factory=dict)

    def expired(self, skew_s: float = 60.0) -> bool:
        return bool(self.expires_at) and self.expires_at <= time.time() + skew_s

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TokenBundle":
        return cls(
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token", "")),
            expires_at=float(data.get("expires_at", 0.0) or 0.0),
            scopes=list(data.get("scopes", []) or []),
            token_type=str(data.get("token_type", "Bearer") or "Bearer"),
            raw=data.get("raw", {}) if isinstance(data.get("raw", {}), dict) else {},
        )

    @classmethod
    def from_response(cls, payload: dict) -> "TokenBundle":
        access = str(payload.get("access_token", ""))
        if not access:
            raise OAuthError("The provider returned no access token.")
        expires_in = payload.get("expires_in")
        try:
            expires_at = time.time() + float(expires_in) if expires_in else 0.0
        except (TypeError, ValueError):
            expires_at = 0.0
        scope = payload.get("scope", "")
        if isinstance(scope, str):
            scopes = [s for s in scope.replace(",", " ").split() if s]
        elif isinstance(scope, list):
            scopes = [str(s) for s in scope]
        else:
            scopes = []
        return cls(
            access_token=access,
            refresh_token=str(payload.get("refresh_token", "") or ""),
            expires_at=expires_at,
            scopes=scopes,
            token_type=str(payload.get("token_type", "Bearer") or "Bearer"),
            raw={k: v for k, v in payload.items() if k not in {"access_token", "refresh_token"}},
        )


@dataclass
class AuthStart:
    platform: str
    url: str
    state: str
    redirect_uri: str
    manual_callback: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Pending:
    platform: str
    state: str
    verifier: str
    redirect_uri: str
    client_id: str
    client_secret: str
    created_at: float


_PENDING: dict[str, _Pending] = {}
_LOCK = threading.Lock()


def provider(platform: str) -> OAuthProvider:
    try:
        return PROVIDERS[platform]
    except KeyError as exc:
        raise OAuthError(f"Unknown platform: {platform}") from exc


def _pkce_pair() -> tuple[str, str]:
    verifier = random_secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _prune() -> None:
    cutoff = time.time() - PENDING_TTL_S
    for key, value in list(_PENDING.items()):
        if value.created_at < cutoff:
            _PENDING.pop(key, None)


def start(
    platform: str,
    client_id: str,
    client_secret: str = "",
    redirect_uri: str = "",
    scopes: tuple[str, ...] | list[str] | None = None,
    code_verifier: str | None = None,
) -> AuthStart:
    cfg = provider(platform)
    client_id = client_id.strip()
    if not client_id:
        raise OAuthError(f"Enter the {cfg.label} client ID first.")
    redirect_uri = (redirect_uri or DEFAULT_REDIRECT).strip()
    verifier, challenge = _pkce_pair()
    if code_verifier is not None:
        verifier = code_verifier
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    state = random_secrets.token_urlsafe(24)
    params: dict[str, str] = {
        cfg.client_id_param: client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg.scope_separator.join(scopes or cfg.scopes),
        "state": state,
    }
    if cfg.pkce:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    params.update(cfg.extra_auth)
    with _LOCK:
        _prune()
        _PENDING[state] = _Pending(
            platform=platform,
            state=state,
            verifier=verifier,
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_secret=client_secret.strip(),
            created_at=time.time(),
        )
    return AuthStart(
        platform=platform,
        url=cfg.authorize_url + "?" + urlencode(params),
        state=state,
        redirect_uri=redirect_uri,
        manual_callback=cfg.manual_callback,
    )


def pending(state: str) -> _Pending | None:
    with _LOCK:
        _prune()
        return _PENDING.get(state)


def _take_pending(state: str) -> _Pending:
    with _LOCK:
        _prune()
        item = _PENDING.pop(state, None)
    if item is None:
        raise OAuthError("This connection attempt expired. Start again from the app.")
    return item


def _error_message(response: httpx.Response) -> tuple[str, str]:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        data = {}
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "OAuth request failed"), str(error.get("code") or "")
        if error:
            description = data.get("error_description") or data.get("error_message") or ""
            return f"{error}: {description}".strip(": "), str(error)
    return f"OAuth request failed ({response.status_code})", ""


def _request_token(
    cfg: OAuthProvider,
    data: dict[str, str],
    client_id: str,
    client_secret: str,
    client: httpx.Client | None = None,
) -> TokenBundle:
    payload = dict(data)
    if cfg.client_auth == "basic_if_secret" and client_secret:
        auth: tuple[str, str] | None = (client_id, client_secret)
        # One client authentication method, not two: providers reject requests
        # that carry both Basic credentials and client_secret in the body.
        payload.pop("client_id", None)
        payload.pop("client_secret", None)
    else:
        auth = None
        if cfg.client_id_param not in payload:
            payload[cfg.client_id_param] = client_id
        if client_secret:
            payload["client_secret"] = client_secret
    owned = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.post(cfg.token_url, data=payload, auth=auth)
    finally:
        if owned:
            client.close()
    if response.status_code >= 400:
        message, code = _error_message(response)
        raise OAuthError(message, code=code, status=response.status_code)
    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        raise OAuthError("The provider returned a non-JSON token response.", status=response.status_code) from exc
    if not isinstance(body, dict):
        raise OAuthError("The provider returned an unexpected token response.")
    return TokenBundle.from_response(body)


def complete(
    code: str,
    state: str,
    client: httpx.Client | None = None,
) -> tuple[AuthStart, TokenBundle]:
    item = _take_pending(state)
    cfg = provider(item.platform)
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": item.redirect_uri,
    }
    if cfg.pkce:
        data["code_verifier"] = item.verifier
    if cfg.client_id_param == "client_key":
        data["client_key"] = item.client_id
    else:
        data["client_id"] = item.client_id
    if item.client_secret:
        data["client_secret"] = item.client_secret
    token = _request_token(cfg, data, item.client_id, item.client_secret, client)
    start = AuthStart(
        platform=item.platform,
        url="",
        state=item.state,
        redirect_uri=item.redirect_uri,
        manual_callback=cfg.manual_callback,
    )
    return start, token


def refresh(
    platform: str,
    refresh_token: str,
    client_id: str,
    client_secret: str = "",
    client: httpx.Client | None = None,
) -> TokenBundle:
    cfg = provider(platform)
    if cfg.refresh_mode == "none":
        raise OAuthError(f"{cfg.label} does not support token refresh; reconnect the account.")
    if not refresh_token:
        raise OAuthError(f"{cfg.label} needs a reconnect: no refresh token was stored.")
    if cfg.refresh_mode == "fb_exchange_token":
        data = {"grant_type": "fb_exchange_token", "fb_exchange_token": refresh_token}
    else:
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if cfg.client_id_param == "client_key":
        data["client_key"] = client_id
    else:
        data["client_id"] = client_id
    if client_secret:
        data["client_secret"] = client_secret
    return _request_token(cfg, data, client_id, client_secret, client)


def revoke(
    platform: str,
    token: str,
    client_id: str = "",
    client_secret: str = "",
    client: httpx.Client | None = None,
) -> bool:
    """Best-effort revocation. Returns False when the provider has no endpoint."""
    cfg = provider(platform)
    auth: tuple[str, str] | None = None
    if platform == "youtube":
        url = "https://oauth2.googleapis.com/revoke"
        data = {"token": token}
    elif platform == "x":
        url = "https://api.x.com/2/oauth2/revoke"
        data = {"token": token, "token_type_hint": "access_token"}
        # X requires client authentication on the revoke endpoint.
        if client_secret:
            auth = (client_id, client_secret)
    else:
        return False
    owned = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        response = client.post(url, data=data, auth=auth)
    finally:
        if owned:
            client.close()
    return response.status_code < 400


def _get(client: httpx.Client, url: str, token: str, params: dict | None = None) -> dict:
    response = client.get(url, params=params or {}, headers={"Authorization": f"Bearer {token}"})
    if response.status_code >= 400:
        message, code = _error_message(response)
        raise OAuthError(message, code=code, status=response.status_code)
    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        raise OAuthError("The provider returned a non-JSON identity response.") from exc
    return body if isinstance(body, dict) else {}


def fetch_identity(
    platform: str,
    token: str,
    client: httpx.Client | None = None,
) -> dict:
    """Return a small, stable identity record for the connected account."""
    owned = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        if platform == "youtube":
            body = _get(
                client,
                "https://www.googleapis.com/youtube/v3/channels",
                token,
                {"part": "snippet", "mine": "true"},
            )
            items = body.get("items") or []
            if not items:
                raise OAuthError("No YouTube channel is attached to this Google account.")
            item = items[0]
            snippet = item.get("snippet", {})
            return {
                "external_id": str(item.get("id", "")),
                "handle": str(snippet.get("customUrl", "") or ""),
                "display_name": str(snippet.get("title", "") or "YouTube channel"),
                "avatar_url": str((snippet.get("thumbnails") or {}).get("default", {}).get("url", "") or ""),
            }
        if platform == "x":
            body = _get(client, "https://api.x.com/2/users/me", token, {"user.fields": "profile_image_url"})
            data = body.get("data") or {}
            if not data.get("id"):
                raise OAuthError("X did not return an account identity.")
            return {
                "external_id": str(data.get("id", "")),
                "handle": str(data.get("username", "") or ""),
                "display_name": str(data.get("name", "") or "X account"),
                "avatar_url": str(data.get("profile_image_url", "") or ""),
            }
        if platform == "tiktok":
            body = _get(
                client,
                "https://open.tiktokapis.com/v2/user/info/",
                token,
                {"fields": "open_id,display_name,avatar_url"},
            )
            data = (body.get("data") or {}).get("user") or {}
            if not data.get("open_id"):
                raise OAuthError("TikTok did not return an account identity.")
            return {
                "external_id": str(data.get("open_id", "")),
                "handle": str(data.get("display_name", "") or ""),
                "display_name": str(data.get("display_name", "") or "TikTok account"),
                "avatar_url": str(data.get("avatar_url", "") or ""),
            }
        if platform == "instagram":
            response = client.get(
                f"https://graph.facebook.com/{META_VERSION}/me/accounts",
                params={
                    "fields": "id,name,instagram_business_account{id,username,profile_picture_url}",
                    "access_token": token,
                },
            )
            if response.status_code >= 400:
                message, code = _error_message(response)
                raise OAuthError(message, code=code, status=response.status_code)
            body = response.json()
            for page in body.get("data", []) if isinstance(body, dict) else []:
                ig = page.get("instagram_business_account") or {}
                if ig.get("id"):
                    return {
                        "external_id": str(ig.get("id", "")),
                        "handle": str(ig.get("username", "") or ""),
                        "display_name": str(ig.get("username", "") or "Instagram account"),
                        "avatar_url": str(ig.get("profile_picture_url", "") or ""),
                        "page_id": str(page.get("id", "") or ""),
                    }
            raise OAuthError("No Instagram professional account is linked to a Facebook Page.")
        raise OAuthError(f"Identity lookup is not implemented for {platform}.")
    finally:
        if owned:
            client.close()


def clear_for_tests() -> None:
    with _LOCK:
        _PENDING.clear()


def debug_state() -> dict:
    """Diagnostics without tokens or client secrets."""
    with _LOCK:
        _prune()
        return {
            "pending": len(_PENDING),
            "platforms": sorted(PROVIDERS),
            "redirect": DEFAULT_REDIRECT,
        }

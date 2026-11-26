"""Connected platform accounts and token lifecycle.

Raw tokens never touch SQLite. The database stores a reference to an entry in
the OS credential store; this module is the only code that resolves it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import db, secrets
from .publish import limits, oauth


class AccountError(RuntimeError):
    """Base class for account failures shown to the user."""


class ReconnectRequired(AccountError):
    """The token is missing, expired, or revoked; the user must reconnect."""


@dataclass
class Account:
    id: str
    platform: str
    external_id: str
    handle: str = ""
    display_name: str = ""
    avatar_url: str = ""
    scopes: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    status: str = "connected"
    token_expires_at: float = 0.0
    last_sync_at: float = 0.0
    last_error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    def to_dict(self) -> dict:
        limits_row = limits.LIMITS.get(self.platform)
        return {
            "id": self.id,
            "platform": self.platform,
            "label": limits_row.label if limits_row else self.platform,
            "external_id": self.external_id,
            "handle": self.handle,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "scopes": self.scopes,
            "capabilities": self.capabilities,
            "status": self.status,
            "connected": self.connected,
            "token_expires_at": self.token_expires_at,
            "last_sync_at": self.last_sync_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def account_id(platform: str, external_id: str) -> str:
    digest = hashlib.sha1(f"{platform}:{external_id}".encode("utf-8")).hexdigest()[:16]
    return f"acct_{digest}"


def token_key(account: str) -> str:
    return f"account.{account}.token"


def provider_key(platform: str) -> str:
    return f"provider.{platform}.client"


def save_provider_client(platform: str, client_id: str, client_secret: str = "") -> None:
    secrets.set_json(provider_key(platform), {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
    })


def load_provider_client(platform: str) -> dict:
    data = secrets.get_json(provider_key(platform))
    return {
        "client_id": str(data.get("client_id", "")),
        "client_secret": str(data.get("client_secret", "")),
    }


def save_tokens(account: str, tokens: oauth.TokenBundle, *, preserve_refresh: bool = True) -> None:
    existing = load_tokens(account) if preserve_refresh else None
    if preserve_refresh and existing and not tokens.refresh_token:
        tokens.refresh_token = existing.refresh_token
    secrets.set_json(token_key(account), tokens.to_dict())


def load_tokens(account: str) -> oauth.TokenBundle | None:
    data = secrets.get_json(token_key(account))
    if not data or not data.get("access_token"):
        return None
    return oauth.TokenBundle.from_dict(data)


def _row_to_account(row) -> Account:
    def parsed(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return fallback

    return Account(
        id=row["id"],
        platform=row["platform"],
        external_id=row["external_id"],
        handle=row["handle"],
        display_name=row["display_name"],
        avatar_url=row["avatar_url"],
        scopes=parsed(row["scopes"], []),
        capabilities=parsed(row["capabilities"], {}),
        status=row["status"],
        token_expires_at=row["token_expires_at"],
        last_sync_at=row["last_sync_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_account(account: str) -> Account | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account,)).fetchone()
    return _row_to_account(row) if row else None


def list_accounts(platform: str | None = None) -> list[Account]:
    with db.connect() as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE platform=? ORDER BY created_at DESC", (platform,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM accounts ORDER BY created_at DESC").fetchall()
    return [_row_to_account(row) for row in rows]


def connect_account(
    platform: str,
    tokens: oauth.TokenBundle,
    client_id: str,
    client_secret: str = "",
    identity: dict | None = None,
    client: httpx.Client | None = None,
) -> Account:
    if platform not in limits.LIMITS:
        raise AccountError(f"Unknown platform: {platform}")
    if not tokens.access_token:
        raise AccountError("The provider returned no access token.")
    identity = identity or oauth.fetch_identity(platform, tokens.access_token, client=client)
    external_id = str(identity.get("external_id", "")).strip()
    if not external_id:
        raise AccountError("The provider returned no account id.")
    account = account_id(platform, external_id)
    caps = limits.capabilities_for(platform)
    extra = identity.get("capabilities")
    if isinstance(extra, dict):
        caps.update(extra)
    now = time.time()
    save_provider_client(platform, client_id, client_secret)
    save_tokens(account, tokens, preserve_refresh=False)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO accounts
                (id, platform, external_id, handle, display_name, avatar_url, scopes,
                 capabilities, status, token_ref, client_ref, token_expires_at,
                 last_sync_at, last_error, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                handle=excluded.handle, display_name=excluded.display_name,
                avatar_url=excluded.avatar_url, scopes=excluded.scopes,
                capabilities=excluded.capabilities, status=excluded.status,
                token_ref=excluded.token_ref, client_ref=excluded.client_ref,
                token_expires_at=excluded.token_expires_at, last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (
                account, platform, external_id,
                str(identity.get("handle", "") or ""),
                str(identity.get("display_name", "") or ""),
                str(identity.get("avatar_url", "") or ""),
                json.dumps(tokens.scopes),
                json.dumps(caps),
                "connected",
                token_key(account),
                provider_key(platform),
                tokens.expires_at,
                0.0,
                "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account,)).fetchone()
    return _row_to_account(row)


def mark_error(account: str, message: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE accounts SET status=?, last_error=?, updated_at=? WHERE id=?",
            ("reconnect", message[:500], time.time(), account),
        )


def mark_synced(account: str, when: float | None = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE accounts SET last_sync_at=?, status=?, last_error=?, updated_at=? WHERE id=?",
            (when or time.time(), "connected", "", time.time(), account),
        )


def delete_account(account: str) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM accounts WHERE id=?", (account,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM accounts WHERE id=?", (account,))
    secrets.delete_secret(token_key(account))
    return True


def access_token(account: str, client: httpx.Client | None = None) -> str:
    """Return a valid access token, refreshing it when possible."""
    record = get_account(account)
    if record is None:
        raise AccountError("That account is no longer connected.")
    tokens = load_tokens(account)
    if tokens is None:
        mark_error(account, "No stored token")
        raise ReconnectRequired(f"Reconnect {record.display_name or record.platform} to continue.")
    if not tokens.expired():
        return tokens.access_token
    creds = load_provider_client(record.platform)
    try:
        refreshed = oauth.refresh(
            record.platform,
            tokens.refresh_token,
            creds["client_id"],
            creds["client_secret"],
            client=client,
        )
    except oauth.OAuthError as exc:
        mark_error(account, str(exc))
        raise ReconnectRequired(f"Reconnect {record.display_name or record.platform}: {exc}") from exc
    save_tokens(account, refreshed)
    with db.connect() as conn:
        conn.execute(
            "UPDATE accounts SET token_expires_at=?, status=?, last_error=?, updated_at=? WHERE id=?",
            (refreshed.expires_at, "connected", "", time.time(), account),
        )
    return refreshed.access_token


def account_count(platform: str | None = None) -> int:
    with db.connect() as conn:
        if platform:
            row = conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE platform=?", (platform,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()
    return int(row["n"]) if row else 0

import time

import pytest

from clipper import accounts, db, secrets
from clipper.publish import oauth


def tokens(**overrides):
    base = dict(access_token="access-1", refresh_token="refresh-1", expires_at=time.time() + 3600)
    base.update(overrides)
    return oauth.TokenBundle(**base)


def connect(platform="youtube", external_id="UC1", token=None):
    return accounts.connect_account(
        platform,
        token or tokens(),
        "client-id",
        "client-secret",
        identity={
            "external_id": external_id,
            "handle": "@handle",
            "display_name": "A Channel",
            "avatar_url": "https://img",
        },
    )


def test_connect_stores_the_row_and_keeps_the_token_out_of_sqlite(clean_db):
    account = connect()
    assert account.platform == "youtube"
    assert account.connected is True
    assert account.capabilities["analytics"] is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account.id,)).fetchone()
    assert row["token_ref"]
    assert "access-1" not in str(dict(row))
    assert accounts.load_tokens(account.id).access_token == "access-1"


def test_connecting_the_same_identity_updates_instead_of_duplicating(clean_db):
    first = connect()
    second = connect(token=tokens(access_token="access-2"))
    assert first.id == second.id
    assert accounts.account_count("youtube") == 1
    assert accounts.load_tokens(first.id).access_token == "access-2"


def test_list_and_delete_only_touch_the_selected_account(clean_db):
    one = connect("youtube", "UC1")
    two = connect("x", "X1")
    assert {row.id for row in accounts.list_accounts()} == {one.id, two.id}
    assert [row.id for row in accounts.list_accounts("x")] == [two.id]
    assert accounts.delete_account(one.id) is True
    assert accounts.get_account(one.id) is None
    assert accounts.get_account(two.id) is not None
    assert accounts.load_tokens(one.id) is None


def test_delete_revokes_the_remote_token_before_forgetting_it(clean_db, monkeypatch):
    account = connect("x", "X1")
    calls = []

    def fake_revoke(platform, token, client_id="", client_secret="", client=None):
        calls.append((platform, token, client_id, client_secret))
        return True

    monkeypatch.delenv("CLIPPER_DISABLE_REVOKE", raising=False)
    monkeypatch.setattr(oauth, "revoke", fake_revoke)
    assert accounts.delete_account(account.id) is True
    assert calls == [("x", "access-1", "client-id", "client-secret")]


def test_access_token_refreshes_an_expired_token_and_preserves_refresh(clean_db, monkeypatch):
    account = connect(token=tokens(expires_at=time.time() - 10))
    monkeypatch.setattr(
        oauth,
        "refresh",
        lambda platform, refresh_token, cid, csecret, client=None: tokens(
            access_token="access-new", refresh_token="", expires_at=time.time() + 3600
        ),
    )
    assert accounts.access_token(account.id) == "access-new"
    saved = accounts.load_tokens(account.id)
    assert saved.access_token == "access-new"
    assert saved.refresh_token == "refresh-1"


def test_missing_token_requires_reconnect(clean_db):
    account = connect()
    secrets.delete_secret(accounts.token_key(account.id))
    with pytest.raises(accounts.ReconnectRequired, match="Reconnect"):
        accounts.access_token(account.id)
    assert accounts.get_account(account.id).status == "reconnect"


def test_failed_refresh_marks_the_account_for_reconnect(clean_db, monkeypatch):
    account = connect(token=tokens(expires_at=time.time() - 10))

    def fail(*args, **kwargs):
        raise oauth.OAuthError("refresh expired")

    monkeypatch.setattr(oauth, "refresh", fail)
    with pytest.raises(accounts.ReconnectRequired, match="refresh expired"):
        accounts.access_token(account.id)
    assert accounts.get_account(account.id).status == "reconnect"


def test_unknown_account_is_a_clear_error(clean_db):
    with pytest.raises(accounts.AccountError, match="no longer connected"):
        accounts.access_token("acct_missing")


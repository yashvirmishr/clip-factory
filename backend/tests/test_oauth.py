import httpx
import pytest
from urllib.parse import parse_qs, urlparse

from clipper.publish import oauth


@pytest.fixture(autouse=True)
def _clear_pending():
    oauth.clear_for_tests()
    yield
    oauth.clear_for_tests()


class FakeClient:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.last = None

    def post(self, url, data=None, auth=None):
        self.last = {"url": url, "data": dict(data or {}), "auth": auth}
        return httpx.Response(self.status, json=self.payload)

    def get(self, url, params=None, headers=None):
        self.last = {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        return httpx.Response(self.status, json=self.payload)

    def close(self):
        pass


def test_start_builds_a_pkce_authorization_url_without_storing_tokens():
    start = oauth.start("youtube", "client-123", "secret-456", "http://127.0.0.1:8756/cb")
    query = parse_qs(urlparse(start.url).query)
    assert query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8756/cb"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in query
    assert query["state"] == [start.state]
    assert start.manual_callback is False


def test_complete_exchanges_a_code_and_consumes_state():
    start = oauth.start("youtube", "client-123", "secret-456")
    fake = FakeClient({
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/youtube.upload",
        "token_type": "Bearer",
    })
    started, token = oauth.complete("code-1", start.state, client=fake)
    assert started.platform == "youtube"
    assert token.access_token == "access"
    assert token.refresh_token == "refresh"
    assert token.expires_at > 0
    assert "refresh" not in fake.last["data"].values()

    with pytest.raises(oauth.OAuthError, match="expired"):
        oauth.complete("code-1", start.state, client=fake)


def test_a_provider_error_is_reported_without_leaking_the_code():
    start = oauth.start("youtube", "client-123")
    fake = FakeClient({"error": "invalid_grant", "error_description": "Bad code"}, status=400)
    with pytest.raises(oauth.OAuthError) as excinfo:
        oauth.complete("secret-code", start.state, client=fake)
    assert "Bad code" in str(excinfo.value)
    assert "secret-code" not in str(excinfo.value)


def test_public_x_client_uses_pkce_without_a_secret():
    start = oauth.start("x", "public-client")
    query = parse_qs(urlparse(start.url).query)
    assert query["code_challenge_method"] == ["S256"]
    fake = FakeClient({"access_token": "x-access", "expires_in": 7200})
    _started, token = oauth.complete("x-code", start.state, client=fake)
    assert token.access_token == "x-access"
    assert fake.last["auth"] is None
    assert fake.last["data"]["client_id"] == "public-client"


def test_confidential_x_client_uses_basic_auth():
    fake = FakeClient({"access_token": "new", "refresh_token": "new-refresh", "expires_in": 7200})
    token = oauth.refresh("x", "old-refresh", "cid", "csecret", client=fake)
    assert token.access_token == "new"
    assert fake.last["auth"] == ("cid", "csecret")
    assert "client_id" not in fake.last["data"]
    assert "client_secret" not in fake.last["data"]


def test_facebook_mode_uses_fb_exchange_token():
    fake = FakeClient({"access_token": "long-lived", "token_type": "bearer"})
    token = oauth.refresh("instagram", "short-lived", "cid", "csecret", client=fake)
    assert token.access_token == "long-lived"
    assert fake.last["data"]["grant_type"] == "fb_exchange_token"
    assert fake.last["data"]["fb_exchange_token"] == "short-lived"


def test_youtube_identity_is_reduced_to_the_fields_we_store():
    fake = FakeClient({
        "items": [{
            "id": "UC123",
            "snippet": {
                "title": "The Channel",
                "customUrl": "@channel",
                "thumbnails": {"default": {"url": "https://img"}},
            },
        }]
    })
    identity = oauth.fetch_identity("youtube", "token", client=fake)
    assert identity == {
        "external_id": "UC123",
        "handle": "@channel",
        "display_name": "The Channel",
        "avatar_url": "https://img",
    }
    assert fake.last["headers"]["Authorization"] == "Bearer token"


def test_unknown_platform_is_rejected():
    with pytest.raises(oauth.OAuthError):
        oauth.provider("twitch")


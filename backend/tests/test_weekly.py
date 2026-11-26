import time

from clipper import accounts, analytics, weekly
from clipper.publish import oauth
from clipper.publish.base import RemotePost


class FakeAdapter:
    def fetch_posts(self, token, limit=50):
        now = time.time()
        return [
            RemotePost(
                platform_post_id=f"v{i}", url=f"https://youtu.be/v{i}",
                published_at=now - 48 * 3600, title=f"Clip {i}", duration_s=30,
                metrics={"views": 100 * (i + 1), "likes": 10 + i, "comments": 1},
            )
            for i in range(10)
        ]

    def fetch_profile(self, token):
        return {"followers": 100}


def connect():
    return accounts.connect_account(
        "youtube",
        oauth.TokenBundle(access_token="token", expires_at=time.time() + 3600),
        "client-id", "client-secret",
        identity={"external_id": "UC1", "display_name": "Channel"},
    )


def test_weekly_run_syncs_accounts_and_records_the_next_date(clean_db, monkeypatch):
    account = connect()
    monkeypatch.setattr(analytics, "adapter_for_analytics", lambda platform: FakeAdapter())
    weekly.clear_for_tests()
    before = weekly.status()
    assert before["due"] is True
    result = weekly.run(now=1_800_000_000.0)
    assert result["results"][0]["ok"] is True
    assert result["results"][0]["new_posts"] == 10
    after = weekly.status(now=1_800_000_001.0)
    assert after["due"] is False
    assert after["next_run"] == 1_800_000_000.0 + weekly.INTERVAL_S
    assert after["training"]["posts"] == 0


def test_weekly_status_is_due_again_after_seven_days(clean_db):
    weekly.clear_for_tests()
    weekly.run(now=1_800_000_000.0)
    assert weekly.status(now=1_800_000_000.0 + weekly.INTERVAL_S + 1)["due"] is True

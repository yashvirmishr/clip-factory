import pytest

from clipper.publish import MediaInfo, PublishDraft, limits, validate


def media(**overrides):
    base = dict(duration=45.0, width=1080, height=1920, size_bytes=10_000_000, has_audio=True, format="mp4")
    base.update(overrides)
    return MediaInfo(**base)


def test_youtube_accepts_a_vertical_short():
    result = validate(PublishDraft(platform="youtube", media=media(), title="A hook", visibility="public"))
    assert result.ok
    assert result.limits is not None and result.limits.platform == "youtube"
    assert not any(issue.severity == "block" for issue in result.issues)


def test_too_long_is_a_block_with_a_remedy():
    result = validate(PublishDraft(platform="youtube", media=media(duration=181), visibility="public"))
    assert result.ok is False
    issue = next(item for item in result.issues if item.code == "too_long")
    assert issue.severity == "block"
    assert "180" in issue.remedy


def test_caption_and_hashtag_limits_are_hard_blocks():
    result = validate(PublishDraft(
        platform="youtube",
        media=media(),
        caption="x" * 5001,
        hashtags=[f"#tag{i}" for i in range(16)],
    ))
    codes = {issue.code for issue in result.issues if issue.severity == "block"}
    assert {"caption_limit", "hashtag_limit"} <= codes


def test_landscape_is_a_warning_not_a_block():
    result = validate(PublishDraft(platform="youtube", media=media(width=1920, height=1080)))
    assert result.ok
    assert any(issue.code == "aspect" and issue.severity == "warn" for issue in result.issues)


def test_x_accepts_any_aspect():
    result = validate(PublishDraft(platform="x", media=media(width=1920, height=1080, duration=60), visibility="public"))
    assert result.ok
    assert not any(issue.code == "aspect" for issue in result.issues)


def test_tiktok_review_and_schedule_are_warnings():
    result = validate(PublishDraft(platform="tiktok", media=media(), scheduled_at=1.0))
    codes = {issue.code for issue in result.issues if issue.severity == "warn"}
    assert "review" in codes
    assert "app_queue" in codes


def test_instagram_requires_a_public_url_as_a_warning():
    result = validate(PublishDraft(platform="instagram", media=media(duration=5), visibility="public"))
    assert result.ok
    assert any(issue.code == "public_url" for issue in result.issues)


def test_unknown_platform_is_an_explicit_key_error():
    with pytest.raises(KeyError):
        validate(PublishDraft(platform="twitch", media=media()))


def test_limits_registry_is_complete_and_ordered():
    assert set(limits.LIMITS) == set(limits.PLATFORMS)
    for platform, row in limits.LIMITS.items():
        assert row.platform == platform
        assert row.max_duration_s > row.min_duration_s
        assert row.caption_limit > 0


def test_capabilities_do_not_claim_review_is_approval():
    caps = limits.capabilities_for("tiktok")
    assert caps["requires_review"] is True
    assert caps["direct_post"] is True
    assert "audited" in caps["note"]

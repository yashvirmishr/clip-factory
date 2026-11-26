"""Platform limits and publish validation.

Every number here is a product constraint, not a suggestion. The registry is
versioned by ``last_verified`` so a stale value is visible instead of silently
becoming wrong. Adapters may narrow these limits per account, but they may not
widen them without an explicit capability response from the platform.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Platform = Literal["youtube", "tiktok", "instagram", "x"]
Severity = Literal["block", "warn"]

PLATFORMS: tuple[str, ...] = ("youtube", "tiktok", "instagram", "x")


@dataclass(frozen=True)
class PlatformLimits:
    platform: str
    label: str
    min_duration_s: float
    max_duration_s: float
    max_bytes: int
    caption_limit: int
    title_limit: int
    max_hashtags: int
    aspect: str
    aspect_tolerance: float = 0.08
    has_audio_required: bool = False
    direct_post: bool = True
    inbox_upload: bool = False
    analytics: bool = True
    retention: bool = False
    native_schedule: bool = False
    requires_public_url: bool = False
    requires_review: bool = False
    max_posts_per_24h: int = 0
    allowed_visibility: tuple[str, ...] = ("public",)
    note: str = ""
    last_verified: str = "2026-11"

    def as_dict(self) -> dict:
        return asdict(self)


LIMITS: dict[str, PlatformLimits] = {
    "youtube": PlatformLimits(
        platform="youtube",
        label="YouTube Shorts",
        min_duration_s=1.0,
        max_duration_s=180.0,
        max_bytes=256 * 1024**3,
        caption_limit=5000,
        title_limit=100,
        max_hashtags=15,
        aspect="9:16",
        direct_post=True,
        analytics=True,
        retention=True,
        native_schedule=True,
        allowed_visibility=("public", "unlisted", "private"),
        max_posts_per_24h=100,
        note="Vertical/square videos up to 3 minutes publish as Shorts. Uploads share a per-project daily bucket.",
    ),
    "tiktok": PlatformLimits(
        platform="tiktok",
        label="TikTok",
        min_duration_s=1.0,
        max_duration_s=600.0,
        max_bytes=4 * 1024**3,
        caption_limit=2200,
        title_limit=0,
        max_hashtags=20,
        aspect="9:16",
        direct_post=True,
        inbox_upload=True,
        analytics=True,
        native_schedule=False,
        requires_review=True,
        max_posts_per_24h=5,
        allowed_visibility=("public", "friends", "private"),
        note="Public Direct Post needs an audited app. Before approval, use inbox upload and finish in TikTok.",
    ),
    "instagram": PlatformLimits(
        platform="instagram",
        label="Instagram Reels",
        min_duration_s=3.0,
        max_duration_s=180.0,
        max_bytes=1024**3,
        caption_limit=2200,
        title_limit=0,
        max_hashtags=30,
        aspect="9:16",
        direct_post=True,
        analytics=True,
        retention=True,
        native_schedule=False,
        requires_public_url=True,
        requires_review=True,
        max_posts_per_24h=50,
        allowed_visibility=("public",),
        note="Needs a professional account, a Meta app, and either a public video URL or the Facebook-Login resumable path.",
    ),
    "x": PlatformLimits(
        platform="x",
        label="X",
        min_duration_s=0.5,
        max_duration_s=140.0,
        max_bytes=512 * 1024**2,
        caption_limit=280,
        title_limit=0,
        max_hashtags=10,
        aspect="any",
        aspect_tolerance=1.0,
        direct_post=True,
        analytics=True,
        native_schedule=False,
        max_posts_per_24h=0,
        allowed_visibility=("public",),
        note="Text limit depends on the account tier; the adapter checks the live account before posting.",
    ),
}


@dataclass(frozen=True)
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    has_audio: bool = True
    format: str = ""

    @property
    def portrait(self) -> bool:
        return self.height >= self.width


@dataclass
class ValidationIssue:
    field: str
    code: str
    severity: Severity
    message: str
    remedy: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    limits: PlatformLimits | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "limits": self.limits.as_dict() if self.limits else None,
        }


@dataclass
class PublishDraft:
    platform: str
    media: MediaInfo
    title: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    visibility: str = "private"
    scheduled_at: float = 0.0
    made_for_kids: bool = False
    public_url: str = ""


def limits_for(platform: str) -> PlatformLimits:
    try:
        return LIMITS[platform]
    except KeyError as exc:
        raise KeyError(f"unknown platform: {platform}") from exc


def capabilities_for(platform: str) -> dict:
    limits = limits_for(platform)
    return {
        "platform": limits.platform,
        "label": limits.label,
        "direct_post": limits.direct_post,
        "inbox_upload": limits.inbox_upload,
        "analytics": limits.analytics,
        "retention": limits.retention,
        "native_schedule": limits.native_schedule,
        "requires_public_url": limits.requires_public_url,
        "requires_review": limits.requires_review,
        "max_duration_s": limits.max_duration_s,
        "max_bytes": limits.max_bytes,
        "caption_limit": limits.caption_limit,
        "title_limit": limits.title_limit,
        "max_hashtags": limits.max_hashtags,
        "note": limits.note,
    }


def probe_media(path: str | Path) -> MediaInfo:
    from ..pipeline.media import probe

    data = probe(path)
    return MediaInfo(
        duration=float(data.get("duration", 0.0)),
        width=int(data.get("width", 0)),
        height=int(data.get("height", 0)),
        size_bytes=int(data.get("size_bytes", 0)),
        has_audio=bool(data.get("has_audio", True)),
        format=str(data.get("format", "")),
    )


def _issue(field: str, code: str, severity: Severity, message: str, remedy: str = "") -> ValidationIssue:
    return ValidationIssue(field=field, code=code, severity=severity, message=message, remedy=remedy)


def validate(draft: PublishDraft) -> ValidationResult:
    limits = limits_for(draft.platform)
    media = draft.media
    issues: list[ValidationIssue] = []

    if media.duration <= 0:
        issues.append(_issue("media", "no_duration", "block", "The file has no readable duration."))
    elif media.duration < limits.min_duration_s:
        issues.append(_issue(
            "media", "too_short", "block",
            f"{media.duration:.1f}s is shorter than {limits.label}'s {limits.min_duration_s:.0f}s minimum.",
        ))
    elif media.duration > limits.max_duration_s:
        issues.append(_issue(
            "media", "too_long", "block",
            f"{media.duration:.1f}s is longer than {limits.label}'s {limits.max_duration_s:.0f}s maximum.",
            f"Trim to {limits.max_duration_s:.0f}s or less.",
        ))

    if media.size_bytes > limits.max_bytes:
        issues.append(_issue(
            "media", "too_large", "block",
            f"The file is {media.size_bytes / 1024**3:.2f} GB; the limit is {limits.max_bytes / 1024**3:.2f} GB.",
        ))

    if limits.has_audio_required and not media.has_audio:
        issues.append(_issue("media", "no_audio", "block", "This platform requires an audio track."))
    elif not media.has_audio:
        issues.append(_issue("media", "no_audio", "warn", "The file has no audio track."))

    if not media.width or not media.height:
        issues.append(_issue("media", "no_dimensions", "warn", "Could not read video dimensions."))
    elif limits.aspect != "any":
        ratio = media.width / media.height
        target = 9 / 16
        if abs(ratio - target) > limits.aspect_tolerance:
            if ratio > 1:
                issues.append(_issue(
                    "media", "aspect", "warn",
                    "Landscape video will publish as a regular video, not a vertical Short.",
                    "Re-render in the 9:16 vertical preset.",
                ))
            else:
                issues.append(_issue(
                    "media", "aspect", "warn",
                    f"Aspect ratio {media.width}:{media.height} is not 9:16.",
                    "Re-render in the 9:16 vertical preset.",
                ))

    if limits.title_limit and len(draft.title) > limits.title_limit:
        issues.append(_issue(
            "title", "title_limit", "block",
            f"Title is {len(draft.title)} characters; the limit is {limits.title_limit}.",
        ))
    if len(draft.caption) > limits.caption_limit:
        issues.append(_issue(
            "caption", "caption_limit", "block",
            f"Caption is {len(draft.caption)} characters; the limit is {limits.caption_limit}.",
        ))
    if len(draft.hashtags) > limits.max_hashtags:
        issues.append(_issue(
            "hashtags", "hashtag_limit", "block",
            f"{len(draft.hashtags)} hashtags; the limit is {limits.max_hashtags}.",
        ))

    if draft.visibility not in limits.allowed_visibility:
        issues.append(_issue(
            "visibility", "visibility", "block",
            f"{draft.visibility!r} is not an allowed visibility for {limits.label}.",
            "Choose one of: " + ", ".join(limits.allowed_visibility) + ".",
        ))

    if draft.scheduled_at and not limits.native_schedule:
        issues.append(_issue(
            "schedule", "app_queue", "warn",
            f"{limits.label} has no native scheduling; this will stay queued and upload only while the app is running.",
        ))

    if limits.requires_public_url and not draft.public_url:
        issues.append(_issue(
            "media", "public_url", "warn",
            "The standard publishing path needs a publicly reachable video URL.",
            "Use the resumable upload path if the connected app supports it, or export for manual posting.",
        ))

    if limits.requires_review:
        issues.append(_issue(
            "account", "review", "warn",
            f"{limits.label} requires an approved developer app for public posting; capability is checked at connect time.",
        ))

    return ValidationResult(
        ok=not any(issue.severity == "block" for issue in issues),
        issues=issues,
        limits=limits,
    )

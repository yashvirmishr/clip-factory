"""Shared publishing adapter contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .limits import MediaInfo

Progress = Callable[[str, float, str], None]


class PublishError(RuntimeError):
    """A platform error with enough structure for the queue to retry or stop."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        status: int = 0,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


@dataclass
class UploadRequest:
    account_id: str
    media_path: str
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    visibility: str = "private"
    made_for_kids: bool = False
    publish_at: str = ""
    category_id: str = "22"
    cover_path: str = ""
    public_url: str = ""
    media: MediaInfo | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(self.media_path)


@dataclass
class PublishResult:
    platform_post_id: str
    url: str = ""
    status: str = "published"
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "platform_post_id": self.platform_post_id,
            "url": self.url,
            "status": self.status,
            "raw": self.raw,
        }


@dataclass
class RemotePost:
    platform_post_id: str
    url: str = ""
    published_at: float = 0.0
    title: str = ""
    caption: str = ""
    duration_s: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "platform_post_id": self.platform_post_id,
            "url": self.url,
            "published_at": self.published_at,
            "title": self.title,
            "caption": self.caption,
            "duration_s": self.duration_s,
            "metrics": self.metrics,
            "raw": self.raw,
        }

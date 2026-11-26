"""X (Twitter) v2 adapter: chunked video upload, tweet creation, metrics."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from .base import Progress, PublishError, PublishResult, RemotePost, UploadRequest

API = "https://api.x.com/2"
UPLOAD = f"{API}/media/upload"
CHUNK_SIZE = 4 * 1024 * 1024
POLL_LIMIT = 20
POLL_INTERVAL = 2.0


def _retryable(status: int) -> bool:
    return status in (408, 429, 500, 502, 503, 504)


def _error(response: httpx.Response) -> PublishError:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {}
    message = ""
    code = ""
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("title") or ""
        if isinstance(detail, list):
            detail = "; ".join(str(item.get("message", item)) for item in detail)
        message = str(detail or "")
        code = str(body.get("type", "") or body.get("code", "") or "")
    if response.status_code == 401:
        message = "X needs you to reconnect the account."
        code = code or "unauthorized"
    elif response.status_code == 403:
        message = message or "X rejected this app permission or account action."
        code = code or "forbidden"
    elif response.status_code == 429:
        message = message or "X rate limit reached. The queue will retry later."
        code = "rate_limit"
    return PublishError(
        message or f"X request failed ({response.status_code}).",
        code=code or f"http_{response.status_code}",
        status=response.status_code,
        retryable=_retryable(response.status_code),
    )


def _id(payload: dict) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(
        data.get("id")
        or data.get("media_id_string")
        or payload.get("media_id_string")
        or payload.get("id")
        or "",
    )


def _text_for(request: UploadRequest) -> str:
    parts = [request.description or request.title or ""]
    if request.tags:
        tags = " ".join(tag if str(tag).startswith("#") else f"#{tag}" for tag in request.tags)
        parts.append(tags)
    text = "\n\n".join(part for part in parts if part).strip()
    return text[:280]


class XAdapter:
    platform = "x"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _session(self, client: httpx.Client | None = None):
        return client or self._client or httpx.Client(timeout=120.0)

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _poll(self, session, headers: dict, media_id: str, progress: Progress) -> None:
        for index in range(POLL_LIMIT):
            response = session.get(
                UPLOAD,
                params={"command": "STATUS", "media_id": media_id},
                headers=headers,
                timeout=30.0,
            )
            if response.status_code >= 400:
                raise _error(response)
            body = response.json()
            info = body.get("processing_info") or (body.get("data") or {}).get("processing_info") or {}
            state = str(info.get("state", "") or "")
            if state in ("succeeded", "success", ""):
                return
            if state == "failed":
                error = info.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else ""
                raise PublishError(
                    f"X could not process the video: {message or 'unknown error'}",
                    code="media_processing",
                )
            progress("process", min(0.9, 0.6 + index * 0.02), f"X is processing: {state}")
            time.sleep(POLL_INTERVAL)
        raise PublishError("X did not finish processing the video in time.", code="media_timeout", retryable=True)

    def upload(
        self,
        request: UploadRequest,
        access_token: str,
        progress: Progress | None = None,
        client: httpx.Client | None = None,
    ) -> PublishResult:
        progress = progress or (lambda stage, pct, detail="": None)
        path = request.path
        if not path.exists() or not path.is_file():
            raise PublishError(f"Rendered file not found: {path}", code="missing_file")
        size = path.stat().st_size
        if size <= 0:
            raise PublishError("The rendered file is empty.", code="empty_file")
        session = self._session(client)
        owned = client is None and self._client is None
        headers = self._headers(access_token)
        try:
            progress("prepare", 0.02, "creating an X media session")
            init = session.post(
                UPLOAD,
                data={
                    "command": "INIT",
                    "total_bytes": str(size),
                    "media_type": "video/mp4",
                    "media_category": "tweet_video",
                },
                headers=headers,
            )
            if init.status_code >= 400:
                raise _error(init)
            media_id = _id(init.json())
            if not media_id:
                raise PublishError("X did not return a media id.", code="no_media_id")

            offset = 0
            segment = 0
            with path.open("rb") as handle:
                while offset < size:
                    chunk = handle.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    response = session.post(
                        UPLOAD,
                        data={
                            "command": "APPEND",
                            "media_id": media_id,
                            "segment_index": str(segment),
                        },
                        files={"media": (path.name, chunk, "video/mp4")},
                        headers=headers,
                    )
                    if response.status_code >= 400:
                        raise _error(response)
                    offset += len(chunk)
                    segment += 1
                    progress("upload", min(0.85, 0.1 + 0.75 * offset / size), f"{offset / size * 100:.0f}% uploaded")

            progress("finalize", 0.88, "finalizing the X upload")
            final = session.post(
                UPLOAD,
                data={"command": "FINALIZE", "media_id": media_id},
                headers=headers,
            )
            if final.status_code >= 400:
                raise _error(final)
            self._poll(session, headers, media_id, progress)

            text = _text_for(request)
            if not text:
                text = request.title or path.stem
            progress("publish", 0.94, "posting the tweet")
            response = session.post(
                f"{API}/tweets",
                json={"text": text[:280], "media": {"media_ids": [media_id]}},
                headers={**headers, "Content-Type": "application/json"},
            )
            if response.status_code >= 400:
                raise _error(response)
            tweet_id = _id(response.json())
            if not tweet_id:
                raise PublishError("X accepted the tweet but returned no id.", code="no_tweet_id")
            progress("done", 1.0, "published")
            return PublishResult(
                platform_post_id=tweet_id,
                url=f"https://x.com/i/status/{tweet_id}",
                raw={"media_id": media_id},
            )
        finally:
            if owned:
                session.close()

    def fetch_metrics(
        self, access_token: str, post_id: str, client: httpx.Client | None = None
    ) -> dict:
        session = self._session(client)
        owned = client is None and self._client is None
        try:
            response = session.get(
                f"{API}/tweets/{post_id}",
                params={"tweet.fields": "public_metrics,created_at,text"},
                headers=self._headers(access_token),
            )
            if response.status_code >= 400:
                raise _error(response)
            item = response.json().get("data") or {}
            stats = item.get("public_metrics") or {}
            return {
                "platform_post_id": post_id,
                "url": f"https://x.com/i/status/{post_id}",
                "title": str(item.get("text", "") or ""),
                "caption": str(item.get("text", "") or ""),
                "published_at": _timestamp(item.get("created_at", "")),
                "views": int(stats.get("impression_count", 0) or 0),
                "likes": int(stats.get("like_count", 0) or 0),
                "comments": int(stats.get("reply_count", 0) or 0),
                "shares": int(stats.get("retweet_count", 0) or 0) + int(stats.get("quote_count", 0) or 0),
                "saves": int(stats.get("bookmark_count", 0) or 0),
                "raw": item,
            }
        finally:
            if owned:
                session.close()

    def fetch_posts(
        self, access_token: str, limit: int = 50, client: httpx.Client | None = None
    ) -> list[RemotePost]:
        session = self._session(client)
        owned = client is None and self._client is None
        headers = self._headers(access_token)
        try:
            me = session.get(f"{API}/users/me", headers=headers)
            if me.status_code >= 400:
                raise _error(me)
            user_id = str((me.json().get("data") or {}).get("id", "") or "")
            if not user_id:
                return []
            response = session.get(
                f"{API}/users/{user_id}/tweets",
                params={
                    "max_results": max(5, min(100, int(limit))),
                    "tweet.fields": "public_metrics,created_at,text",
                    "exclude": "retweets,replies",
                },
                headers=headers,
            )
            if response.status_code >= 400:
                raise _error(response)
            out: list[RemotePost] = []
            for item in response.json().get("data", []) or []:
                stats = item.get("public_metrics") or {}
                tweet_id = str(item.get("id", "") or "")
                if not tweet_id:
                    continue
                text = str(item.get("text", "") or "")
                out.append(RemotePost(
                    platform_post_id=tweet_id,
                    url=f"https://x.com/i/status/{tweet_id}",
                    published_at=_timestamp(item.get("created_at", "")),
                    title=text,
                    caption=text,
                    metrics={
                        "views": int(stats.get("impression_count", 0) or 0),
                        "likes": int(stats.get("like_count", 0) or 0),
                        "comments": int(stats.get("reply_count", 0) or 0),
                        "shares": int(stats.get("retweet_count", 0) or 0) + int(stats.get("quote_count", 0) or 0),
                        "saves": int(stats.get("bookmark_count", 0) or 0),
                    },
                    raw=item,
                ))
            return out
        finally:
            if owned:
                session.close()

    def fetch_profile(self, access_token: str, client: httpx.Client | None = None) -> dict:
        session = self._session(client)
        owned = client is None and self._client is None
        try:
            response = session.get(
                f"{API}/users/me",
                params={"user.fields": "public_metrics,profile_image_url"},
                headers=self._headers(access_token),
            )
            if response.status_code >= 400:
                raise _error(response)
            data = response.json().get("data") or {}
            stats = data.get("public_metrics") or {}
            return {
                "followers": int(stats.get("followers_count", 0) or 0),
                "following": int(stats.get("following_count", 0) or 0),
                "posts": int(stats.get("tweet_count", 0) or 0),
                "avatar_url": data.get("profile_image_url", ""),
            }
        finally:
            if owned:
                session.close()


def _timestamp(value: str) -> float:
    if not value:
        return 0.0
    from datetime import datetime, timezone

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0

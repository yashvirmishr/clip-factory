"""YouTube Data API upload and metrics adapter.

Uses resumable uploads directly over HTTPS. No Google SDK: the flow is small
and mocking it is much easier than mocking a client library.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .base import Progress, PublishError, PublishResult, RemotePost, UploadRequest

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3"
CHUNK_SIZE = 8 * 1024 * 1024


def _retryable(status: int) -> bool:
    return status in (408, 429, 500, 502, 503, 504)


def _error(response: httpx.Response) -> PublishError:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {}
    error = (body.get("error") or {}) if isinstance(body, dict) else {}
    if isinstance(error, list):
        error = error[0] if error else {}
    message = ""
    code = ""
    if isinstance(error, dict):
        message = str(error.get("message", "") or "")
        code = str(error.get("status", "") or error.get("code", "") or "")
    message = message or f"YouTube request failed ({response.status_code})."
    if response.status_code == 401:
        code = code or "unauthorized"
        message = "YouTube needs you to reconnect the account."
    elif response.status_code == 403 and "quota" in message.lower():
        code = "quota"
        message = "YouTube upload quota is exhausted for today."
    return PublishError(
        message,
        code=code or f"http_{response.status_code}",
        status=response.status_code,
        retryable=_retryable(response.status_code),
    )


def _iso_duration(value: str) -> float:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0.0
    days, hours, minutes, seconds = (float(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _timestamp(value: str) -> float:
    if not value:
        return 0.0
    from datetime import datetime, timezone

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class YouTubeAdapter:
    platform = "youtube"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _session(self, client: httpx.Client | None = None):
        return client or self._client or httpx.Client(timeout=120.0)

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
        media = request.media
        if media is None:
            from .limits import probe_media

            media = probe_media(path)

        visibility = request.visibility
        publish_at = request.publish_at
        if publish_at and visibility != "private":
            # YouTube only accepts publishAt on a private video.
            visibility = "private"
        status: dict[str, Any] = {
            "privacyStatus": visibility,
            "selfDeclaredMadeForKids": bool(request.made_for_kids),
        }
        if publish_at:
            status["publishAt"] = publish_at
        body = {
            "snippet": {
                "title": request.title[:100] or path.stem[:100],
                "description": request.description[:5000],
                "tags": request.tags[:15],
                "categoryId": request.category_id or "22",
            },
            "status": status,
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        }
        session = self._session(client)
        owned = client is None and self._client is None
        try:
            progress("prepare", 0.02, "requesting an upload session")
            init = session.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers=headers,
                content=json.dumps(body).encode("utf-8"),
            )
            if init.status_code >= 400:
                raise _error(init)
            location = init.headers.get("location") or init.headers.get("Location")
            if not location:
                raise PublishError("YouTube did not return an upload session URL.", code="no_session")

            offset = 0
            video_id = ""
            with path.open("rb") as handle:
                while offset < size:
                    chunk = handle.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    end = offset + len(chunk) - 1
                    chunk_headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                        "Content-Type": "video/mp4",
                    }
                    response = session.put(location, headers=chunk_headers, content=chunk)
                    if response.status_code in (200, 201):
                        payload = response.json()
                        video_id = str(payload.get("id", "") or "")
                        offset = size
                        break
                    if response.status_code == 308:
                        range_header = response.headers.get("range") or response.headers.get("Range") or ""
                        match = re.search(r"bytes=0-(\d+)", range_header)
                        offset = int(match.group(1)) + 1 if match else offset + len(chunk)
                        progress("upload", min(0.98, offset / size), f"{offset / size * 100:.0f}% uploaded")
                        continue
                    raise _error(response)
            if not video_id:
                raise PublishError("YouTube accepted the upload but returned no video id.", code="no_video_id")
            progress("done", 1.0, "published")
            return PublishResult(
                platform_post_id=video_id,
                url=f"https://youtu.be/{video_id}",
                raw={"id": video_id, "privacy": visibility},
            )
        finally:
            if owned:
                session.close()

    def fetch_metrics(
        self,
        access_token: str,
        post_id: str,
        client: httpx.Client | None = None,
    ) -> dict:
        session = self._session(client)
        owned = client is None and self._client is None
        try:
            response = session.get(
                f"{API_URL}/videos",
                params={"part": "statistics,snippet,contentDetails", "id": post_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code >= 400:
                raise _error(response)
            body = response.json()
            items = body.get("items") or []
            if not items:
                raise PublishError("YouTube returned no video for that id.", code="not_found", status=404)
            item = items[0]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})
            return {
                "platform_post_id": post_id,
                "url": f"https://youtu.be/{post_id}",
                "title": str(snippet.get("title", "") or ""),
                "caption": str(snippet.get("description", "") or ""),
                "published_at": _timestamp(str(snippet.get("publishedAt", "") or "")),
                "duration_s": _iso_duration(str(details.get("duration", "") or "")),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "raw": item,
            }
        finally:
            if owned:
                session.close()

    def fetch_posts(
        self,
        access_token: str,
        limit: int = 50,
        client: httpx.Client | None = None,
    ) -> list[RemotePost]:
        """List recent uploads through the channel uploads playlist."""
        session = self._session(client)
        owned = client is None and self._client is None
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            channel = session.get(
                f"{API_URL}/channels",
                params={"part": "contentDetails", "mine": "true"},
                headers=headers,
            )
            if channel.status_code >= 400:
                raise _error(channel)
            items = channel.json().get("items") or []
            if not items:
                return []
            uploads = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads", "")
            if not uploads:
                return []
            ids: list[str] = []
            token = ""
            while len(ids) < limit:
                params = {"part": "contentDetails", "playlistId": uploads, "maxResults": min(50, limit - len(ids))}
                if token:
                    params["pageToken"] = token
                page = session.get(f"{API_URL}/playlistItems", params=params, headers=headers)
                if page.status_code >= 400:
                    raise _error(page)
                body = page.json()
                for item in body.get("items", []):
                    vid = ((item.get("contentDetails") or {}).get("videoId") or "")
                    if vid:
                        ids.append(str(vid))
                token = str(body.get("nextPageToken", "") or "")
                if not token:
                    break
            out: list[RemotePost] = []
            for start in range(0, len(ids), 50):
                chunk = ids[start:start + 50]
                response = session.get(
                    f"{API_URL}/videos",
                    params={"part": "statistics,snippet,contentDetails", "id": ",".join(chunk)},
                    headers=headers,
                )
                if response.status_code >= 400:
                    raise _error(response)
                for item in response.json().get("items", []):
                    vid = str(item.get("id", "") or "")
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    out.append(RemotePost(
                        platform_post_id=vid,
                        url=f"https://youtu.be/{vid}",
                        published_at=_timestamp(str(snippet.get("publishedAt", "") or "")),
                        title=str(snippet.get("title", "") or ""),
                        caption=str(snippet.get("description", "") or ""),
                        duration_s=_iso_duration(str((item.get("contentDetails") or {}).get("duration", "") or "")),
                        metrics={
                            "views": int(stats.get("viewCount", 0) or 0),
                            "likes": int(stats.get("likeCount", 0) or 0),
                            "comments": int(stats.get("commentCount", 0) or 0),
                        },
                        raw=item,
                    ))
            return out
        finally:
            if owned:
                session.close()

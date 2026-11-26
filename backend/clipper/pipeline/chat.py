"""Twitch VOD chat, used as a scoring signal.

Chat is the only signal here that knows what the audience actually reacted to. A
spike in message rate lines up with the joke, not with the sentence before it, so
it is worth the fetch.

The fetch is Twitch's public GraphQL endpoint - the same one the web player uses.
There is no official API for VOD chat replay and no auth is required. It can
change without notice, so every response is parsed defensively and the failure
message quotes what came back instead of a KeyError.

Paging goes by `contentOffsetSeconds`, not by cursor. Twitch's cursor mode is
behind a browser-integrity challenge: the first page answers, the next one comes
back as `failed integrity check`. Offset mode answers every page and returns a
window that starts before the requested offset, so pages overlap - each page
only contributes messages past the last one already kept.

The stored artifact is the same shape the existing parser already reads: a list
of ``{"content_offset_seconds": 12.3, ...}`` - which is also what TwitchDownloader
emits, so a hand-made dump keeps working.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path

import numpy as np

GQL_ENDPOINT = "https://gql.twitch.tv/gql"
PUBLIC_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
MAX_COMMENTS = 250_000

_COMMENTS_QUERY = """
query ClipFactoryComments($id: ID!, $offset: Int!) {
  video(id: $id) {
    lengthSeconds
    comments(first: 100, contentOffsetSeconds: $offset) {
      edges { node { contentOffsetSeconds } }
      pageInfo { hasNextPage }
    }
  }
}
"""


class ChatError(RuntimeError):
    pass


def vod_id(value: str) -> str:
    """Numeric id from a Twitch VOD URL or a bare id. Empty when it is neither."""
    text = (value or "").strip()
    match = re.search(r"twitch\.tv/videos/(\d+)", text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    return ""


def is_twitch_vod(value: str) -> bool:
    return bool(vod_id(value))


def _post(client, variables: dict) -> dict:
    payload = {"query": _COMMENTS_QUERY, "variables": variables}
    response = client.post(
        GQL_ENDPOINT,
        json=payload,
        headers={"Client-ID": PUBLIC_CLIENT_ID, "Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise ChatError(f"twitch returned HTTP {response.status_code}: {response.text[:160]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ChatError(f"twitch returned non-JSON: {response.text[:160]}") from exc
    if not isinstance(body, dict):
        raise ChatError(f"twitch returned an unexpected payload: {json.dumps(body)[:200]}")
    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = first.get("message", "unknown GraphQL error")
        raise ChatError(f"twitch GraphQL error: {message}")
    return body


def _video(body: dict) -> dict:
    video = (body.get("data") or {}).get("video")
    if not isinstance(video, dict):
        raise ChatError(
            "twitch returned no video for that id (deleted, expired, or the schema "
            f"changed): {json.dumps(body)[:200]}"
        )
    return video


def fetch_offsets(
    video_id: str,
    progress=None,
    client=None,
    max_comments: int = MAX_COMMENTS,
) -> tuple[list[float], float]:
    """Every chat message offset in seconds, plus the VOD length.

    Offsets are what the signal needs: message *timestamps* land on the beat that
    caused them. Message text is deliberately not stored - it is not used for
    scoring and it is the part with privacy weight.
    """
    if not video_id:
        raise ChatError("not a Twitch VOD id")
    import httpx

    offsets: list[float] = []
    length = 0.0
    offset = 0
    last = -1.0
    close = client is None
    http = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        while True:
            try:
                body = _post(http, {"id": video_id, "offset": offset})
            except httpx.HTTPError as exc:
                raise ChatError(f"could not reach twitch: {exc}") from exc
            video = _video(body)
            if not length:
                try:
                    length = float(video.get("lengthSeconds") or 0.0)
                except (TypeError, ValueError):
                    length = 0.0
                if not math.isfinite(length) or length < 0:
                    length = 0.0

            comments = video.get("comments")
            if not isinstance(comments, dict):
                comments = {}
            edges = comments.get("edges")
            if not isinstance(edges, list):
                edges = []
            page: list[float] = []
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                if not isinstance(node, dict):
                    continue
                value = node.get("contentOffsetSeconds")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                value = float(value)
                if math.isfinite(value) and value >= 0:
                    page.append(value)

            # A page starts before the requested offset, so most of it is a
            # replay of what the previous page already gave us. Keep the tail -
            # all of it, because several messages sharing one second are a
            # burst, and the rate signal is exactly that.
            tail = [value for value in page if value > last]
            offsets.extend(tail)
            fresh = len(tail)
            if page:
                last = max(last, max(page))
            if progress:
                fraction = min(0.99, (last / length) if (length and last >= 0) else 0.0)
                progress(fraction, f"{len(offsets):,} messages")

            if not fresh or len(offsets) >= max_comments:
                break
            offset = int(last) + 1
            if length and offset >= length:
                break
    finally:
        if close:
            http.close()

    offsets.sort()
    return offsets, length


def write_dump(path: Path, offsets: list[float], source: str = "") -> Path:
    """Write the artifact atomically so an interrupted fetch cannot be read as empty."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"content_offset_seconds": round(offset, 3), "source": source}
        for offset in offsets
    ]
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def _seconds(value) -> float | None:
    """A finite, non-negative offset, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def read_dump(path: Path) -> list[float]:
    try:
        payload = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("comments", [])
    if not isinstance(payload, list):
        return []
    out: list[float] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        seconds = _seconds(item.get("content_offset_seconds"))
        if seconds is not None:
            out.append(seconds)
    out.sort()
    return out


def offsets_cache_path(path: Path) -> Path:
    return Path(path).with_suffix(".offsets.npz")


def read_offsets(path: Path | str) -> list[float]:
    """Sorted offsets, cached in a small array beside the dump.

    A two-hour chat dump is tens of megabytes of JSON; parsing and sorting it on
    every source click is the most avoidable cost in the UI. The cache is keyed
    on the dump's mtime, so a hand-dropped file still wins.
    """

    p = Path(path)
    cache = offsets_cache_path(p)
    try:
        if cache.exists() and cache.stat().st_mtime >= p.stat().st_mtime:
            with np.load(cache) as data:
                return [float(value) for value in data["offsets"]]
    except (OSError, ValueError, KeyError):
        pass
    values = read_dump(p)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, offsets=np.asarray(values, dtype=np.float32))
    except (OSError, ValueError):
        pass
    return values


def coverage(offsets: list[float], duration: float) -> dict:
    """How much of the VOD the chat actually covers, for the UI to be honest."""
    values = [_seconds(offset) for offset in offsets]
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"messages": 0, "first": 0.0, "last": 0.0, "coverage": 0.0}
    first, last = values[0], values[-1]
    try:
        total = float(duration)
    except (TypeError, ValueError):
        total = 0.0
    if not math.isfinite(total) or total <= 0:
        total = 0.0
    span = max(0.0, last - first)
    return {
        "messages": len(values),
        "first": round(first, 1),
        "last": round(last, 1),
        "coverage": round(min(1.0, span / total), 3) if total else 0.0,
    }


def fetch(
    vod_url: str,
    target: Path,
    progress=None,
    client=None,
    max_comments: int = MAX_COMMENTS,
) -> dict:
    video_id = vod_id(vod_url)
    if not video_id:
        raise ChatError("that is not a Twitch VOD URL (expected twitch.tv/videos/<id>)")
    offsets, length = fetch_offsets(video_id, progress=progress, client=client, max_comments=max_comments)
    if not offsets:
        raise ChatError("this VOD has no chat replay (chat may have been disabled)")
    write_dump(target, offsets, source=vod_url)
    info = coverage(offsets, length)
    info.update({"vod_id": video_id, "path": str(target), "length": round(length, 1)})
    return info

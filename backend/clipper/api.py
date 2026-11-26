"""HTTP API. The Electron shell and the browser dev server both talk to this.

Everything is localhost-only and single-user; there is no auth layer by design,
and the sidecar binds 127.0.0.1 in production (see __main__).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, accounts, analytics, coach, db, demo, hardware, personal, policy, secrets, service, weekly
from .config import SETTINGS
from .jobs import JOBS
from .publish import limits as publish_limits
from .publish import oauth as publish_oauth
from .publish import queue as publish_queue
from .learn import LEARNER
from .logging_setup import configure_logging
from .pipeline.caption import (
    CaptionPage,
    CaptionWord,
    caption_stats,
    edit_pages,
    group_words,
    pages_for,
)
from .pipeline.media import FFMPEG, MediaError

app = FastAPI(title="Clip Factory", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_probe_cache: dict = {}
_STARTED_AT = time.time()
LOG_PATH = configure_logging(SETTINGS.data_dir)
logger = logging.getLogger(__name__)


class IngestRequest(BaseModel):
    path: str
    name: str | None = None
    language: str = "auto"
    # {"lang": "hi", "auto": true} from the URL sheet, when a caption track was
    # chosen instead of speech recognition.
    subtitle_track: dict | None = None
    prefer_captions: bool = False


class PreviewRequest(BaseModel):
    url: str


class SubtitleRequest(BaseModel):
    lang: str
    auto: bool = False


class ChatRequest(BaseModel):
    url: str | None = None


class AnalyzeRequest(BaseModel):
    subtitle_path: str | None = None
    chat_path: str | None = None
    limit: int = 10
    force: bool = False
    language: str = "auto"
    translate: bool = False


class DecisionRequest(BaseModel):
    action: str
    reason: str = ""


class HookRequest(BaseModel):
    hook: str


class RenderRequest(BaseModel):
    preset: str = "hormozi"
    framing: str = "blur"
    force: bool = False


class TrimRequest(BaseModel):
    start: float | None = None
    end: float | None = None


class CaptionEditRequest(BaseModel):
    pages: list[list[CaptionWord]]


class BakeRequest(BaseModel):
    preset: str = "hormozi"
    framing: str = "auto"
    approved_only: bool = False


class RevealRequest(BaseModel):
    path: str


class RunnerRequest(BaseModel):
    url: str = ""


class ConnectStartRequest(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list[str] | None = None


class PublishDraftRequest(BaseModel):
    platform: str
    media_path: str | None = None
    media: dict | None = None
    title: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    visibility: str = "private"
    scheduled_at: float = 0.0
    public_url: str = ""
    made_for_kids: bool = False


class PublishCreateRequest(PublishDraftRequest):
    account_id: str
    source_id: str = ""
    clip_id: str = ""
    idempotency_key: str = ""
    metadata: dict = Field(default_factory=dict)


@app.on_event("startup")
def _startup() -> None:
    logger.info(
        "Clip Factory %s starting (pid %s, data %s, log %s)",
        __version__,
        os.getpid(),
        SETTINGS.data_dir,
        LOG_PATH,
    )
    db.init()
    logger.info("database ready at %s", SETTINGS.db_path())

    # Probing hardware encoders can take ~25 s on a machine with a broken NVENC
    # install. Doing it here, off the request path, keeps that out of the first
    # render the user waits for.
    def warm_encoder_probe() -> None:
        try:
            from .render.ffmpeg import choose_encoder

            logger.info("hardware encoder ready: %s", choose_encoder())
        except Exception:  # noqa: BLE001 - a probe must never block startup
            logger.warning("hardware encoder probe failed", exc_info=True)

    threading.Thread(target=warm_encoder_probe, name="clip-encoder-probe", daemon=True).start()

    def pump_publishes() -> None:
        for job_id in publish_queue.recover():
            try:
                _submit_publish(job_id)
            except Exception:  # noqa: BLE001 - one stuck upload must not block startup
                logger.warning("could not resume publish job %s", job_id, exc_info=True)
        while True:
            time.sleep(20)
            try:
                pending = publish_queue.next_pending()
                if pending is not None:
                    _submit_publish(pending["id"])
            except Exception:  # noqa: BLE001 - the scheduler retries next tick
                logger.warning("publish scheduler tick failed", exc_info=True)

    if os.environ.get("CLIPPER_DISABLE_PUBLISH_SCHEDULER") != "1":
        threading.Thread(target=pump_publishes, name="clip-publish-scheduler", daemon=True).start()
    weekly.start()


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "version": __version__,
        "data_dir": str(SETTINGS.data_dir),
        "busy": JOBS.busy(),
        "llama_url": SETTINGS.llama_url,
        "whisper_cli": SETTINGS.whisper_cli or "not configured",
    }


@app.get("/api/diagnostics")
def diagnostics() -> dict:
    """A single snapshot for bug reports and the About/Setup panel."""

    data_dir = SETTINGS.data_dir
    db_path = SETTINGS.db_path()
    media_dir = SETTINGS.media_dir()

    def directory_bytes(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        for entry in path.iterdir():
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
        return total

    try:
        disk = shutil.disk_usage(data_dir)
        disk_payload = {
            "free_gb": round(disk.free / 1e9, 1),
            "total_gb": round(disk.total / 1e9, 1),
        }
    except OSError:
        disk_payload = {}

    try:
        db_bytes = db_path.stat().st_size
    except OSError:
        db_bytes = 0

    return {
        "version": __version__,
        "pid": os.getpid(),
        "uptime_s": round(time.time() - _STARTED_AT, 1),
        "python": sys.version.split()[0],
        "data_dir": str(data_dir),
        "data_writable": os.access(data_dir, os.W_OK),
        "log": str(LOG_PATH),
        "db": {"path": str(db_path), "bytes": db_bytes},
        "media": {"path": str(media_dir), "bytes": directory_bytes(media_dir)},
        "disk": disk_payload,
        "busy": JOBS.busy(),
        "jobs": JOBS.list(8),
        "ffmpeg": shutil.which("ffmpeg") or "not on PATH",
        "llama_url": SETTINGS.llama_url or "not configured",
        "whisper_cli": SETTINGS.whisper_cli or "not configured",
    }


@app.get("/api/languages")
def list_languages() -> list[dict]:
    """The language picker: whisper codes, native names and their script."""
    from .lang import catalog

    return catalog()


@app.get("/api/hardware")
def get_hardware(refresh: bool = False) -> dict:
    if refresh or not _probe_cache:
        _probe_cache.clear()
        profile = hardware.probe()
        _probe_cache["profile"] = profile
        _probe_cache["advice"] = hardware.advise(profile)
        _probe_cache["models"] = hardware.MODELS
    return {
        "profile": _probe_cache["profile"],
        "advice": _probe_cache["advice"],
        "models": _probe_cache["models"],
    }


@app.get("/api/sources")
def list_sources() -> list[dict]:
    return db.list_sources_with_stats()


@app.post("/api/sources")
def ingest_source(request: IngestRequest) -> dict:
    try:
        source = service.ingest(request.path, request.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
    return source.model_dump()


@app.post("/api/sources/preview")
def preview_source(request: PreviewRequest) -> dict:
    """Metadata and caption tracks for a URL, without downloading anything."""
    from .pipeline import fetch

    if not fetch.is_url(request.url):
        raise HTTPException(status_code=400, detail="that is not an http(s) URL")
    if not fetch.available():
        raise HTTPException(
            status_code=409,
            detail="URL import needs yt-dlp: ./.venv/Scripts/python.exe -m pip install yt-dlp",
        )
    try:
        return fetch.inspect(request.url).as_dict()
    except fetch.FetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sources/{source_id}/tracks")
def source_tracks(source_id: str) -> dict:
    """Caption tracks this source can offer, and what is already stored."""
    from .hardware import find_whisper_cli
    from .pipeline import fetch

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    preview = service.stored_preview(source)
    if preview is None and source.origin_url and fetch.available():
        try:
            preview = fetch.inspect(source.origin_url).as_dict()
            service.store_preview(source, preview)
        except fetch.FetchError:
            preview = {"url": source.origin_url, "tracks": [], "error": "metadata unavailable"}
    model = Path(SETTINGS.whisper_model_path or "").name
    return {
        "preview": preview,
        "stored": service.stored_subtitles(source),
        "asr": {
            "model": model,
            "english_only": model.endswith(".en.bin"),
            "language": "auto",
            "available": bool(
                SETTINGS.whisper_cli or find_whisper_cli([SETTINGS.data_dir / "bin"])
            ),
        },
    }


@app.post("/api/sources/{source_id}/subtitles")
def download_subtitles(source_id: str, request: SubtitleRequest) -> dict:
    """Fetch one caption track from the origin URL and keep it with the source."""
    from .pipeline import fetch

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if not source.origin_url:
        raise HTTPException(status_code=400, detail="this source was not imported from a URL")
    if not fetch.available():
        raise HTTPException(status_code=409, detail="caption download needs yt-dlp")

    def task(progress):
        return service.fetch_subtitles(source, request.lang, request.auto, progress=progress)

    return JOBS.submit("download", task).to_dict()


@app.post("/api/sources/url")
def ingest_url(request: IngestRequest) -> dict:
    """Download a VOD and register it. A job, because a 2 h VOD is not a request."""
    from .pipeline import fetch

    if not fetch.is_url(request.path):
        raise HTTPException(status_code=400, detail="that is not an http(s) URL")
    if not fetch.available():
        raise HTTPException(
            status_code=409,
            detail=(
                "URL import needs yt-dlp: "
                "./.venv/Scripts/python.exe -m pip install yt-dlp"
            ),
        )

    def task(progress):
        source = service.ingest(request.path, request.name, progress=progress)
        try:
            preview = fetch.inspect(request.path).as_dict()
            service.store_preview(source, preview)
        except fetch.FetchError:
            # Metadata is a nicety: the download already succeeded.
            pass
        if request.subtitle_track:
            track = request.subtitle_track
            try:
                service.fetch_subtitles(
                    source,
                    str(track.get("lang") or request.language),
                    bool(track.get("auto")),
                    progress=progress,
                )
            except (fetch.FetchError, ValueError) as exc:
                progress("subtitles", 1.0, f"captions failed: {exc}"[:120])
        return source.model_dump()

    return JOBS.submit("download", task).to_dict()


@app.post("/api/demo")
def create_demo() -> dict:
    try:
        path = demo.generate(SETTINGS.media_dir())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"demo generation failed: {exc}") from exc
    source = service.ingest(path, "Demo stream")
    return source.model_dump()


@app.get("/api/sources/{source_id}")
def get_source(source_id: str) -> dict:
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source.model_dump()


@app.get("/api/sources/{source_id}/chat")
def get_chat(source_id: str) -> dict:
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return service.chat_status(source)


@app.post("/api/sources/{source_id}/chat/fetch")
def fetch_chat(source_id: str, request: ChatRequest | None = None) -> dict:
    """Download a Twitch VOD's chat replay. A job - it is a paged network walk."""
    from .pipeline import chat as chatmod

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    url = (request.url if request else None) or source.origin_url
    if not chatmod.vod_id(url or ""):
        raise HTTPException(
            status_code=400,
            detail="chat replay needs a Twitch VOD URL (twitch.tv/videos/<id>)",
        )

    def task(progress):
        info = service.fetch_chat(source, url, progress=progress)
        progress("chat", 1.0, f"{info['messages']:,} messages")
        return info

    return JOBS.submit("chat", task).to_dict()


@app.post("/api/sources/{source_id}/analyze")
def analyze_source(source_id: str, request: AnalyzeRequest) -> dict:
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    # Start the browsing copy alongside the analysis; it makes every later seek
    # cheap and the io lane would otherwise sit idle.
    def proxy_task(progress):
        try:
            return {"path": str(service.build_proxy(source, progress))}
        except (RuntimeError, OSError):
            return {"path": "", "skipped": True}

    JOBS.submit("proxy", proxy_task)

    # A caption track already downloaded for this source is the most accurate
    # transcript available, so use it unless the caller asked for something else.
    subtitle_path = request.subtitle_path
    if not subtitle_path:
        stored = service.stored_subtitles(source)
        if stored:
            subtitle_path = stored[0]["path"]

    def task(progress):
        return service.analyze(
            source,
            subtitle_path=subtitle_path,
            chat_path=request.chat_path,
            limit=request.limit,
            progress=progress,
            force=request.force,
            language=request.language,
            translate=request.translate,
        ).model_dump()

    job = JOBS.submit("analyze", task)
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return JOBS.list()


def _job_payload(job) -> dict:
    """One job as the client sees it, with its result attached when finished.

    Shared by the poll route and the event stream so a client that switches from
    one to the other cannot see a different shape.
    """
    payload = job.to_dict()
    if job.status == "done" and job.result is not None and isinstance(job.result, dict):
        if "candidates" in job.result:
            # Do not inline a multi-megabyte analysis in every update of a
            # finished job; the client refetches the shape it renders.
            payload["analysis_ready"] = True
            payload["source_id"] = (job.result.get("source") or {}).get("id", "")
            payload["clip_count"] = sum(
                1 for c in job.result.get("candidates", []) if c.get("rank")
            )
            payload["reel_quality"] = job.result.get("reel_quality", 0.0)
        else:
            payload["analysis"] = job.result
    return payload


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_payload(job)


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str):
    """Server-sent events for one job: one frame per change, then the result.

    A poll loop asks "anything new?" every second for the whole render; this asks
    nothing and still updates immediately. The stream closes itself after the
    terminal frame, so a client that only reads the stream cannot hang.
    """
    import json as json_module
    import time as time_module

    from fastapi.responses import StreamingResponse

    if JOBS.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    def frames():
        last = ""
        idle_rounds = 0
        while True:
            job = JOBS.get(job_id)
            if job is None:
                yield "event: gone\ndata: {}\n\n"
                return
            body = json_module.dumps(_job_payload(job), default=str)
            if body != last:
                last = body
                idle_rounds = 0
                yield f"data: {body}\n\n"
            else:
                idle_rounds += 1
                if idle_rounds % 40 == 0:
                    # A comment line keeps idle proxies and browsers from
                    # treating a long render as a dead connection.
                    yield ": keep-alive\n\n"
            if job.status in {"done", "error", "cancelled"}:
                return
            time_module.sleep(0.35)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = JOBS.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


@app.get("/api/sources/{source_id}/analysis")
def get_analysis(source_id: str, shape: str = "reel") -> dict:
    """The analysis, sized for what is actually on screen.

    `shape=reel` (the default) returns the ranked clips without word timings or
    pre-baked caption pages - those are the megabytes, and the reel does not
    draw them. `shape=full` keeps the old payload for tools that walk every
    candidate.
    """

    analysis = db.get_analysis(source_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="not analyzed yet")
    if shape == "full":
        return analysis.model_dump()
    # Dumping all ~900 candidates and then discarding the unranked ones costs
    # more than the query: build the payload from the ten clips on screen.
    payload = analysis.model_dump(exclude={"candidates"})
    payload["candidates"] = [
        candidate.model_dump(exclude={"words", "caption_pages"})
        for candidate in analysis.candidates
        if candidate.rank
    ]
    return payload


# The peaks artifact is 8 MB of compressed min/max pairs and the timeline asks
# for the same reduction on every source select. Keep the reduced response, keyed
# on the artifact's mtime so a re-analysis invalidates it for free.
_PEAK_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_PEAK_CACHE_LIMIT = 8


@app.get("/api/sources/{source_id}/peaks")
def get_peaks(source_id: str, buckets: int = 1400) -> dict:
    path = service.artifacts_for(source_id) / "peaks.npz"
    try:
        stamp = path.stat().st_mtime
    except OSError as exc:
        raise HTTPException(status_code=404, detail="peaks not built yet") from exc
    buckets = max(50, min(4000, buckets))
    cache_key = (source_id, buckets)
    cached = _PEAK_CACHE.get(cache_key)
    if cached is not None and cached[0] == stamp:
        return cached[1]

    try:
        data = np.load(str(path))
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="peaks not built yet") from exc
    if "min64" not in data:
        raise HTTPException(status_code=500, detail="peaks artifact malformed")
    lows, highs = data["min64"], data["max64"]
    total_samples = int(data["count"][0]) if "count" in data else int(lows.size * 64)
    n = int(lows.size)
    if n == 0:
        payload: dict = {"duration": 0.0, "low": [], "high": [], "buckets": 0}
    else:
        edges = (np.arange(buckets + 1) * n // buckets).astype(np.int64)
        edges = np.clip(edges, 0, n)
        starts = edges[:-1]
        valid = starts < n
        low = np.minimum.reduceat(lows, starts[valid])
        high = np.maximum.reduceat(highs, starts[valid])
        payload = {
            "duration": round(total_samples / SETTINGS.audio.sample_rate, 3),
            "low": [round(float(v), 4) for v in low],
            "high": [round(float(v), 4) for v in high],
            "buckets": int(valid.sum()),
        }
    if len(_PEAK_CACHE) >= _PEAK_CACHE_LIMIT:
        _PEAK_CACHE.clear()
    _PEAK_CACHE[cache_key] = (stamp, payload)
    return payload


@app.get("/api/media/{source_id}")
def get_media(source_id: str, proxy: bool = False):
    source = db.get_source(source_id)
    if source is None or not Path(source.path).exists():
        raise HTTPException(status_code=404, detail="media not found")
    path = Path(source.path)
    if proxy:
        preview = service.proxy_path_for(source)
        if preview.exists():
            path = preview
    return FileResponse(
        path,
        filename=path.name,
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.post("/api/sources/{source_id}/proxy")
def build_proxy(source_id: str) -> dict:
    """Build the 720p browsing copy. Queued on the io lane beside downloads."""

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    def task(progress):
        path = service.build_proxy(source, progress)
        return {"path": str(path), "url": f"/api/media/{source_id}?proxy=1"}

    return JOBS.submit("proxy", task).to_dict()


@app.get("/api/sources/{source_id}/thumb")
def get_thumb(source_id: str, t: float = 0.0, w: int = 320):
    """One still from the source, for the clip and source lists.

    Ten clips with a <video> element each means ten decoders competing with the
    monitor for the same file. A JPEG is one seek and one frame, and the browser
    gets to cache it.
    """

    source = db.get_source(source_id)
    if source is None or not Path(source.path).exists():
        raise HTTPException(status_code=404, detail="media not found")
    width = max(64, min(640, int(w)))
    limit = max(0.0, (source.duration or 0.0) - 0.1)
    seconds = max(0.0, min(float(t), limit)) if source.duration else max(0.0, float(t))
    folder = SETTINGS.artifacts_dir() / source_id / "thumbs"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{int(round(seconds * 10))}-{width}.jpg"
    if not out.exists() or out.stat().st_size == 0:
        result = subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{seconds:.3f}", "-i", source.path,
                "-frames:v", "1", "-vf", f"scale={width}:-2",
                "-q:v", "4", str(out),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            raise HTTPException(status_code=503, detail="ffmpeg could not build a thumbnail")
    stat = out.stat()
    return FileResponse(
        out,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=86400",
            "ETag": f'"{int(stat.st_mtime)}-{stat.st_size}"',
        },
    )


@app.get("/api/sources/{source_id}/clips/{clip_id}")
def get_clip(source_id: str, clip_id: str) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return candidate.model_dump()


def _captions_font(candidate, pages: list[CaptionPage]) -> str:
    """The family the renderer will actually use for these pages.

    The studio previews with this so a Han clip does not preview in Arial Black
    and burn in YaHei.
    """
    from .render.ass import font_for_text, resolve_style

    style = resolve_style(candidate.caption_style, SETTINGS.captions.default_preset)
    return font_for_text(style.font, "".join(page.text for page in pages))


def _caption_payload(
    clip_id: str, pages: list[CaptionPage], edited: bool, font: str = ""
) -> dict:
    return {
        "clip_id": clip_id,
        "pages": [page.model_dump() for page in pages],
        "stats": caption_stats(pages),
        "edited": edited,
        "font": font,
    }


@app.get("/api/sources/{source_id}/clips/{clip_id}/captions")
def get_captions(source_id: str, clip_id: str) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    pages = pages_for(candidate, SETTINGS.captions)
    return _caption_payload(
        clip_id, pages, bool(candidate.caption_pages), _captions_font(candidate, pages)
    )


@app.put("/api/sources/{source_id}/clips/{clip_id}/captions")
def put_captions(source_id: str, clip_id: str, request: CaptionEditRequest) -> dict:
    """Save a manual caption pass. Words are the edit; pages are derived."""
    analysis = db.get_analysis(source_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="no analysis for this source")
    candidate = next((c for c in analysis.candidates if c.id == clip_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    try:
        pages = edit_pages(
            request.pages, candidate.start, candidate.end, SETTINGS.captions
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # One row instead of a whole-payload rewrite; the pages are folded back on
    # load and cached there.
    db.save_clip_edit(source_id, clip_id, "captions", {"pages": [p.model_dump() for p in pages]})
    return _caption_payload(clip_id, pages, True, _captions_font(candidate, pages))


@app.delete("/api/sources/{source_id}/clips/{clip_id}/captions")
def reset_captions(source_id: str, clip_id: str) -> dict:
    analysis = db.get_analysis(source_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="no analysis for this source")
    candidate = next((c for c in analysis.candidates if c.id == clip_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    db.clear_clip_edits(source_id, clip_id, "captions")
    pages = group_words(candidate.words, SETTINGS.captions)
    return _caption_payload(clip_id, pages, False, _captions_font(candidate, pages))


@app.post("/api/sources/{source_id}/clips/{clip_id}/decision")
def decide(source_id: str, clip_id: str, request: DecisionRequest) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    if request.action not in ("approve", "reject", "undo"):
        raise HTTPException(status_code=400, detail="action must be approve, reject or undo")
    if request.action == "undo":
        return {"ok": True, "action": "undo"}
    outcome = LEARNER.record_decision(candidate, request.action, request.reason)
    return {
        "ok": True,
        "action": request.action,
        "learning": outcome.__dict__ if outcome else None,
        "state": LEARNER.state(),
    }


@app.post("/api/sources/{source_id}/clips/{clip_id}/hook")
def set_hook(source_id: str, clip_id: str, request: HookRequest) -> dict:
    analysis = db.get_analysis(source_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="not analyzed yet")
    target = next((c for c in analysis.candidates if c.id == clip_id), None)
    if target is None or target.llm is None:
        raise HTTPException(status_code=404, detail="clip or judgement not found")
    db.record_hook_edit(target.llm.hook, request.hook)
    db.save_clip_edit(source_id, clip_id, "hook", {"hook": request.hook})
    LEARNER.refresh_profile()
    return {"ok": True, "hook": request.hook, "state": LEARNER.state()}


@app.get("/api/sources/{source_id}/export")
def export_reel(source_id: str, format: str = "bundle", approved_only: bool = False):
    """Hand a clip decision to an NLE: OTIO, FCP7 XML, EDL, SRT or a zip of all.

    Media is referenced by absolute path, never copied into the bundle - a
    two-hour VOD in a zip is a mail attachment nobody can send.
    """
    from fastapi import Response

    from .editors import FORMATS, build_export, specs_for
    from .render import renders_dir

    source = db.get_source(source_id)
    analysis = db.get_analysis(source_id)
    if source is None or analysis is None:
        raise HTTPException(status_code=404, detail="source has no analysis yet")

    fmt = format.lower().strip()
    if fmt not in FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {FORMATS}")

    if approved_only:
        approved = _approved_ids()
        kept = [c for c in analysis.candidates if c.id in approved]
        if not kept:
            raise HTTPException(status_code=400, detail="no approved clips to export")
        analysis = analysis.model_copy(update={"candidates": kept})

    title = f"{Path(source.name).stem} reel"
    from .editors import bundle, specs_for

    specs = specs_for(source, analysis)
    if not specs:
        raise HTTPException(status_code=409, detail="no selected clips to export")

    if fmt == "bundle":
        # If clips were rendered already, ship them alongside the edit decisions.
        renders = sorted(renders_dir().glob("*.mp4"))
        wanted = [r for r in renders if any(r.name.startswith(s.id) for s in specs)]
        members = bundle.files(specs, renders=wanted, title=title)
        filename = f"{bundle.safe_name(title)}.zip"
        media_type = "application/zip"
        payload = bundle.zip_bytes(members, title)
    else:
        try:
            filename, media_type, payload = build_export(source, analysis, fmt, title)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/models")
def list_models() -> dict:
    """Model manifest with installed / active / fits-this-machine status."""
    from . import models

    return models.summary()


@app.post("/api/models/{model_id}/download")
def download_model(model_id: str) -> dict:
    from . import models

    if models.find(model_id) is None:
        raise HTTPException(status_code=404, detail="unknown model")

    def task(progress):
        return models.download(model_id, progress=progress)

    return JOBS.submit("download", task).to_dict()


@app.post("/api/models/{model_id}/activate")
def activate_model(model_id: str) -> dict:
    """Point the pipeline at a downloaded model and persist the choice."""
    from . import models

    try:
        return models.activate(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/readiness")
def readiness_check() -> dict:
    """Everything the setup cards need, from a single probe of the machine."""
    from . import readiness

    return readiness.snapshot()


@app.get("/api/settings/llm")
def get_llm_settings() -> dict:
    """Where scoring looks for a local model runner, and whether it answers."""
    from . import readiness

    return readiness.runner_settings()


@app.post("/api/settings/llm")
def set_llm_settings(request: RunnerRequest) -> dict:
    """Save a runner address. Takes effect on the next analysis, not a running one."""
    from . import readiness

    try:
        return readiness.save_runner(request.url)
    except PermissionError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "This address is set by your environment (CLIPPER_LLAMA_URL). "
                "Remove it there to change it here."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/settings/llm/test")
def test_llm_settings(request: RunnerRequest) -> dict:
    """Probe an address without saving it, so Test is safe to press."""
    from . import readiness
    from .llm.scorer import probe_runner

    try:
        url = readiness.normalize_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"url": url, **probe_runner(url)}


@app.get("/api/render/presets")
def render_presets() -> list[dict]:
    from .render.ass import PRESETS

    # The full catalogue, not a summary: the studio draws each preset from these
    # numbers, so a partial payload means a preview that lies.
    return [
        {
            "key": style.key,
            "label": style.label,
            "font": style.font,
            "size": style.size,
            "primary": style.primary,
            "secondary": style.secondary,
            "outline": style.outline,
            "back": style.back,
            "bold": style.bold,
            "outline_width": style.outline_width,
            "shadow": style.shadow,
            "alignment": style.alignment,
            "margin_h": style.margin_h,
            "margin_v": style.margin_v,
            "uppercase": style.uppercase,
            "karaoke": style.karaoke,
        }
        for style in PRESETS.values()
    ]


@app.get("/api/framing/status")
def framing_status() -> dict:
    """Whether face-aware framing can run here, and what it falls back to."""
    from . import models
    from .pipeline import faces

    # An explicit config path wins; otherwise the model the app downloaded.
    path = SETTINGS.framing.face_model or models.face_model_path()
    payload = faces.status(path)
    payload["configured"] = bool(SETTINGS.framing.face_model)
    payload["model_id"] = "face-yunet"
    return payload


@app.get("/api/fonts")
def list_fonts() -> dict:
    """Installed families, so a caption font can be picked rather than typed."""
    from .lang import SCRIPTS, font_for

    families: set[str] = set()
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
        ) as key:
            index = 0
            while True:
                try:
                    name, _value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                family = str(name).split(" (")[0].strip()
                if family:
                    families.add(family)
    except (ImportError, OSError):
        families = set()
    curated = {script: font_for(script) for script in SCRIPTS}
    if not families:
        families = {family for names in curated.values() for family in names}
    return {"families": sorted(families), "curated": curated}


def _subtitle_body(spec, fmt: str, preset: str = "hormozi") -> tuple[str, str]:
    from .editors import srt as srt_editor
    from .editors import vtt as vtt_editor

    if fmt == "vtt":
        return vtt_editor.build(spec), "text/vtt"
    if fmt == "ass":
        from .render.ass import build_ass_document, resolve_style

        # The clip's saved preset and overrides ride along, so the downloaded
        # ASS is the same picture the renderer burns.
        style = resolve_style(spec.caption_style, preset)
        body = build_ass_document(
            list(spec.pages),
            style,
            spec.start,
            SETTINGS.captions.max_chars_per_line,
            SETTINGS.captions.max_lines,
        )
        return body, "text/plain; charset=utf-8"
    return srt_editor.build(spec), "application/x-subrip"


def _safe_filename(name: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in " -_" else "" for char in name
    ).strip()
    return (cleaned or "captions")[:80]


def _approved_ids() -> set[str]:
    """The latest approve/reject per clip, oldest decision first."""
    approved: set[str] = set()
    for row in reversed(db.list_decisions(limit=100_000)):
        if row["action"] == "approve":
            approved.add(row["candidate_id"])
        elif row["action"] in {"reject", "undo"}:
            approved.discard(row["candidate_id"])
    return approved


@app.get("/api/sources/{source_id}/clips/{clip_id}/captions/style")
def get_caption_style(source_id: str, clip_id: str, preset: str | None = None) -> dict:
    """The preset with this clip's saved changes folded in - what the render will use."""
    from .render.ass import resolve_style, style_payload

    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    style = resolve_style(
        candidate.caption_style, preset or SETTINGS.captions.default_preset
    )
    return style_payload(style, candidate.caption_style)


@app.put("/api/sources/{source_id}/clips/{clip_id}/captions/style")
def put_caption_style(source_id: str, clip_id: str, request: dict) -> dict:
    """Save per-clip caption style; unknown or out-of-range keys drop out."""
    from .render.ass import clean_overrides, resolve_style, style_payload

    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    default_preset = SETTINGS.captions.default_preset
    preset = str(request.get("preset") or default_preset)
    overrides = clean_overrides(request.get("overrides", request))
    payload = {"preset": preset, "overrides": overrides}
    # A style that matches the default exactly is not an edit; clearing keeps
    # old analyses and the "Reset" path on one representation.
    if overrides or preset != default_preset:
        targets = [candidate]
        if request.get("apply_to_all"):
            analysis = db.get_analysis(source_id)
            targets = list(analysis.candidates) if analysis else [candidate]
        for clip in targets:
            db.save_clip_edit(source_id, clip.id, "caption_style", payload)
        style = resolve_style(payload, default_preset)
        result = style_payload(style, overrides)
        if len(targets) > 1:
            result["applied"] = len(targets)
        return result
    if request.get("apply_to_all"):
        db.clear_clip_edits(source_id, kind="caption_style")
    else:
        db.clear_clip_edits(source_id, clip_id, "caption_style")
    style = resolve_style({}, default_preset)
    return style_payload(style, {})


@app.delete("/api/sources/{source_id}/clips/{clip_id}/captions/style")
def clear_caption_style(source_id: str, clip_id: str, preset: str | None = None) -> dict:
    """Back to the shipped preset."""
    from .render.ass import get_preset, style_payload

    if db.find_candidate(source_id, clip_id) is None:
        raise HTTPException(status_code=404, detail="clip not found")
    db.clear_clip_edits(source_id, clip_id, "caption_style")
    return style_payload(get_preset(preset or SETTINGS.captions.default_preset), {})


@app.get("/api/sources/{source_id}/clips/{clip_id}/subtitles")
def clip_subtitles(
    source_id: str, clip_id: str, format: str = "srt", preset: str = "hormozi"
):
    """One clip's caption pages as an editable sidecar."""
    from .editors.spec import spec_for

    source = db.get_source(source_id)
    analysis = db.get_analysis(source_id)
    if source is None or analysis is None:
        raise HTTPException(status_code=404, detail="not analyzed yet")
    candidate = next((c for c in analysis.candidates if c.id == clip_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    fmt = (format or "srt").lower()
    if fmt not in {"srt", "vtt", "ass"}:
        raise HTTPException(status_code=400, detail="format must be srt, vtt or ass")
    spec = spec_for(source, candidate, candidate.rank or 1)
    body, media = _subtitle_body(spec, fmt, preset)
    return PlainTextResponse(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_filename(spec.name)}.{fmt}"'
        },
    )


@app.get("/api/sources/{source_id}/subtitles")
def reel_subtitles(
    source_id: str,
    format: str = "srt",
    approved_only: bool = False,
    preset: str = "hormozi",
):
    """Every clip's captions as a zip of sidecars, in rank order."""
    import io
    import zipfile

    from fastapi import Response

    from .editors.spec import specs_for

    source = db.get_source(source_id)
    analysis = db.get_analysis(source_id)
    if source is None or analysis is None:
        raise HTTPException(status_code=404, detail="not analyzed yet")
    fmt = (format or "srt").lower()
    if fmt not in {"srt", "vtt", "ass"}:
        raise HTTPException(status_code=400, detail="format must be srt, vtt or ass")
    specs = specs_for(source, analysis)
    if approved_only:
        approved = _approved_ids()
        specs = [spec for spec in specs if spec.id in approved]
        if not specs:
            raise HTTPException(status_code=400, detail="no approved clips to export")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for spec in specs:
            body, _media = _subtitle_body(spec, fmt, preset)
            archive.writestr(f"{_safe_filename(spec.name)}.{fmt}", body)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="captions-{fmt}.zip"'},
    )


@app.post("/api/sources/{source_id}/clips/{clip_id}/trim")
def trim_clip(source_id: str, clip_id: str, request: TrimRequest) -> dict:
    from .service import trim_clip as do_trim

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    try:
        candidate = do_trim(source, clip_id, request.start, request.end)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return candidate.model_dump()


@app.get("/api/sources/{source_id}/clips/{clip_id}/suggestions")
def get_suggestions(source_id: str, clip_id: str) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return {"suggestions": coach.refresh(candidate)}


@app.post("/api/sources/{source_id}/clips/{clip_id}/suggestions/{suggestion_id}/preview")
def preview_suggestion(source_id: str, clip_id: str, suggestion_id: str) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    item = coach.get(suggestion_id)
    if candidate is None or item is None or item["clip_id"] != clip_id:
        raise HTTPException(status_code=404, detail="suggestion not found")
    return {"suggestion": item, "preview": coach.preview(candidate, item)}


@app.post("/api/sources/{source_id}/clips/{clip_id}/suggestions/{suggestion_id}/apply")
def apply_suggestion(source_id: str, clip_id: str, suggestion_id: str) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    try:
        outcome = coach.apply(source_id, clip_id, suggestion_id, candidate=candidate)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = db.find_candidate(source_id, clip_id)
    return {**outcome, "candidate": updated.model_dump() if updated else None}


@app.post("/api/sources/{source_id}/clips/{clip_id}/suggestions/{suggestion_id}/undo")
def undo_suggestion(source_id: str, clip_id: str, suggestion_id: str) -> dict:
    try:
        outcome = coach.undo(source_id, clip_id, suggestion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = db.find_candidate(source_id, clip_id)
    return {**outcome, "candidate": updated.model_dump() if updated else None}


@app.post("/api/sources/{source_id}/clips/{clip_id}/suggestions/{suggestion_id}/dismiss")
def dismiss_suggestion(source_id: str, clip_id: str, suggestion_id: str) -> dict:
    item = coach.get(suggestion_id)
    if item is None or item["clip_id"] != clip_id:
        raise HTTPException(status_code=404, detail="suggestion not found")
    return coach.dismiss(suggestion_id)


@app.get("/api/sources/{source_id}/clips/{clip_id}/framing")
def clip_framing(source_id: str, clip_id: str) -> dict:
    """Where the "auto" reframer would put the crop, and why.

    Exposed so the plan can be inspected before spending a render - a reframe you
    cannot see is indistinguishable from a bug the first time it is wrong.
    """
    from .pipeline.framing import plan_for_clip
    from .pipeline.scenes import cuts_for, shots_between

    source = db.get_source(source_id)
    candidate = db.find_candidate(source_id, clip_id)
    if source is None or candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    cuts = cuts_for(source.path, None, source.duration)
    plan = plan_for_clip(source, candidate, cuts)
    return {
        "cuts": cuts[:200],
        "shots": [list(span) for span in shots_between(cuts, candidate.start, candidate.end)],
        "plan": plan.summary() if plan else None,
        "expression": plan.expression() if plan else "",
    }


@app.post("/api/sources/{source_id}/clips/{clip_id}/render")
def render_clip(source_id: str, clip_id: str, request: RenderRequest) -> dict:
    from .render import render_clip as do_render

    source = db.get_source(source_id)
    candidate = db.find_candidate(source_id, clip_id)
    if source is None or candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")

    def task(progress):
        return do_render(
            source,
            candidate,
            preset_key=request.preset,
            framing=request.framing,
            force=request.force,
            progress=progress,
        )

    return JOBS.submit("render", task).to_dict()


@app.post("/api/sources/{source_id}/export/bake")
def bake_export(source_id: str, request: BakeRequest) -> dict:
    """Render the whole reel into one folder of finished vertical MP4s."""
    from .editors.bake import bake_reel

    source = db.get_source(source_id)
    analysis = db.get_analysis(source_id)
    if source is None or analysis is None:
        raise HTTPException(status_code=404, detail="not analyzed yet")
    approved = _approved_ids()

    def task(progress):
        return bake_reel(
            source,
            analysis,
            preset=request.preset,
            framing=request.framing,
            approved_only=request.approved_only,
            approved=approved,
            progress=progress,
        )

    return JOBS.submit("render", task).to_dict()


@app.get("/api/sources/{source_id}/export/bake")
def last_bake(source_id: str) -> dict:
    """Where the last bake landed, without re-reading a finished job."""
    import json as json_module

    from .editors.bake import bake_dir

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    folder = bake_dir(source)
    manifest = folder / "manifest.json"
    if not manifest.exists():
        return {"folder": str(folder), "exists": False, "clips": []}
    try:
        payload = json_module.loads(manifest.read_text("utf-8"))
    except (OSError, ValueError):
        return {"folder": str(folder), "exists": False, "clips": []}
    return {"folder": str(folder), "exists": True, **payload}


@app.get("/api/sources/{source_id}/export/bake/file/{filename}")
def bake_file(source_id: str, filename: str):
    """One baked MP4, so the folder is reachable from the browser too."""
    from .editors.bake import bake_dir

    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    safe = Path(filename).name
    if safe != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = bake_dir(source) / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="baked clip not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=safe,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/reveal")
def reveal_folder(request: RevealRequest) -> dict:
    """Open a bake folder in the desktop file manager.

    Restricted to the exports tree: a loopback API that opens any path handed to
    it turns a stray link into a way to launch things.
    """
    import sys

    from .editors.bake import bakes_root

    root = bakes_root()
    try:
        target = Path(request.path).resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if target != root and root not in target.parents:
        raise HTTPException(status_code=403, detail="only bake folders can be opened")
    if not target.exists():
        raise HTTPException(status_code=404, detail="that folder does not exist yet")
    try:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"could not open the folder: {exc}") from exc
    return {"ok": True, "path": str(target)}


@app.get("/api/renders/{filename}")
def get_render(filename: str):
    from .render import renders_dir

    safe = Path(filename).name
    if safe != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = renders_dir() / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="render not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=safe,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/learn/state")
def learn_state() -> dict:
    return LEARNER.state()


@app.post("/api/learn/profile/refresh")
def refresh_profile() -> dict:
    summary = LEARNER.refresh_profile()
    return {"ok": True, "summary": summary, "state": LEARNER.state()}


@app.get("/api/learning/weekly")
def weekly_state() -> dict:
    return weekly.status()


@app.post("/api/learning/weekly/run")
def run_weekly() -> dict:
    return weekly.run()


@app.get("/api/learn/personal")
def personal_state(account_id: str = "") -> dict:
    return personal.state(account_id)


@app.post("/api/learn/personal/train")
def train_personal(account_id: str = "") -> dict:
    return personal.train(account_id)


@app.post("/api/learn/personal/{version}/activate")
def activate_personal(version: str) -> dict:
    try:
        return personal.activate(version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/learn/personal/rollback")
def rollback_personal() -> dict:
    personal.rollback()
    return personal.state()


@app.get("/api/learn/export")
def export_dataset() -> PlainTextResponse:
    lines = demo.build_training_export()
    return PlainTextResponse("\n".join(lines), media_type="application/jsonl")


@app.get("/api/ffmpeg")
def ffmpeg_info() -> dict:
    try:
        filters = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        encoders = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": " ass " in filters,
        "libass": " ass " in filters,
        "encoders": {"h264_amf": "h264_amf" in encoders, "h264_nvenc": "h264_nvenc" in encoders},
    }


# --- Connected accounts and publishing -------------------------------------

def _media_from_request(request: PublishDraftRequest):
    if request.media:
        allowed = {"duration", "width", "height", "size_bytes", "has_audio", "format"}
        try:
            return publish_limits.MediaInfo(**{k: request.media[k] for k in allowed if k in request.media})
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid media metadata: {exc}") from exc
    if not request.media_path:
        raise HTTPException(status_code=400, detail="Provide media_path or media metadata.")
    try:
        return publish_limits.probe_media(request.media_path)
    except Exception as exc:  # noqa: BLE001 - ffprobe errors are user-facing
        raise HTTPException(status_code=400, detail=f"Could not read the video: {exc}") from exc


def _draft_from_request(request: PublishDraftRequest):
    media = _media_from_request(request)
    draft = publish_limits.PublishDraft(
        platform=request.platform,
        media=media,
        title=request.title,
        caption=request.caption,
        hashtags=list(request.hashtags),
        visibility=request.visibility,
        scheduled_at=float(request.scheduled_at or 0.0),
        made_for_kids=bool(request.made_for_kids),
        public_url=request.public_url,
    )
    result = publish_limits.validate(draft)
    return draft, result


def _callback_page(ok: bool, title: str, message: str) -> HTMLResponse:
    import html as html_module

    color = "#4ade80" if ok else "#f87171"
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html_module.escape(title)}</title>
    <style>body{{font-family:system-ui,sans-serif;background:#0b0d10;color:#e5e7eb;display:grid;place-items:center;height:100vh;margin:0}}
    .card{{max-width:520px;padding:32px;border:1px solid #252a31;border-radius:16px;background:#12151a}}
    h1{{font-size:20px;margin:0 0 12px;color:{color}}}p{{line-height:1.55;color:#a9b1bd}}</style></head>
    <body><div class="card"><h1>{html_module.escape(title)}</h1><p>{html_module.escape(message)}</p></div></body></html>"""
    return HTMLResponse(body, status_code=200 if ok else 400)


@app.get("/api/accounts")
def list_accounts() -> dict:
    rows = [account.to_dict() for account in accounts.list_accounts()]
    platforms = []
    for platform, row in publish_limits.LIMITS.items():
        payload = row.as_dict()
        payload["connected"] = accounts.account_count(platform)
        payload["adapter"] = platform in ("youtube", "x")
        platforms.append(payload)
    return {
        "accounts": rows,
        "platforms": platforms,
        "secret_store": secrets.status(),
    }


@app.post("/api/accounts/{platform}/connect")
def start_account_connection(platform: str, request: ConnectStartRequest) -> dict:
    if platform not in publish_limits.LIMITS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")
    try:
        stored = accounts.load_provider_client(platform)
        client_id = request.client_id.strip() or stored["client_id"]
        client_secret = request.client_secret.strip() or stored["client_secret"]
        start = publish_oauth.start(
            platform,
            client_id,
            client_secret,
            redirect_uri=request.redirect_uri,
            scopes=request.scopes,
        )
        accounts.save_provider_client(platform, client_id, client_secret)
    except secrets.SecretStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except publish_oauth.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return start.as_dict()


@app.get("/api/connections/callback")
def account_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> HTMLResponse:
    if error:
        return _callback_page(False, "Connection cancelled", error_description or error)
    if not code or not state:
        return _callback_page(False, "Connection failed", "The provider did not return a code and state.")
    try:
        started, token = publish_oauth.complete(code, state)
        creds = accounts.load_provider_client(started.platform)
        account = accounts.connect_account(
            started.platform,
            token,
            creds["client_id"],
            creds["client_secret"],
        )
    except secrets.SecretStoreUnavailable as exc:
        return _callback_page(False, "Secure storage unavailable", str(exc))
    except (publish_oauth.OAuthError, accounts.AccountError) as exc:
        return _callback_page(False, "Connection failed", str(exc))
    return _callback_page(
        True,
        f"{account.display_name} connected",
        "The account token is stored in your operating system credential store. You can close this tab and return to Clip Factory.",
    )


@app.delete("/api/accounts/{account_id}")
def disconnect_account(account_id: str) -> dict:
    if not accounts.delete_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"ok": True}


@app.post("/api/accounts/{account_id}/sync")
def sync_account(account_id: str) -> dict:
    """Pull recent posts and snapshot metrics now. Also runs weekly while the app is open."""
    if accounts.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    try:
        return analytics.sync_account(account_id)
    except accounts.ReconnectRequired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except accounts.AccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - platform errors are user-facing
        from .publish.base import PublishError
        if isinstance(exc, PublishError):
            raise HTTPException(status_code=502, detail={"message": str(exc), "code": exc.code}) from exc
        raise


@app.get("/api/accounts/{account_id}/overview")
def account_overview(account_id: str) -> dict:
    if accounts.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return analytics.account_overview(account_id)


@app.get("/api/accounts/{account_id}/posts")
def account_posts(account_id: str, limit: int = 100) -> dict:
    if accounts.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    posts = analytics.list_posts(account_id, limit=limit)
    return {"posts": posts, "baseline": analytics.baseline(account_id)}


@app.get("/api/publish/limits")
def publish_platform_limits() -> dict:
    return {
        "platforms": {platform: row.as_dict() for platform, row in publish_limits.LIMITS.items()},
        "supported": ["youtube", "x"],
        "last_verified": "2026-11",
    }


@app.post("/api/publish/validate")
def validate_publish(request: PublishDraftRequest) -> dict:
    try:
        draft, result = _draft_from_request(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    from dataclasses import asdict

    return {
        "ok": result.ok,
        "issues": [issue.as_dict() for issue in result.issues],
        "limits": result.limits.as_dict() if result.limits else None,
        "media": asdict(draft.media),
    }


def _submit_publish(job_id: str):
    # Claim before submitting. Both the create route and the retry scheduler can
    # see the same due row; only one of them may own the upload.
    if publish_queue.claim(job_id) is None:
        return None

    def task(progress):
        return publish_queue.process(job_id, progress)

    try:
        return JOBS.submit("publish", task)
    except Exception as exc:  # noqa: BLE001 - a refused task must not leave a running row
        publish_queue.mark_failure(job_id, f"Could not start upload: {exc}", retryable=True)
        raise


@app.post("/api/publish")
def create_publish(request: PublishCreateRequest) -> dict:
    if request.platform not in ("youtube", "x"):
        raise HTTPException(
            status_code=400,
            detail=f"{request.platform.title()} publishing is not enabled yet. Use Export & share for now.",
        )
    if not request.media_path:
        raise HTTPException(status_code=400, detail="A rendered media_path is required to publish.")
    account = accounts.get_account(request.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Connect that account before publishing.")
    if account.platform != request.platform:
        raise HTTPException(status_code=400, detail="That account belongs to a different platform.")
    try:
        draft, result = _draft_from_request(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not result.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "This clip does not fit the platform yet.",
                "issues": [issue.as_dict() for issue in result.issues],
            },
        )
    from dataclasses import asdict
    from datetime import datetime, timezone

    scheduled_iso = ""
    if request.scheduled_at:
        scheduled_iso = datetime.fromtimestamp(request.scheduled_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "title": request.title,
        "description": request.caption,
        "caption": request.caption,
        "tags": list(request.hashtags),
        "hashtags": list(request.hashtags),
        "visibility": request.visibility,
        "made_for_kids": request.made_for_kids,
        "publish_at": scheduled_iso,
        "category_id": "22",
        "duration_s": draft.media.duration,
        "media": asdict(draft.media),
        "policy_version": policy.active().version,
    }
    metadata.update(request.metadata)
    try:
        job = publish_queue.enqueue(
            platform=request.platform,
            account_id=request.account_id,
            media_path=request.media_path or "",
            metadata=metadata,
            source_id=request.source_id,
            clip_id=request.clip_id,
            idempotency_key=request.idempotency_key,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _submit_publish(job["id"])
    return job


@app.get("/api/publish/jobs")
def list_publish_jobs(limit: int = 50, status: str | None = None) -> dict:
    return {"jobs": publish_queue.list_jobs(limit=limit, status=status)}


@app.get("/api/publish/jobs/{job_id}")
def get_publish_job(job_id: str) -> dict:
    job = publish_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Publish job not found.")
    return job


@app.post("/api/publish/jobs/{job_id}/retry")
def retry_publish_job(job_id: str) -> dict:
    try:
        job = publish_queue.retry(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Publish job not found.")
    _submit_publish(job_id)
    return job


@app.post("/api/publish/jobs/{job_id}/cancel")
def cancel_publish_job(job_id: str) -> dict:
    job = publish_queue.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Publish job not found.")
    return job


@app.get("/api/posts")
def list_posts(limit: int = 50) -> dict:
    return {"posts": analytics.list_posts("", limit=limit)}

# Production: the built UI is served from the same origin as the API, so the
# desktop shell only has to load one URL. Mounted last so /api keeps priority.
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")

"""HTTP API. The Electron shell and the browser dev server both talk to this.

Everything is localhost-only and single-user; there is no auth layer by design,
and the sidecar binds 127.0.0.1 in production (see __main__).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, db, demo, hardware, service
from .config import SETTINGS
from .jobs import JOBS
from .learn import LEARNER
from .pipeline.media import MediaError

app = FastAPI(title="Clip Factory", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_probe_cache: dict = {}


class IngestRequest(BaseModel):
    path: str
    name: str | None = None


class ChatRequest(BaseModel):
    url: str | None = None


class AnalyzeRequest(BaseModel):
    subtitle_path: str | None = None
    chat_path: str | None = None
    limit: int = 10
    force: bool = False


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


@app.on_event("startup")
def _startup() -> None:
    db.init()


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
    out: list[dict] = []
    for source in db.list_sources():
        analysis = db.get_analysis(source.id)
        out.append(
            {
                **source.model_dump(),
                "analyzed": analysis is not None,
                "clip_count": len([c for c in analysis.candidates if c.rank]) if analysis else 0,
                "reel_quality": analysis.reel_quality if analysis else 0.0,
            }
        )
    return out


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

    def task(progress):
        return service.analyze(
            source,
            subtitle_path=request.subtitle_path,
            chat_path=request.chat_path,
            limit=request.limit,
            progress=progress,
            force=request.force,
        ).model_dump()

    job = JOBS.submit("analyze", task)
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return JOBS.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    payload = job.to_dict()
    if job.status == "done" and job.result is not None and isinstance(job.result, dict):
        payload["analysis"] = job.result
    return payload


@app.get("/api/sources/{source_id}/analysis")
def get_analysis(source_id: str) -> dict:
    analysis = db.get_analysis(source_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="not analyzed yet")
    return analysis.model_dump()


@app.get("/api/sources/{source_id}/peaks")
def get_peaks(source_id: str, buckets: int = 1400) -> dict:
    try:
        data = np.load(str(service.artifacts_for(source_id) / "peaks.npz"))
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="peaks not built yet") from exc
    if "min64" not in data:
        raise HTTPException(status_code=500, detail="peaks artifact malformed")
    lows, highs = data["min64"], data["max64"]
    total_samples = int(data["count"][0]) if "count" in data else int(lows.size * 64)
    buckets = max(50, min(4000, buckets))
    n = int(lows.size)
    if n == 0:
        return {"duration": 0.0, "low": [], "high": [], "buckets": 0}
    edges = (np.arange(buckets + 1) * n // buckets).astype(np.int64)
    edges = np.clip(edges, 0, n)
    starts = edges[:-1]
    valid = starts < n
    low = np.minimum.reduceat(lows, starts[valid])
    high = np.maximum.reduceat(highs, starts[valid])
    return {
        "duration": round(total_samples / SETTINGS.audio.sample_rate, 3),
        "low": [round(float(v), 4) for v in low],
        "high": [round(float(v), 4) for v in high],
        "buckets": int(valid.sum()),
    }


@app.get("/api/media/{source_id}")
def get_media(source_id: str):
    source = db.get_source(source_id)
    if source is None or not Path(source.path).exists():
        raise HTTPException(status_code=404, detail="media not found")
    return FileResponse(source.path, filename=Path(source.path).name)


@app.get("/api/sources/{source_id}/clips/{clip_id}")
def get_clip(source_id: str, clip_id: str) -> dict:
    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return candidate.model_dump()


@app.get("/api/sources/{source_id}/clips/{clip_id}/captions")
def get_captions(source_id: str, clip_id: str) -> dict:
    from .pipeline.caption import caption_stats, group_words

    candidate = db.find_candidate(source_id, clip_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="clip not found")
    pages = group_words(candidate.words, SETTINGS.captions)
    return {
        "clip_id": clip_id,
        "pages": [p.model_dump() for p in pages],
        "stats": caption_stats(pages),
    }


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
    target.llm = target.llm.model_copy(update={"hook": request.hook})
    db.save_analysis(analysis)
    LEARNER.refresh_profile()
    return {"ok": True, "hook": request.hook, "state": LEARNER.state()}


@app.get("/api/sources/{source_id}/export")
def export_reel(source_id: str, format: str = "bundle"):
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


@app.get("/api/render/presets")
def render_presets() -> list[dict]:
    from .render.ass import PRESETS, style_summary

    return [style_summary(style) for style in PRESETS.values()]


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


@app.get("/api/renders/{filename}")
def get_render(filename: str):
    from .render import renders_dir

    safe = Path(filename).name
    if safe != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = renders_dir() / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="render not found")
    return FileResponse(path, media_type="video/mp4", filename=safe)


@app.get("/api/learn/state")
def learn_state() -> dict:
    return LEARNER.state()


@app.post("/api/learn/profile/refresh")
def refresh_profile() -> dict:
    summary = LEARNER.refresh_profile()
    return {"ok": True, "summary": summary, "state": LEARNER.state()}


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


# Production: the built UI is served from the same origin as the API, so the
# desktop shell only has to load one URL. Mounted last so /api keeps priority.
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")

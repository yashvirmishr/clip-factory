# Limitations

Clip Factory is deliberately narrow. This page lists what it does not do, so you can decide whether it fits before fighting it.

## It is not a timeline editor

The centre Timeline is a review and navigation surface: it shows the source, ranked windows and clip boundaries. It is not a multitrack NLE. There are no tracks, transitions, effects, keyframes, titles, colour grading, speed ramps, audio mixing or frame-accurate manual cuts beyond the per-clip trim.

The intended workflow is: find and shape the clip here, then hand it to Premiere, Resolve or another editor through OTIO, FCP7 XML, EDL or a bundle.

There is no global undo/redo across analysis, render, trim, hook or workspace changes. Individual surfaces offer local escape hatches (revert a hook edit, reset a trim, undo a verdict), but they are not a history stack.

## One source, one reel at a time

The analysis and export model is built around a source and its ranked reel. There is no project file, no multi-source sequence, no batch analysis across a library and no batch render queue. The single compute lane means one CPU-heavy task at a time by design; a separate I/O lane keeps downloads and uploads from blocking it.

Sources can be removed and relinked one at a time. Removal deletes only files under `media/` (URL downloads); an imported file is always left on disk. There is no multi-select cleanup, no batch relink and no background scan for missing files.

Cancellation is cooperative: the analysis bar, a render and a bake each have a cancel control, but a native step already running (one ffmpeg pass, one whisper call) finishes before the job stops. A cancelled bake keeps the clips it already finished. The queue is in memory, so restarting the backend loses queued work (completed files remain).

## Analysis is a ranking signal, not a verdict

The score does not predict views, retention or virality. It ranks candidates against structural and signal heuristics. A high score is a reason to watch the clip, not a promise.

The pipeline is built for spoken, stream-style content. Word counting, sentence ends, subtitle widths and caption fonts are script-aware: Han, kana, Hangul, Arabic, Hebrew and Indic scripts are measured and wrapped correctly, uppercase styling is skipped where a script has no case, and the hallucination gate judges script switching against the language the analysis asked for rather than penalising every non-Latin transcript.

The app ships no model, but Models can download multilingual Whisper models (`base`, `small`, `medium`, `large-v3-turbo`): choose one of those to transcribe anything other than English. An `.en` model can only produce English words no matter which language you select, so pick a multilingual model before blaming the language picker. Translation exists only as whisper's translate-to-English flag — there is no translation into any other language. Music, gameplay with little speech and heavily overlapping speakers produce weak or empty reels in every language.

ASR quality is the ceiling. A missed word, a music hallucination or a bad speaker boundary propagates into windows, gates, the hook and captions. The app can show low confidence, but it cannot recover speech that was never transcribed.

Automatic framing uses motion and skin density by default. The face tier is opt-in twice: install `opencv-python-headless` (`requirements-optional.txt`) and download **Face tracking (YuNet)** in Models. Neither tier does speaker diarization. Both can follow the wrong subject in a wide shot, a cutaway or a scene with warm-toned backgrounds, and can produce an uncomfortable crop when nobody is clearly framed.

The hook is generated text, not a claim checked against the world. The grounding scorecard check measures whether the hook's words appear in the clip transcript; it does not establish that the statement is true or safe.

## Language and models

No speech or language model ships with the repository. Transcription needs a separate `whisper-cli` binary plus an ASR model downloaded from Models (pick a multilingual one for non-English sources); the VAD model is optional but recommended. **Programs** can install ffmpeg and whisper.cpp automatically on Windows x64 only; elsewhere both come from the machine. Without them, transcription uses an API-supplied subtitle if one is provided; otherwise the deterministic stub runs, and that transcript is synthetic and must not be mistaken for real speech recognition.

The local LLM is optional and is not managed as a child process. You run `llama-server` yourself and point `CLIPPER_LLAMA_URL` at it. Without it, the heuristic scorer runs and is labelled as such. The app does not download, launch, supervise or restart the inference server.

Model downloads are a curated manifest. The UI does not manage arbitrary GGUF files, LoRAs or fine-tunes. A model that fits the manifest but not current free memory can still be installed; activation warns, but the app cannot make it fit.

The taste learner needs local decisions before it does anything. Below its threshold it is inert; above it, it can still overfit a small or inconsistent history. It does not override structural gates, and it cannot fix bad ASR.

The engagement learner has stricter gates: 30 full-feature posts, at least 10 positives and 10 negatives, a held-out AUC, a reach-only baseline and a permutation test. When it does promote, it changes at most 20% of the final score. It learns correlation inside one account, not causation, and a small or young account may never clear the gate. Labels use weighted engagement rate, not views, so a high-reach post with no interaction is not automatically “good”.

## Captions

Caption **words** are read-only in the UI. You can inspect pages, word counts and CPS, but changing words means the `PUT /captions` API. There is no click-to-edit caption timeline, no per-word nudge control and no caption track in the NLE export.

Caption **style** is editable per clip in the subtitle studio: font, size, colours, outline, bottom margin, case and word animation. Placement is bottom-centre only and alignment is not exposed. There is no arbitrary font upload or safe-area editor.

Caption layout is fixed by configuration: at most four words per page, two lines, 22 columns per line, 19 CPS and a 0.35 s minimum page. The twelve presets change style, not layout. For scripts written without spaces (Han, kana, Thai) the same column budget applies, but width is measured in display columns: 22 columns is 11 Han glyphs per line, not 22, so a two-line page holds about 22 characters rather than 44.

Rendered caption fonts depend on fonts available to libass. The presets name common faces such as Arial Black; a machine without them gets a substitution. When the transcript's script has no glyphs in the preset family (for example Han with Arial Black), the style is swapped for an installed family for that script, such as Microsoft YaHei or Nirmala UI; a font you picked explicitly is left alone. The ASS file is correct even when the local font is not.

The hook is not burned into the MP4. This is intentional: the hook is an overlay for review and metadata for the edit. If you want it on screen, add it as a title in your NLE.

## Render

Output is fixed at 1080×1920 H.264/AAC. There is no 4K, no square or landscape deliverable, no HEVC/ProRes option and no per-clip bitrate control. The encoder chooses a tested hardware path when available and falls back to `libx264`; it is not a general transcoding UI.

Rendering is one ffmpeg pass over the source segment. Very long clips, difficult sources and software encoding take time. Hardware encoding can fail after probing; the automatic retry is slower.

Rendered files are cached by clip, preset, framing and caption pages. Changing the hook does not invalidate the cache because the picture did not change. Old renders are not garbage-collected automatically.

There is no render farm, distributed encoding, background render while the app is closed, or progress recovery after a restart.

## Export

Exports reference media by absolute path. They do not copy or consolidate source files, so a bundle moved to another machine has offline media until it is relinked.

The export includes every ranked clip by default. **Approved clips only** narrows it, but the default still means rejecting a clip does not remove it from the handoff. Curate in the NLE, use the switch, or trim the exported sequence.

EDL is the lowest-fidelity handoff: cuts and comments, no complex reframing, transitions or effects. FCP7 XML and OTIO carry more, but they are not a guarantee that every NLE will reconstruct every decision perfectly.

Timecode is non-drop-frame. There is no drop-frame option, which matters for 29.97 and 59.94 workflows that expect it.

There is no direct upload to TikTok or Instagram; only YouTube and X publishing are implemented, and both need your own OAuth client and a platform account that allows the requested scopes. Everything else produces local files. There is no scheduling calendar, no cross-posting in one action and no hosted OAuth callback.

## Learning and coaching

The weekly loop trains on posts the app published and can attribute to a full feature vector. Uploads made elsewhere are not used for training, so a fresh install starts with no personal model no matter how many posts the account already has. A post with missing caption or analysis features is excluded rather than guessed at.

Coach suggestions are deterministic rules over transcript and signal evidence. They can be wrong when the transcript is wrong, and they do not understand irony, context or whether a joke lands. Applying a trim can move the end into a word; preview is there because the rule cannot hear the result. Suggestions never publish, render or rewrite a clip without an explicit apply.

## Import

URL import is one HTTP(S) video at a time. Playlists and channel URLs are refused. It depends on `yt-dlp`, and platform changes can break a fetch without warning. Downloads are pinned to H.264/AAC in MP4 for editor compatibility.

Only Twitch VODs have chat replay import. YouTube and local files do not. Chat is reduced to message offsets, not text, so the app cannot show you what chat said.

Subtitle import is an API option (`subtitle_path`), not an interface control. It is consulted only when whisper is unavailable. The per-source transcript artifact is reused even by a forced analysis, so changing ASR output means deleting that artifact first.

There is no live stream capture, no screen recording, no webcam capture and no audio-only workflow.

## Workspace and themes

Workspace layout and custom themes live in `localStorage`. They do not travel with an export, a data directory or another browser. Clearing site data removes them. Themes are not tied to a connected account, and there is no server-side theme store.

The Marketplace is a local library, not an online catalogue. Sharing is a JSON file or clipboard copy; there is no install link, rating, moderation or remote update.

The Studio does not expose the `scheme` or `tags` fields. They are preserved from the base theme and can be changed in the JSON. A hand-inverted theme with the wrong scheme will render correctly but native browser widgets and scrollbars may use the wrong mode.

Contrast checks are advisory. The app will not stop you from applying a theme with unreadable muted text or focus rings.

The interface is English-only. There is no localization layer or RTL layout work.

The UI is desktop-first. Compact layouts collapse panels and remain usable on a small window, but editing on a phone is not a supported workflow. The Timeline is a visual canvas; the reel/list view is the practical keyboard and screen-reader path.

## Platform and operations

The Windows installer is unsigned, per-user and builds from source with
`scripts/build-release.ps1`; there is no auto-updater or code signing. It bundles
the Python runtime and the built UI, but downloads ffmpeg, whisper.cpp and models
on demand instead of bundling them, so the first run needs a connection. ffmpeg
is GPLv3, whisper.cpp is MIT; the dialog names each license. Running from a
checkout still needs a built
`web/dist` and the repository virtualenv (falling back to `python` or
`python3` on `PATH`).

The backend is single-user and unauthenticated. It binds to loopback by default and must not be exposed to a network. Two backend processes against one SQLite data directory will contend for the database.

The SQLite schema upgrades itself only for the columns it knows about: startup runs guarded `ALTER TABLE ... ADD COLUMN` statements and backfills the two analysis summary columns. There is no general migration versioning, so a change that rewrites or drops data still needs a fresh data directory or a manual migration.

Analysis, renders, captions and thumbnails are stored on local disk without eviction. There is no storage quota, cleanup policy or project archive.

There is no telemetry and no crash reporter. Diagnosing a problem requires the error text, job payload and local logs; the app cannot send them for you.

---

Back to [Home](Home.md).

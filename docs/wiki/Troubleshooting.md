# Troubleshooting

Start with the failing surface, not the whole stack. The UI usually names the stage; the API can give the exact error.

## The page will not load

**Connection refused on 8756.** The backend is not running, or it exited during startup. Run it in a terminal and read the traceback:

```powershell
$env:PYTHONPATH = "backend"
./.venv/Scripts/python.exe -m clipper --port 8756
```

**`No module named clipper`.** `PYTHONPATH=backend` is missing. `scripts/run.cmd` sets it; a manual command must too.

**Blank page at 8756.** There is no built frontend. Run `npm run build` in `web/`, then restart the API. The development server on 5173 does not need `web/dist`.

**The page loads but every request fails.** Vite may have chosen port 5174 because 5173 was busy. The API only allows the two configured development origins on port 5173. Stop the other Vite process and restart, or open the instance actually on 5173.

**The port is already in use.** Another backend is still running. Stop it, or start this one with `--port 8757` and change the proxy target in `web/vite.config.ts`.

**Electron says `app is undefined`.** `ELECTRON_RUN_AS_NODE=1` is set in the shell. Unset it for that command.

## Analysis

**Nothing happens after Analyze.** Check that the source appears and the job is running. The backend worker is single-threaded; a download, another analysis or a render in front of it will delay the job. `GET /api/health` reports `busy`, and `GET /api/jobs` shows the queue.

**Progress stops at a stage.** Read the job's `error` and `detail` fields. A failure inside the worker is reported there rather than as an HTTP error on the analyze request.

**The transcript is synthetic or says stub.** No usable ASR backend was found. Install the `whisper-cli` binary on `PATH` or in `<data>/bin`, and download an ASR plus VAD model in Hardware & models. Without them the deterministic stub keeps the pipeline usable, but the transcript is not real.

**A model is downloaded but not used.** Downloading and activating are separate. Open Hardware & models and activate the model. A normal analyze returns the cached analysis; force rebuilds it. For a **scoring** change, force is enough. For an **ASR** change, `artifacts/<source-id>/transcript.json` is reused even on force: delete that file first, then force.

**`llama-server-failed` or `llama-server-invalid`.** The configured endpoint was reachable but the request failed or returned unusable JSON. Check that `llama-server` is running at the URL in `CLIPPER_LLAMA_URL`, that the model is loaded, and that the URL answers `/v1/models`. If no URL is configured, the heuristic scorer is used; its provider is `heuristic-stub`, not an error.

**No clips were found.** The pipeline can legitimately return an empty reel when every window fails the structural gates: too little speech, very low ASR confidence, a source that is mostly music, or windows under the minimum word count. Try a longer, speech-led section. The analysis warnings often name the gate that rejected the most windows.

**The score does not match what I would pick.** That is a ranking signal, not a forecast. Read the eight scorecard checks and the signal bars before assuming a bug. The learning loop only starts influencing results after enough of your own decisions.

**Results look stale after a trim or hook edit.** The analysis is persisted. Trims rebuild the candidate; hook edits update the judgement. If you changed scoring or gate settings, force a full re-analysis. For an ASR change, also delete the transcript artifact first.

## URL import and chat

**URL import returns 409.** `yt-dlp` is not installed in the virtualenv:

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m yt_dlp --version
```

**URL import rejects my link.** Only a single HTTP(S) video URL is accepted. Channel and playlist URLs are refused deliberately. A valid Twitch VOD looks like `https://www.twitch.tv/videos/<id>`.

**A download succeeds but the file will not import.** The fetcher pins H.264/AAC in MP4 so the edit target can decode it. A source that still fails is usually not the pinned download; read the ingest error for the codec or container ffprobe reported.

**Fetch chat is missing.** It only appears for a Twitch VOD source. YouTube and local files have no public replay endpoint the app can use.

**Chat fetch fails with 400.** The source or supplied URL is not a Twitch VOD URL. A live channel URL is not a VOD.

## Setup and the tour

**The tour is gone.** It runs once on a fresh install. Open **Help → Take the
tour** (or the command palette, "Take the tour"). Progress resumes where you
stopped; after the last step it starts from the top.

**Setup says "needs a runner" for reading speech.** Two separate things are
required: a speech model (downloaded in setup) and the `whisper-cli` program
(one file, placed in the folder setup names). Setup has buttons to open that
folder and to check again. Without either, clips are cut from a stand-in
transcript and the app labels them that way.

**I do not want to download a speech model.** Add a video that already has
`.srt` or `.vtt` subtitles next to it. The import reads those words instead.

**Where do I set the scoring model address?** **Help → This computer**, under
Scoring. Test checks the address without saving. The same address can come from
`CLIPPER_LLAMA_URL`; when it does, the field is read-only and says so.

**The model runner is unreachable.** Scoring falls back to the built-in rules.
Start `llama-server` yourself, load a model, then press Test. The app never
starts it for you.

**A check blocks a clip I like.** In the inspector, "Checks" names each failed
check in plain words and whether it stops the clip or only flags it. Blocked
clips stay in the list until you reject or trim them; nothing is deleted.

## Captions and rendering

**`No such filter: ass` or an ffmpeg subtitle error.** Your ffmpeg build lacks libass. Install a full build with the `ass` filter and check `GET /api/ffmpeg`; `available` must be true. Restart the backend after changing `PATH`.

**A render finishes but has no captions.** Check the clip's caption page count and the selected preset. Captions are burned from generated pages; a clip with no words has nothing to burn. Re-run analysis, or supply `subtitle_path` through the API after clearing the transcript artifact (the UI has no subtitle picker).

**The render is slow.** One worker, H.264 encoding and a full source decode are the cost. Hardware encoding is used when the build exposes working NVENC or AMF, but the app retries with `libx264` if the hardware path fails. A retry is slower, not stuck.

**The render looks identical after a change.** The MP4 is cached by clip, preset, framing and caption-page digest. Changing the trim, preset, framing or caption pages produces a different key; if the panel still shows an old result, press **Render again** to force it. A hook edit alone does not invalidate the cache because the hook is not burned into the picture.

**I expected the hook in the MP4.** It is not burned in. The hook appears in the monitor overlay and travels in the OTIO marker, EDL comment and manifest. Add it as a title in your editor if you want it on screen.

**The crop misses the speaker.** Auto framing uses motion and skin density until the face tier is installed: `pip install -r requirements-optional.txt` for OpenCV, then download **Face tracking (YuNet)** in Models. Even then it follows one subject per shot and can be wrong on a wide shot, an animated overlay or a dark scene. Press **Inspect framing** in the render panel to see the crop path before spending a render; `GET /api/framing/status` says whether faces are in use and what is missing. Use `crop` or `blur` framing, or fix the shot in the editor.

**The video is black or will not play.** Re-render with force. If it persists, check the encoder reported on the job; a broken hardware encode can produce an unplayable file, and the app's retry should have produced an H.264 fallback. If not, force a fresh render and report the encoder and ffmpeg stderr.

## Export

**Media is offline after import.** Exports reference absolute paths and do not copy media. Import into the NLE on the same machine, or relink to the same files at their original paths.

**The NLE will not open the zip.** Unzip the bundle first. Import `reel.otio`, `reel.xml` or `reel.fcpxml`; the zip is a delivery container, not a project file. Final Cut Pro 10.6.8+ takes `reel.fcpxml`.

**Timecode drifts at 29.97.** Timecode is non-drop-frame. The app does not offer drop-frame; use the NLE's interpretation deliberately.

**The EDL is missing something.** EDL is the lowest-fidelity format: cuts and comments, no complex reframing or transitions. Use OTIO, FCP7 XML or FCP X XML for a fuller handoff.

**No clips export.** Export includes ranked clips, not approved-only clips, but a source with no ranked candidates returns 409. Analyze first.

## Accounts, publishing and learning

**Connect is greyed out, or the tab says "Secure storage unavailable".** The OS
credential store could not be opened, so the app refuses to store a token rather
than writing one to disk. `GET /api/accounts` reports the reason under
`secret_store.detail`. On Linux that usually means no Secret Service
(gnome-keyring, KWallet or `pass`) in the session; on Windows, a policy that
blocks Credential Manager. For development only, `CLIPPER_SECRET_BACKEND=memory`
keeps tokens in RAM, and they are gone after a restart.

**The consent page ends on "Connection failed".** The code expired (ten minutes)
or the redirect did not match exactly. Start **Connect** again; the URI registered
with the provider has to be the copy in the Accounts tab, port included.

**The provider says `redirect_uri_mismatch` or rejects the client secret.** Google
needs a **Web application** client with the callback above and both ID and secret;
X needs a **confidential** OAuth 2.0 client, not a public/native one. Paste the
secret again — a trailing space is enough to fail.

**Sync returns 401.** The token was revoked or expired at the provider. Disconnect
and connect again; nothing else changes.

**Sync returns 502, or X says the rate limit was reached.** The payload carries the
platform's own message and an error code. X limits are per app per window; the
weekly loop or a later **Sync** will catch up. A 403 usually means a missing scope
or a plan that does not allow the call.

**Posts are listed but nothing gets labelled.** A post settles after 24 hours and
50 views, and an account needs 8 eligible posts before its median can split them
into wins and misses. Until then every pill says **settling**, which is also what
"No posts captured yet" means before the first Sync.

**The performance model never goes live.** It needs 30 posts that carry clip
features, at least 10 wins and 10 misses, an AUC 0.03 above a reach-only baseline
and p < 0.05 on a 200-permutation test. Channel history has no features, so it can
raise the baseline but never train the model. The history list shows each
attempt's numbers, including a failed gate.

**A model version never becomes active.** It failed its gate, and a failed attempt
cannot be activated by hand — the API answers 409. Retrain once more posts have
settled. A 409 on `retry` is different: that upload is still running, or already
published.

**The weekly run did not happen.** The daemon lives in the app: it checks 20
seconds after launch and then hourly, and runs when seven days have passed.
`GET /api/learning/weekly` shows `last_run`, `next_run` and `due`;
`CLIPPER_DISABLE_WEEKLY=1` turns it off. **Sync and retrain now** always runs.

**Disconnect left the app's access at the provider.** The app removes the local
token first and then asks the provider to revoke it; if revocation failed (or
`CLIPPER_DISABLE_REVOKE=1` is set), remove the app from the provider's account
settings. The app no longer holds the token either way.

**The Coach tab shows nothing.** No rule fired, which is normal on a clean clip.
Suggestions are rules over the transcript, gates and signals, so a bad transcript
produces poor ones; fix or re-import it before trusting the coach.

## Themes and layout

**A theme file will not import.** It must be JSON with all nine seed colours. Unknown fields are discarded; a missing seed is a hard error. An optional font stylesheet must be HTTPS or it is ignored.

**A custom theme's fonts do not load.** The font families must be installed locally or supplied by an HTTPS stylesheet in the theme. The stack falls back if neither is available; that is not a save failure.

**A theme is gone in another browser.** Themes live in `localStorage`, not on the server. Export the JSON and import it there. Clearing site data also removes them.

**Contrast warnings appear on a theme I like.** They are advisory WCAG checks, not a block. Low-contrast focus rings and muted labels are still real usability problems; adjust the seed rather than ignoring the warning.

**The monitor stays dark in a light theme.** Intentional. Video is judged against a stable neutral stage, not the room's paper colour.

**A panel disappeared.** Press `Ctrl+B` for the inspector; at narrow widths it becomes a drawer and `Esc` closes it. The three areas are always in the rail (`Ctrl+1` / `Ctrl+2` / `Ctrl+3`). If the layout is mangled, use **Edit → Reset layout**.

**Shortcuts stop working while typing.** By design: the global handler defers to inputs, textareas and dialogs. Click out of the field, then use the shortcut.

**Clipboard sharing did nothing.** The browser blocked clipboard access. The theme is downloaded as a file instead; use Import on the other machine.

## Data and recovery

**Where is my library?** `GET /api/health` returns the exact `data_dir`. The default is `%APPDATA%/ClipFactory` on Windows and `$XDG_DATA_HOME/ClipFactory` otherwise. The Electron shell uses its own `userData` folder.

**The database is locked.** More than one backend is using the same data directory. Stop the extra process. Do not run two servers against one library.

**I moved a source file.** The database still has the old absolute path. Re-import the file at its new path. The old source entry remains; there is no delete control in the UI or API.

**I need a clean library.** Stop the app, then rename the data directory rather than deleting it. Renaming is reversible and preserves the old database, media and renders. Start the app again to create a fresh directory. Do not do this to a directory you have not confirmed from `/api/health`.

**A job vanished after restart.** Jobs are in memory. Completed analyses and renders are on disk; the queue is not. Re-run the operation.

## Reporting a problem

Include:

- the exact error text and the surface where it appeared;
- the Clip Factory version from `GET /api/health`, or the whole `GET /api/diagnostics` snapshot (versions, paths, sizes, disk free);
- the job JSON from `GET /api/jobs/{id}`, if a job failed;
- the output of `GET /api/ffmpeg` for caption or encoder problems;
- whether models are installed and active;
- the operating system and whether you used the browser or Electron.

Do not attach a private source video, transcript or chat dump unless you intend to share it. The logs do not require the media to diagnose an API or ffmpeg failure.

---

Next: [Limitations](Limitations.md).

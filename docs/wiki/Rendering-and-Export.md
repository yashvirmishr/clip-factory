# Rendering and Export

Rendering makes the vertical master inside Clip Factory. Export hands the reel to another editor with the cuts, hooks and captions intact. They are separate operations: a render is a finished MP4, an export is an editable timeline.

## Before you render

1. Trim the clip and save the hook.
2. Check the **Captions** tab for page warnings.
3. Review the frame in the Monitor with the 9:16 guides on.
4. Confirm the source is on a disk that will still be connected while ffmpeg runs.

Only one background job runs at a time. Rendering is queued behind an analysis and blocks another render until it finishes; an upload uses the same worker, so a publish in front of a render delays it too.

## The render

Open **Output** in the Inspector. The render section shows the delivery size, a caption preset, a framing strategy and the encoder once a render exists. Once a file is rendered, the same tab carries the **Publish** section for sending it to YouTube or X; see [Publishing](Publishing.md).

### Caption presets

| Preset | Look |
|---|---|
| **Hormozi** | Heavy Arial Black, large uppercase words with a dark outline; warm white fills to tungsten as each word is spoken. The default. |
| **Box** | Heavy uppercase type in a translucent dark box with no outline; the most legible on busy footage |
| **Karaoke** | Heavier type with a yellow-green sweep fill across each word |
| **Minimal** | Smaller Segoe UI Semibold, sentence case, quiet outline, less visual weight |
| **Landscape** | Smaller sentence-case type with a tighter bottom margin for wide source framing |

A preset is a starting point. The **Captions** tab's subtitle studio changes the font, size, colours, outline, bottom margin, case and word animation for one clip, with a live preview drawn from the same numbers the renderer uses. Only the fields you change are stored, so the rest keeps following the preset, and **Reset** returns to it. Presets live in `backend/clipper/render/ass.py`; per-clip changes live in the clip's `caption_style` edit and travel into the render, the ASS download and the bundle. Colours do not follow the interface theme.

One caveat: the studio styles what the renderer can burn (font, size, colours, outline, margin, animation). It is not a subtitle timeline editor; the words themselves are edited as pages.

The font, size and karaoke mode are shown in the preset tooltip. If the preset service is unavailable, the panel falls back to Hormozi and says so.

Caption pages themselves are grouped elsewhere: at most four words, 22 characters per line, two lines and a 19 characters-per-second ceiling, with a minimum page duration and a split on speech gaps. Those limits are in `CaptionConfig` and are reflected in the warnings on the Captions tab.

### Framing

| Mode | Behaviour |
|---|---|
| **Auto** | Builds a subject-aware 9:16 column, one crop position per shot, with a measured confidence. Falls back to a centred crop when no plan is usable. |
| **Blur pad** | Fits the whole frame inside the vertical canvas over a blurred fill. Nothing is cropped. |
| **Crop** | Centre-crops to fill the canvas. No tracking. |

Auto works in two tiers. By default it measures motion and skin density on a small grid, then pans linearly between shot centres. Install the face tier (`pip install -r requirements-optional.txt` and **Face tracking (YuNet)** in Models; an explicit `framing.face_model` also works) and it instead tracks faces at 4 fps, picks the largest speaking face in each shot and follows it — still one position per shot, smoothed by a deadband so a wobbling face does not become a handheld camera. When faces cannot be tracked because the package or model is missing, the motion tracker answers, and the render panel says which one is in use; **Inspect framing** draws the planned crop before you spend a render. Nothing in the default path imports OpenCV.

Both tiers are deliberately one decision per shot rather than a per-frame follow, which would wobble on every gesture.

### What ffmpeg does

A render is one ffmpeg command:

- seek to the in-point and cut the clip duration;
- build the 1080 × 1920 frame with the chosen framing;
- burn the ASS captions with libass;
- normalise audio to -14 LUFS with a -1.5 dB true-peak ceiling, AAC 192 kbit/s at 48 kHz;
- encode H.264 with `libx264`, or with a hardware encoder only after a test encode passed;
- write a fast-start MP4.

NVENC and AMF are probed and tested. If a hardware encoder disappears or fails during the real encode, the render retries once with `libx264` rather than failing. The encoder chip on a finished render reports which path was used.

### Caching

Renders are cached under the local `renders/` directory. The key includes the clip, caption preset, resolved framing and a digest of the caption pages. Changing the trim or captions produces a different file; pressing **Render again** forces a fresh pass even when a cached file exists.

Changing the hook does not invalidate the MP4, because the hook is not burned into the picture. It is metadata and monitor overlay, not a video layer.

When a render completes, the panel shows the preview, filename, duration, pages, encoder and a download link. **Open** opens the MP4 in the system player.

## Export

The **Handoff** section in Output offers four downloads. They are generated on demand from the current ranked reel.

| Format | File | Use |
|---|---|---|
| **Bundle** | `.zip` | Everything below plus a manifest and any matching renders |
| **OTIO** | `.otio` | Resolve, Premiere with the OTIO adapter, FilmCraft |
| **FCP X (FCPXML 1.10)** | `.fcpxml` | Final Cut Pro X, and Resolve |
| **FCP7 XML** | `.xml` | Native import in Premiere and Resolve |
| **EDL** | `.edl` | CMX 3600 universal fallback; no media, no captions |

The bundle contains:

```text
reel.otio
reel.xml
reel.edl
README.txt
manifest.json
captions/<clip-id>.srt
render/<clip-id>-...mp4   (when a matching render exists)
```

The API can also return a single merged `.srt`; the Output panel does not expose that button.

### Which clips

Export uses **every ranked clip** in the source, in rank order. **Approved clips only** narrows it to clips whose latest decision is approve — the same switch applies to the reel-wide caption zip and to a bake.

The default is the whole reel: the editor needs the evidence, not a hidden subset. Because that is also the most common surprise in the app, the clip count is on the header of the Handoff section.

### Media and timecode

The timeline references source media by absolute path. Nothing is copied into the zip. If the source moves, the import shows an offline clip; relink it to the same path and the cut survives. A two-hour VOD inside a zip would be useless as an attachment.

Every format gets its timecodes from the same functions, at the source frame rate. Timecode is non-drop-frame: 29.97 counts at 30 fps and 23.976 at 24 fps. For short clips this is within a frame of the clock and avoids a half-correct drop-frame implementation. Long-form drop-frame workflows are not supported.

Hooks appear as clip names, OTIO markers, FCPXML markers, FCP7 XML markers and EDL comments, not as burned-in text. Captions appear as SRT and VTT files next to the timeline, not as a separate subtitle track inside the XML.

## Caption files on their own

Every clip's caption pages can be downloaded without exporting a timeline: **SRT**, **VTT** or **ASS**. The reel-wide download is a zip with one file per clip. SRT/VTT/ASS are built from the same pages the renderer burns, so editing them in your NLE cannot drift from what the preview showed.

ASS keeps the styling (font, size, outline, karaoke timing) that SRT and VTT cannot express.

## Reframing does not survive a timeline export

An animated crop is written into the rendered file, not into the XML. Premiere, Resolve and Final Cut each express a moving crop differently and none of them agree, so the handoff timeline references the source as-is. If you need the reframed picture in the editor, render the clips and hand over the renders.

### Import advice

Try OTIO first, then FCP X XML (Final Cut Pro 10.6.8+), then FCP7 XML, then EDL. This is the order the bundle README recommends. None of these formats is a guarantee on every NLE version; import one test reel before committing to a delivery workflow.

## Baking the reel

**Finished files** in the Handoff section renders every selected clip at 1080 × 1920 with its captions burned in, and collects the results in one folder:

```text
<data dir>/exports/<source-id>/
  01 <hook>.mp4
  02 <hook>.mp4
  captions/01 <hook>.srt
  manifest.json
  README.txt
```

This is the no-editor path: nothing needs importing afterwards. Renders are reused from the render cache and hard-linked into the folder where the filesystem allows it, so a bake is not a second, slower renderer and does not double the disk use. A bake replaces the previous folder for that source, because a stale MP4 beside a fresh manifest is worse than no export at all. One clip failing to render is recorded in `manifest.json` and the rest of the reel still bakes.

## Rendered-file locations

Rendered MP4s live in the data directory under `renders/`, and are served from `/api/renders/<filename>`. Baked clips live under `exports/<source-id>/` and are served from `/api/sources/<id>/export/bake/file/<name>`. Export downloads are generated in memory and streamed; they are not stored as files.

---

Next: [Themes](Themes.md).

# Reviewing Clips

Analysis produces a ranked reel; reviewing turns it into a decision. This page explains where the clips come from, what every number means, and which controls change the cut.

## What analysis does

The header reports five stages. They run in order, in one background job.

| Stage | Work |
|---|---|
| **Audio** | Probe the source, extract a mono analysis track, build the peak pyramid |
| **Transcribe** | Run whisper.cpp, read an imported SRT/VTT, or use the deterministic stub; align words to the audio |
| **Signals** | Compute loudness, speech density, hook-lexicon hits, scene cuts, chat rate and fused windows |
| **Score** | Build sentence-bounded candidates, run the gates, score a shortlist with the LLM or the labelled stub |
| **Select** | Remove overlaps and near-duplicates, rank the survivors, store the reel |

Subtitle import is backend-only: `POST /api/sources/{id}/analyze` accepts a `subtitle_path`, and whisper is preferred when it is available. There is no subtitle picker in the UI.

You can close the tab while this runs. The job is server-side; reopen the source to see its state. Only one job runs at a time.

## The reel

The **Clips** tab is the main reviewing surface; the ranked set it draws is the reel.

- **Filters:** All, Approved, Rejected, Unreviewed. The counts are live.
- **Search:** filters by hook text, transcript or the judge's reason.
- **Sort:** rank, score or duration. Score and duration run high-to-low; rank runs first-to-last.
- **View:** list or grid. List shows more evidence per row; grid shows more clips at once.
- **Selection:** click a card to select it. Double-click to open it on the monitor.
- **Verdicts:** the approve and reject buttons on the card, the Inspector or the Monitor all update the same state.

Rejected cards stay in the reel, dimmed and marked, so a rejection never hides the evidence that produced it. Use the All filter to bring them back.

### Rejection reasons

Rejecting opens a reason bar: **boring**, **confusing**, **cut off**, **spoiler**, **off topic**, **duplicate**, or **Skip** for an unspecified reason. The reason is stored with the decision and used by the learning loop. `Esc` cancels the bar.

## Reading a clip

### The score hero

The Inspector opens with the final score and the judge's reason.

| Value | Meaning |
|---|---|
| **Final score** | The ranked score after fusion and model judgement |
| **fused** | The deterministic signal score on a 0–100 scale |
| **model** | The LLM or stub score, when one was recorded |
| **provider chip** | The recorded provider: `llama-server`, `heuristic-stub`, or a `llama-server-failed` / `llama-server-invalid` fallback |

The final score is a review order, not a promise. A clip can score well and still be wrong for your audience; that is what the reject reason is for.

### Signals

Three bars explain the deterministic side:

- **Audio** — loudness, speech activity and prosody relative to the rest of the source.
- **Chat** — message rate around the moment. It is zero when no chat replay was imported.
- **Hook** — density of hook-like phrasing in the window.

Below the bars are duration, word count, words per second and speech coverage. These are facts about the candidate, not quality judgements.

### Scorecard

The scorecard is the visible answer to "is this clip broken?". It has eight checks:

1. Opens on a sentence
2. Ends on a sentence
3. Hook lands in the first seconds
4. Hook is grounded in the clip
5. Duration is in range
6. Clip stands alone without prior context
7. ASR confidence is sufficient
8. Hook is readable

Each check shows pass or fail and the reason. **Clip quality** in Insights is the average scorecard pass ratio across the ranked clips. It measures structural cleanliness, not how entertaining the reel is.

Gates are the same checks used during selection. A clip that fails a gate can still be present in the reel if it was the best available candidate; the failure is shown, not hidden. Selection prefers clips that pass.

### Clip facts

The editor window shows the transcript around the clip: the lines before and after make it obvious whether the clip starts mid-thought. Words outside the cut are marked, so you can see what the audience will miss.

## Changing the cut

### Hook

The hook is the on-screen text for the first three seconds. It is editable on any scored clip.

- Type a new hook and press **Enter**, or click **Save hook**. **Shift+Enter** adds a line.
- **Escape** restores the saved hook without writing.
- The word count is shown while editing.
- The scorecard expects a readable hook of 1–12 words, and at least 70% of its words should appear in the clip. A hook wider than the evidence will fail **Hook is grounded**.

A saved hook is carried into the monitor overlay and into every export as clip metadata, a timeline marker or an EDL comment. It is not burned into the MP4.

### Trim

Open **Trim** in Properties to adjust the in and out points.

- Nudge either edge by 0.5 seconds, or type an exact time.
- **Show** seeks the monitor to that edge.
- The editor permits 5–90 seconds. The server enforces a 5-second minimum and clamps to the source bounds; it does not impose the 90-second ceiling.
- **Apply trim** updates the clip, its captions and the timeline. **Reset** restores the current saved points; it does not undo an already-applied trim.

Trimming keeps the clip inside its source and re-derives caption pages and gates for the new range.

### Captions

The **Captions** tab is a read-only proof of the page layout: time range, lines, characters per second, line budget and warnings. It is deliberately read-only in the interface; the API and stored caption pages are the source of truth. See [Rendering and Export](Rendering-and-Export.md) for how those pages become burned-in text.

### Coach

The **Coach** tab proposes fixes and shows the evidence for each one: trim dead air at the start, tighten or rewrite a slow hook, cut a mid-sentence ending, shorten an overlong clip, add a payoff, raise speech density, recheck a low-confidence transcript, or thin out crowded captions.

**Preview** shows the before and after without touching the clip. **Apply** makes the change for real: trims go through the same path as the Trim control, hook rewrites are saved as an ordinary hook edit. Both keep the old value, so **Undo** restores it; **Dismiss** hides a suggestion without changing anything. The coach never renders or publishes. See [Learning from your posts](Learning.md#coaching-suggestions) for the full list.

## The monitor

The Monitor is the colour-critical view. Use the **Hook**, **Captions** and **No overlay** buttons to switch overlays, and the switches for loop and 9:16 guides.

The transport supports play/pause, one-second and five-second jumps, frame stepping, mute, volume and playback speed. **Fullscreen** gives the frame the whole display. Approve and reject sit directly under the preview so a review pass does not require moving to the Inspector.

Playback speed defaults to 1×. Slow speeds are useful for checking caption timing; they do not affect the render.

## The timeline

The Timeline tab lays the whole source out as an audio envelope with ranked clip blocks on up to two lanes. Blocks are coloured by verdict. Click a block to select it and seek to its start; double-click to open it on the monitor. Drag anywhere on the timeline to scrub, use the zoom controls or **Fit** to change scale, and use the arrow keys (Shift for five seconds) when the ruler has focus. The playhead and monitor stay in sync.

It is a reading surface, not a multi-track editor. It does not draw scene cuts, caption blocks or gate markers.

## A review pass that stays honest

1. Filter to **Unreviewed**.
2. Read the hook and the judge's reason before playing the clip.
3. Play from the in-point; check that the first sentence makes sense without the previous line.
4. Check the scorecard for structural failures. If one matters to this audience, reject with a reason rather than fixing a bad candidate.
5. Approve only after the hook and caption pages look publishable.
6. Reject with a reason when the clip is boring, confusing, cut off, a spoiler, off topic or a duplicate. Unspecified rejections teach the re-ranker less.
7. Review the approved set once more with the **Approved** filter before rendering.

## What the app learns

Every verdict is appended to a local decision log. The Insights panel reports progress toward the 40-decision threshold, the label balance and the re-ranker gate. Once there is enough data, Clip Factory trains a personal re-ranker, keeps a held-out check, and uses the result only if it beats the base ordering by the required margin. The same log produces a style profile and few-shot memory for future analysis.

Nothing is uploaded. The log lives in the local data directory and can be exported as JSONL from Insights.

That learner reads your approvals. A second, separately gated model reads your audience: posts published from connected accounts are synced with their engagement. It is documented in [Learning from your posts](Learning.md), together with the weekly schedule that retrains it.

---

Next: [Rendering and Export](Rendering-and-Export.md).

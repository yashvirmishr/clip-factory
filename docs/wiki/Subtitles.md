# Subtitles

Captions are generated from the transcript, burned into the render, and downloadable as files. All three come from the same pages, so they cannot disagree.

## Where captions come from

The transcript's word timings are grouped into pages: a few words at a time, split on sentence ends, sized to fit the line budget. Manual edits in the inspector replace the grouping for that clip; **Reset** returns to the generated pages.

## Downloading them

In the inspector's **Output** tab, each clip can be downloaded as:

| Format | Use it for |
|---|---|
| **SRT** | Every editor, YouTube uploads, anything that reads subtitles |
| **VTT** | Web players, and the format caption tracks download as |
| **ASS** | Keeping the styling: font, size, outline, karaoke timing |

With no clip selected, the same buttons download a zip with one file per clip in rank order. **ASS** keeps the burned-in look; SRT and VTT are plain text on purpose.

## What the render burns

Five presets ship: Hormozi, Box, Karaoke, Minimal and Landscape. Each fixes a font, a size, colours, an outline, margins and whether words are uppercased. Karaoke presets highlight each word as it is spoken.

Colours, fonts and margins come from the theme and the preset, not from the caption text, so changing theme does not change the subtitle file.

## Styling one clip

The **Captions** tab opens the subtitle studio. Pick a preset, then change what this clip needs:

- **Font**, from the families installed on this machine.
- **Size**, **outline** and **height** (how far the captions sit from the bottom).
- **Colours** for the spoken word and the words still to come.
- **Words animate**: instant pop, sweep, or static text.
- **UPPER**, for presets that do not uppercase already.

The preview is drawn from the same numbers the renderer uses, so a size that looks wrong there is wrong in the MP4. **Save style** stores only what you changed — the rest keeps following the preset, and **Reset** goes back to it. The preset you pick is remembered between the studio and the render panel, so the two cannot disagree.

Saved changes follow the clip into the render, the downloadable ASS, and the bundle's caption files.

## Languages

Line wrapping counts display width, not characters, so wide glyphs wrap where they should. Fonts are picked per script when the preset's font cannot draw the text. Uppercase styling is skipped for scripts without case (Chinese, Japanese, Korean, Arabic, Hebrew, Hindi and the other Indic scripts).

See [Languages](Languages.md) for what needs a multilingual speech model.

## Limits

- Per-clip styling covers font, size, colours, outline, margins and animation; placement is bottom-centre only, and alignment is not exposed.
- No karaoke timing export in SRT or VTT; those formats have no per-word markup.
- Burned captions cannot be removed from a finished file — re-render instead.

# Clip Factory themes

Clip Factory themes are portable JSON recipes. A theme supplies **nine colour seeds**
and a few typography choices; the app derives every surface, hairline, focus ring,
monitor tone and timeline colour from them. There is no build step and no CSS to
write.

Open **Appearance → Theme atelier** from the palette swatch in the status bar.

## Make a theme in the app

1. Open the theme atelier and choose **Studio**.
2. Start from **New**, **Remix** a built-in theme, or **Edit** one of your own.
3. Change any seed. The preview updates immediately and the draft autosaves in this
   browser.
4. Use the readability checks to keep body text at WCAG AA (4.5:1) or better.
5. **Use this theme** applies it. **Export** downloads the portable JSON.
6. **Import** accepts an exported file or the starter template below.

Opening Studio is side-effect free: a draft appears locally, and is only stored
after the first edit or when you choose **Use this theme**. Deleting a saved custom
theme restores the default room if it was active.

## Theme file

```json
{
  "format": "clip-factory.theme",
  "version": 1,
  "theme": {
    "name": "My room",
    "author": "Your name",
    "description": "One sentence about the mood.",
    "scheme": "light",
    "tags": ["Warm", "Editorial"],
    "seeds": {
      "canvas": "#f2eadc",
      "surface": "#fffaf0",
      "ink": "#1d2824",
      "accent": "#0b6b62",
      "stage": "#0b1211",
      "stageInk": "#e9f2ec",
      "ok": "#2f7d4f",
      "warn": "#9a6b12",
      "danger": "#b14436"
    },
    "fonts": {
      "ui": "'Familjen Grotesk', system-ui, sans-serif",
      "display": "'Instrument Serif', Georgia, serif",
      "mono": "'DM Mono', ui-monospace, monospace"
    },
    "radius": 3
  }
}
```

`format` and `version` are an envelope for sharing. The importer also accepts a
bare theme object. `id` is optional on import; Clip Factory assigns a local
`custom-…` id so a shared file cannot overwrite a theme you already have.

## Seeds

| Seed | Drives |
| --- | --- |
| `canvas` | App background, timeline bed, empty space. |
| `surface` | Panels, inspector, menus and cards. |
| `ink` | Body text, headings and all hairlines. |
| `accent` | Selection, primary actions, focus, active tabs and score marks. |
| `stage` | The video monitor. Keep this dark and neutral for colour judgement. |
| `stageInk` | Monitor labels, timecode and transport icons. |
| `ok` | Approved states, success toasts and healthy signals. |
| `warn` | Warnings, low-confidence marks and caution states. |
| `danger` | Rejections, destructive actions and errors. |

All seeds must be `#rgb` or `#rrggbb` HEX values. The app mixes them into panel
tones, hover surfaces, soft tints and alpha lines; you do not need to supply every
shade.

## Typography and shape

- `fonts.ui` — panels, controls and body copy. Always include a generic fallback.
- `fonts.display` — the serif workspace titles and dialog headlines.
- `fonts.mono` — scores, timecodes, numeric fields and the timeline ruler.
- `fonts.stylesheet` — optional HTTPS stylesheet URL (for example a Google Fonts
  CSS URL). It is ignored unless it starts with `https://`.
- `radius` — `0`–`12` pixels, stored in half-pixel steps. `0` is sharp and technical;
  `2`–`4` is the house default; higher values read softer.

Keep the monitor (`stage`) dark in light themes. It is the one surface that should
not follow the paper colour: it is where you judge the video.

## Accessibility

Aim for at least 4.5:1 for normal text and 3:1 for large display type. The Studio
reports ink-on-canvas, ink-on-surface, monitor labels and accent text. Muted labels
are derived from `ink` and `canvas`, so a strong ink/canvas pair carries through the
whole workspace.

## Starter file

Download [`web/public/themes/starter.json`](../web/public/themes/starter.json) and
edit it, or press **Export** in Studio to use a theme you already like as the
starting point.

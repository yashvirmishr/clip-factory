# The Workspace

Clip Factory uses the shape of a professional editing application: a project bin on the left, a working stage in the centre, a context-sensitive inspector on the right, and a status rail along the bottom. The difference is that every panel is ranked around review, not around an empty timeline.

![Triage workspace with Project, Clips and Inspector](images/workspace-reel.png)

## The shell

### Menu bar

**File**, **Edit**, **View**, **Clip**, **Workspace** and **Help** contain the main application commands. Commands that depend on a selection disable themselves instead of failing after a click. **Help → Take the tour** replays the first-run walkthrough from anywhere.

The right side of the bar has the **Command** button and the keyboard-shortcut button. The command palette is the fastest way to find a command you have not memorised.

### Context bar

The strip below the menu bar shows the three workspace presets, the current source and its format, the active engines, and actions for re-analysis, the export bundle and hardware/models.

| Preset | Shape |
|---|---|
| **Triage** | Project panel and Inspector open, Clips in the centre. The reviewing layout. |
| **Editing** | Monitor in the centre, captions on, 9:16 guides and loop on. The finishing layout. |
| **Review** | Both side panels stowed, Monitor in the centre. The cleanest view of the frame. |

Switching presets changes panel visibility and monitor settings; it does not overwrite your clip verdicts. Your current layout is stored separately.

### Project panel

The left panel is the source bin.

- **Sources** lists every imported source with duration, size, analyzed state and clip count. Select a source to load its analysis. The filter field narrows the list.
- **Insights** holds pipeline warnings, backend telemetry, clip quality, the learning summary and the hardware/models entry point.
- **Accounts** connects YouTube and X, shows each account's posts and baseline, and hosts **Sync** and **Sync and retrain now**. See [Learning from your posts](Learning.md).
- **Add a source** accepts a local path or an HTTP(S) VOD URL. **Demo stream** generates a self-contained test source.
- The footer opens **Hardware & models** and shows the local-first status.

Use the collapse control in the panel header or `Ctrl+B` to stow it. The status bar also has a panel toggle.

### Working area

The centre has three tabs:

| Tab | Purpose |
|---|---|
| **Clips** | The ranked reel: filters, search, list/grid views, approve and reject actions |
| **Monitor** | Source preview, hook and caption overlays, 9:16 guides, transport and clip actions |
| **Timeline** | The source audio envelope, ranked clip blocks and playhead; click to select, double-click for the monitor |

Switch with `1`, `2`, `3`, or by clicking a tab. The tab counts update as clips are reviewed.

### Inspector

The right panel is always about the current clip. It has four sections:

| Tab | Contents |
|---|---|
| **Properties** | Final score, hook editor, signal bars, clip facts, quality scorecard, gates, trim, transcript window |
| **Captions** | Caption pages with timings, characters per second, line layout and warnings |
| **Coach** | Evidence-backed suggestions, each with preview, apply and undo |
| **Output** | Caption preset, framing, render action, rendered preview, handoff formats |

Collapse it with `Ctrl+Shift+B`. The **View** menu can float it instead.

### Status bar

The bottom rail reports the current activity, the selected source and clip, the active theme, the workspace and the panel toggles. The theme swatch is also the entry point to the theme atelier.

## Panels that behave like panels

- Drag the vertical splitters to resize the Project and Inspector. The widths persist.
- Collapse either side panel without losing its state.
- **View → Float inspector** detaches the Inspector into a movable window. Drag its title bar, resize from the lower-right corner, double-click the bar or use the dock button to return it.
- **Workspace → Reset workspace** restores the default layout.
- Layout, tab choices, filters, sort order, view mode and monitor settings are saved to `localStorage` under `clip-factory.workspace.v2`.
- Themes have their own store under `clip-factory.theme.v1`.

At narrow widths the shell compacts around the stage. Panels remain reachable from the status bar and the View menu; the Inspector can float over the stage rather than squeezing it.

## Commands and menus

Every menu command is also a palette command. **Ctrl/Cmd+K** opens the palette, type a few letters, and press Enter. Results are grouped by File, Edit, View, Clip, Workspace and Help.

Right-click a clip card for its context menu: select, open on the monitor, approve, reject, render, copy the hook or copy the timecode. The same commands appear in the **Clip** menu.

## Keyboard shortcuts

Shortcuts are ignored while you are typing in a hook, trim or search field.

### Workspace

| Action | Keys |
|---|---|
| Command palette | `Ctrl/Cmd+K` |
| Toggle Project panel | `Ctrl/Cmd+B` |
| Toggle Inspector | `Ctrl/Cmd+Shift+B` |
| Clips / Monitor / Timeline | `1` / `2` / `3` |
| Shortcut reference | `?` |

### Review

| Action | Keys |
|---|---|
| Next / previous clip | `J` / `K` |
| Approve selected clip | `A` |
| Reject selected clip | `X` |
| Render selected clip | `R` |
| Dismiss the rejection bar | `Esc` |

### Monitor

| Action | Keys |
|---|---|
| Play / pause | `Space` |
| Step one second | `←` / `→` |
| Step five seconds | `Shift+←` / `Shift+→` |
| Step one frame | `,` / `.` |
| Loop selected clip | `L` |

## Themes

Open the theme atelier from the swatch in the status bar or **View → Theme atelier**. The Marketplace applies a theme immediately; the Studio edits one with a live preview. Built-in themes cover light, dark and neutral rooms, and custom themes are stored locally.

See [Themes](Themes.md) for the interface and the theme file format.

## What is intentionally not here

There is no track stack, keyframe editor, effects panel or timeline trimming surface. The timeline is for reading the selected clip, not for building a multi-track sequence. Finishing belongs in the render flow or in the editor you hand the project to.

---

Next: [Reviewing Clips](Reviewing-Clips.md).

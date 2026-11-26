# Glossary

Plain words for the things this app does.

**Clip** — one short vertical video cut from a longer source.

**Source** — the long video you add.

**Analysis** — the pass that reads the speech, finds moments, checks them and
scores them.

**Check** — a rule a moment must pass to become a clip: enough speech, no
sponsor read, ends on a sentence. A failed check either stops the clip or flags
it.

**What it noticed** — the signals behind a score: a question, a number, a laugh,
a hook in the first seconds.

**Hook** — the first spoken line of a clip, the thing that decides whether
someone keeps watching.

**Ranking** — ordering clips by how likely they are to hold attention. Uses the
built-in rules, or a local model runner if one is set.

**Model runner** — a llama-server you run yourself. The app never starts it.

**Speech model** — the file that turns audio into words.

**whisper-cli** — the small program that runs the speech model.

**Render** — write the final vertical MP4 with captions burned in.

**Export bundle** — a folder of clips, captions and a timeline file for another
editor.

**Theme studio** — where colours and type are chosen.

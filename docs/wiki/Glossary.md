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

**Connected account** — a YouTube or X account you authorised once, so Clip
Factory can read its posts and, if you ask, publish. The token lives in the
operating system's credential store, not in the database.

**Engagement rate** — the weighted reactions on a post divided by its views:
likes, comments, shares and saves, not raw view count. It is the label the
performance model learns from.

**Settling** — a post younger than 24 hours or below 50 views. Its numbers are
still moving, so it is not labelled yet.

**Performance model** — a small model trained on your published posts, and
whether their engagement beat the account's median. It only goes live if it
beats a reach-only baseline on data it never trained on.

**Coach** — suggestions for a clip, each with the evidence that produced it.
Every fix is previewed before it is applied and can be undone.

**Theme studio** — where colours and type are chosen.

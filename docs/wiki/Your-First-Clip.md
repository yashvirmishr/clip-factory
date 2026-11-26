# Your first clip

The first run takes about four minutes. The app walks through the same steps as
a tour, and every step can be skipped.

## 1. One long video in

Open the **Library** area. Press **Add source** for a file or a link, or press
**Demo stream**. The demo is a real video that needs no models, so it is the
fastest way to see the whole shape of the app.

## 2. Is this computer ready?

Three checks, and two usually already pass:

- **Video tools** — ffmpeg. Without it nothing can be cut.
- **Reading speech** — a speech model plus the small program that runs it.
  Skip it and clips are cut from a stand-in transcript: usable, but the words
  will not match.
- **Judging clips** — a ranking model runner. Optional. The built-in rules work.

Nothing here blocks you. Press **Continue** and fix what you like later, from
**Help → This computer**.

## 3. Let it watch the whole thing

Open **Clips** and press **Analyze** in the header. The status bar names the current step in plain words:
Listening, Reading speech, Finding moments, Scoring, Picking clips. A four-minute
video takes under a minute on a laptop.

## 4. Read what it found

The **Clips** area lists what it kept. Each card shows the hook, what the model
noticed, and the score. Open one to see the full picture in the inspector.

## 5. You get the last word

**Approve** what you would post. **Reject** what you would not, and pick a reason.
Every rejection teaches the ranking, so the next analysis lands closer to your
taste. Nothing is deleted.

## 6. Make the file

**Render** writes a vertical MP4 with burned-in captions next to your project.
**Export bundle** is for taking the edit into another editor.

## If something is wrong

- **No speech model:** clips still appear, from a stand-in transcript. Setup says
  so, and so does the inspector.
- **No ffmpeg:** analysis can run, but cutting and rendering cannot. Install it,
  then press **Check again**.
- **Model runner unreachable:** scoring falls back to the built-in rules. The
  address box in **Help → This computer** tells you whether it can see a runner.

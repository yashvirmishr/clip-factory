# Learning from your posts

Clip Factory can learn from what actually happened after you published. The loop stays local: it reads your own connected accounts through their official APIs, stores the numbers in SQLite, and never scrapes a logged-in session or posts on your behalf.

## Connect the accounts you publish from

Open **Project → Accounts**. YouTube and X are the platforms with both an upload adapter and an analytics adapter today.

| Platform | What is pulled |
|---|---|
| YouTube | Your uploads with views, likes and comments from the YouTube Data API |
| X | Your posts and public metrics: impressions, likes, replies, reposts, quotes and bookmarks |

Tokens live in the OS credential store. SQLite stores the account row, post metadata, metrics and a token reference — never the token itself. **Disconnect** removes the local entry and stored token first, then asks the provider to revoke it; a provider outage cannot keep the token alive locally.

Press **Sync** after publishing, or let the weekly loop do it. A post needs 24 hours and 50 views before its engagement is treated as eligible; that keeps the first hour of noise out of the labels.

The tab shows each account's baseline — eligible posts, median views and median engagement — then the recent posts with views, engagement rate and a **win**, **miss** or **settling** pill. Something that is still settling has no label yet and contributes nothing to training; `GET /api/accounts/{id}/overview` also reports whether the account has enough labelled posts.

## Two different learners

### What you approve

Every approve/reject decision in the review panel is logged with the clip, its features and the policy version. After enough local decisions, a logistic re-ranker learns your taste and blends into the final score.

This learner answers *what you tend to keep*, not *what the audience watched*. It can overfit a small or inconsistent history, so it stays inert below its threshold and never overrides structural gates.

### What the audience watched

Every upload queued from this app records what the pipeline measured about the clip — features, signals and the judge's score — on the post, so those are the posts that train the personal performance model. Imported channel history is still synced and supplies the per-account baseline, but it has no clip features to learn from. The label is the post's **engagement rate**, not raw views:

```text
likes + 2.5 × comments + 4 × shares + 3 × saves
──────────────────────────────────────────────────
views
```

Each account needs at least **8 eligible posts** before its median splits them into positive and negative labels. The model is trained only after **30 full-feature posts** and at least **10 positives and 10 negatives**. It is evaluated on a time-ordered holdout by AUC, and promoted only when all of these hold:

- held-out AUC beats a reach-only baseline by at least **0.03**;
- a **200-permutation** test puts the result below **p = 0.05**;
- the gate passes on data the model did not train on.

A failed gate leaves the previous active model alone. **Retrain now** runs the same gate for the pooled account data; a passing model becomes the active ranker for every clip, so use it when that audience reflects what you want the ranker to learn. **Pause model** returns to approval-only ranking without deleting the model. History keeps every attempt's AUC, rows, positives and negatives, not just a green badge, so a promotion can be audited later — and an attempt that failed the gate cannot be activated by hand, through the interface or the API.

## How much the models may move a score

Learned signals are modifiers, never the whole ranking:

| Blend | Cap |
|---|---|
| Personal performance model alone | 0.20 |
| Taste model alone | 0.60 |
| Both active | 0.35 taste + 0.20 personal, **0.55 total** |

The base pipeline score always keeps the remaining weight. The caps are enforced in code, not just written in this page. A model that cannot clear its gate does not get a smaller vote; it gets none.

## The weekly loop

A daemon checks once an hour whether seven days have passed since `weekly_learning.last_run`. On the first check after launch (20 seconds in), a due run starts. It:

1. syncs every connected account and records a snapshot;
2. refreshes engagement labels for eligible posts;
3. trains the global personal model against the time-ordered holdout;
4. promotes it only if every gate passes;
5. records the next run time and the per-account result.

**Sync and retrain now** on the Accounts tab does the same work immediately. The loop lives inside the desktop app, so it runs while the app is open and catches up on the first launch after seven days have passed; it cannot run while the app is closed. `CLIPPER_DISABLE_WEEKLY=1` turns the daemon off for development; the manual endpoint still works.

The loop is deliberately conservative. Seven days is enough time for short-form posts to find their audience, and a weekly cadence is slow enough that a single lucky post cannot retrain the ranker every few hours.

## Coaching suggestions

Open a clip's **Coach** tab in the Inspector. The coach reads the same evidence as the review panel and proposes concrete fixes, each with a receipt:

| Suggestion | Evidence |
|---|---|
| Trim dead air at the start | the timestamp and the silence length |
| Tighten a slow hook | the first sentence, its end time and the delay |
| Rewrite a weak hook | the transcript quote and the hook-lexicon/grounding result |
| Cut a mid-sentence ending | the last words and the cut time |
| Shorten an overlong clip | duration against the platform limit |
| Add a payoff | the missing-payoff gate and its reason |
| Fix low speech density | speech ratio and the quiet span |
| Check a low-confidence transcript | ASR confidence and the affected pages |
| Reduce caption density | words per second against the layout budget |

**Preview** shows the before/after. **Apply** is explicit. Trims go through the same `trim_clip` path as the manual control; hook edits are saved as a normal clip edit. Both keep the old value, so **Undo** restores it. Dismissing a suggestion hides it without changing the clip. Nothing is applied silently, and the coach never renders or publishes.

Suggestions are rules over observable evidence, not an LLM guessing at quality. They are useful when the transcript is good; a bad transcript produces both bad suggestions and bad captions.

## What this loop does not do

- It does not log into your accounts or scrape a profile page. Only OAuth on accounts you connect.
- It does not train on other people's accounts, and it does not upload the ranking model anywhere.
- It does not promise that a higher score means more views. The model predicts your observed engagement; that is a local correlation, not a virality forecast.
- It does not post without the Publish area's explicit **Queue upload** action, and it does not schedule posts.
- It does not learn from TikTok or Instagram yet; those analytics adapters are not enabled.

---

Back to [Publishing](Publishing.md) · [Reviewing Clips](Reviewing-Clips.md) · [Limitations](Limitations.md).
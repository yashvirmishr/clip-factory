# Publishing

Publishing sends a finished clip to **YouTube** or **X** from inside Clip Factory. It is the only flow that leaves the machine (apart from URL import, model downloads and analytics sync), and it needs a developer app of your own. There is no hosted OAuth relay in the middle.

## What you need

1. A rendered clip — publishing uploads the finished MP4, never the source. Render it in **Output → Render** first.
2. A developer app for the platform you want. Publishing ships no client credentials.
3. An operating-system credential store. Tokens go to Windows Credential Manager, macOS Keychain or Secret Service through `keyring`. If the store is unavailable, the Accounts tab says so and connecting stays off rather than writing tokens to disk.

## YouTube

In Google Cloud, create an OAuth client of type **Web application** and add this exact redirect URI:

```text
http://127.0.0.1:8756/api/connections/callback
```

Enable **YouTube Data API v3** and **YouTube Analytics API** on the project. The app asks for `youtube.upload`, `youtube.readonly` and `yt-analytics.readonly`.

## X

In the X developer portal, create an OAuth 2.0 **confidential** client and add the same callback URI:

```text
http://127.0.0.1:8756/api/connections/callback
```

The app asks for `tweet.read`, `tweet.write`, `users.read`, `media.write` and `offline.access`. App permissions and the account's plan must allow posting and reading public metrics. X bills per API use; check the current plan before uploading a batch.

## Connecting

Open **Publish → Accounts**, choose YouTube or X, paste the client ID and secret, and press **Connect**. The tab shows the callback URL with a copy button: it embeds port 8756, so a backend running on another port needs that URL registered with the provider as well. The consent page opens in a browser tab. Approving it lands on the loopback callback, stores the account and shows a confirmation page. Return to Clip Factory; the Accounts tab refreshes when the window regains focus.

The client secret and token bundle are stored in the credential store, not in SQLite or the config file. A code expires after ten minutes. **Disconnect** revokes the token where the provider supports revocation and removes the local account. TikTok and Instagram are listed so the boundary is visible, but their upload adapters are not enabled yet.

## The draft

| Field | Notes |
|---|---|
| **Title** | YouTube only. Prefilled from the clip's title, then the hook. Capped at 100 characters. |
| **Post text / description** | Prefilled from the hook. YouTube allows 5000 characters; X allows 280 after hashtags. |
| **Hashtags** | Space- or comma-separated, `#` optional. YouTube keeps 15; X keeps 10. X is public only. |
| **Visibility** | YouTube: private, unlisted or public. X: public. Private is the YouTube default on purpose. |
| **Audience** | YouTube requires a made-for-kids declaration on every upload; the toggle is that declaration. |
| **Schedule** | Optional date and time. YouTube holds the private upload and publishes it natively; X stays queued locally until that time. Leave it empty to upload now. |

**Check against YouTube limits** (the button names the platform) validates the draft against the same rules the upload enforces — duration, size, aspect, caption and title length, hashtag count. It never uploads. **Queue upload** does, or **Schedule for YouTube** when a time is set.

Scheduling behaves differently by platform because the platforms do. YouTube accepts `publishAt` on a private video, so the upload happens now and YouTube releases it at the chosen time. X has no native scheduling, so the job stays in the local queue with `scheduled_at` set and uploads when the time arrives — which means the app must be running then. A time in the past is rejected rather than treated as "now".

YouTube Shorts are capped at three minutes and must be vertical or square. X accepts a longer file at the API level, but this app caps the draft at 140 seconds so it stays a short. The server, not the browser, is the authority; the UI shows the returned issues.

## The queue

Uploads are durable jobs in SQLite, so closing the panel does not cancel one. Recent uploads show their state:

- **queued** — waiting for the single background worker;
- **scheduled** — queued with a future upload time; the queue shows how long until it runs;
- **running** — uploading;
- **done** — a link to the post, when the platform returned one;
- **failed** — the reason, with **Retry**;
- **cancelled** — stopped before upload finished, retryable.

Retryable failures back off up to an hour and are retried up to three times. A scheduler checks due jobs every 20 seconds, so a transient 429 or 503 does not need the app to be restarted. A job interrupted by a crash is returned to `retry` on the next launch with a message saying the app stopped; the finalize step checks with the platform before deciding whether the bytes already landed. The file path is kept, so retrying does not need a re-render.

**Retry** is for a `failed` or `cancelled` upload. A job that is still running cannot be retried, and neither can one that already reached `done`: posting the same file twice means a new render and a new job, so a retry can never duplicate a post.

Only one upload runs at a time, by the same resource governor that serializes analysis and rendering.

A finished upload records the feature vector, signals and judge score the clip carried, so the post can join the performance model once its engagement settles. Posts imported from an existing channel have no such vector and only contribute the per-account baseline. See [Learning from your posts](Learning.md).

## What is not here

- **No TikTok or Instagram upload.** Their OAuth entries exist, but `POST /api/publish` refuses them with a clear message. Use the Output tab's **Handoff** section for now.
- **No scheduling calendar.** Each publish form takes one time; there is no week view, no recurring slot and no bulk rescheduling.
- **No multi-platform posting in one action.** One draft, one account, one upload.
- **No title/hook generation for the platform.** Editing the draft text is manual; the hook and title come from the analysis.
- **No hosted callback.** Each user brings a developer app. That keeps tokens on the machine and keeps the project free of a credential relay.

Views and engagement are pulled back by the weekly loop or the **Sync** button on the Accounts tab; see [Learning from your posts](Learning.md).

---

Back to [Learning from your posts](Learning.md) · [Rendering and Export](Rendering-and-Export.md).

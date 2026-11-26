# Publishing

Publishing sends a finished clip to YouTube from inside Clip Factory. It is the only flow that leaves the machine, and it is the only one that needs an account of your own.

## What you need

1. A rendered clip — publishing uploads the finished MP4, never the source. Render it in **Output → Render** first; the publish section fills in once the render finishes.
2. A Google OAuth client. Publishing does not ship credentials. In Google Cloud, create an OAuth client of type **Web application** and add this exact redirect URI:

   ```text
   http://127.0.0.1:8756/api/connections/callback
   ```

   Enable the **YouTube Data API v3** on the same project.
3. An operating-system credential store. Tokens go to the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service on Linux). If the store is unavailable, the panel says so and stays off rather than writing tokens to disk.

## Connecting

Paste the client ID and secret into the publish section and press **Connect YouTube**. The consent page opens in a browser tab; approving it lands on the loopback callback, which stores the account and shows a confirmation page. Return to the app — the account appears in the panel. The client secret is stored in the credential store, not in the app's config.

If the consent page is closed early or the code expires (ten minutes), press **Connect YouTube** again. **Disconnect** revokes and removes the account.

## The draft

| Field | Notes |
|---|---|
| **Title** | Prefilled from the clip's title, then the hook. Capped at 100 characters. |
| **Description** | Prefilled from the hook. Capped at the platform's limit (5000 for YouTube). |
| **Hashtags** | Space- or comma-separated, `#` optional. Up to 15 are kept. |
| **Visibility** | Private, unlisted or public. Private is the default on purpose. |
| **Audience** | YouTube requires a made-for-kids declaration on every upload; the toggle is that declaration. |

**Check against YouTube limits** validates the draft against the same rules the upload enforces — duration, size, aspect, caption and title length, hashtag count. It never uploads. **Queue upload** does.

## The queue

Uploads are queued jobs, so closing the panel does not cancel one. Recent uploads show their state:

- **queued** — waiting for the single background worker;
- **running** — uploading;
- **done** — a link to the post, when the platform returned one;
- **failed** — the reason, with **Retry**;
- **cancelled** — stopped before upload finished, retryable.

Uploads are retried up to three times with backoff. A failed job keeps the file path, so a retry does not need a re-render.

## What is not here

- **Only YouTube** is enabled. The account, limit and queue code has entries for X, TikTok and Instagram, but the upload adapters are not implemented; the API refuses those platforms with a clear message. Export and share locally instead.
- **No scheduling calendar.** A `scheduled_at` field exists in the API and is passed through to YouTube as `publishAt`, but the UI does not expose a date picker.
- **No analytics pull-in.** Views and retention are not imported; the personal-performance tables exist, but nothing here fills them.
- **No multi-platform posting in one action.** One draft, one account, one upload.
- **No title/hook generation for the platform.** Editing the draft text is manual; the hook and title come from the analysis.

See [Limitations](Limitations.md) for the wider list.

---

Back to [Rendering and Export](Rendering-and-Export.md).

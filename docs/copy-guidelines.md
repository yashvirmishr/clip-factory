# Copy guidelines

Clip Factory talks to people who cut videos, not people who train models. Every
word on screen should be one they could say out loud to a friend.

## The rules

1. **Say the everyday word.** "Clip", "video", "captions", "computer".
   Not "candidate", "asset", "media item", "artifact".
2. **Name what it does, not how.** "Reads the speech" beats "runs ASR".
   "Ranks the moments" beats "LLM scoring". Method belongs in the tooltip.
3. **Keep the verb in the button.** "Render this clip", not "Render".
   "Add the demo video", not "Demo".
4. **Explain before you warn.** Every error names what happened, what it means
   for the person, and the one action that fixes it — in that order.
5. **Never imply a cloud.** Nothing is uploaded. Say "on this computer" when the
   distinction matters, and never say "sync", "account" or "sign in".
6. **One idea per sentence.** If a sentence has two dashes and a semicolon, split
   it.

## Words we use

| Instead of | Write |
| --- | --- |
| ASR, Whisper backend | reading the speech, speech model |
| LLM, scorer, stub scorer | ranking, ranking model, built-in rules |
| candidate | clip |
| gate | check |
| signals | what it noticed |
| telemetry | (say what is measured) |
| reel | clip list |
| triage | sort clips |
| theme atelier | theme studio |
| deterministic | (say what it actually does) |

## Tiers and model names

Tier letters (A–E) are internal. A person sees "This machine can run the medium
model comfortably", never "Tier B". Model files keep their own names because
people search for those names elsewhere.

## Errors

Bad: `LLM backend returned 500`

Good: `The model runner answered with an error. Clips were ranked with the
built-in rules instead.`

## Where this is enforced

`scripts/copy-lint.py` scans user-facing strings in `web/src` for the words in
the table above, and CI runs it on every pull request. Run it locally with:

```
python scripts/copy-lint.py
```

The lint is deliberately narrow: it checks words, not tone. A green run means
nobody shipped "candidate" into a heading; it does not mean the sentence is good.

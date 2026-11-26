# Languages

Clip Factory can read a transcript in any script. Whether it can *produce* one depends on the speech model you installed.

## What works without a model

- **Counting and timing.** Words are counted with a Unicode tokenizer. A Chinese sentence is measured in characters, not as one long word.
- **Sentence ends.** `.` `!` `?` plus `。` `！` `？` `؟` `۔` `।` end a sentence and pass the "ends on a sentence" check.
- **Subtitles.** Line wrapping uses display width, so wide glyphs take two columns. Fonts are chosen per script: Microsoft YaHei for Chinese, Yu Gothic for Japanese, Malgun Gothic for Korean, Nirmala UI for Devanagari and the other Indic scripts, Leelawadee UI for Thai, Noto Naskh Arabic for Arabic and Persian.
- **Checks.** The hallucination check compares the transcript's script with the language the analysis was asked for. A window written almost entirely in another script still blocks (that is the "thank you for watching" ghost); a window that merely mixes scripts warns. Japanese, Hindi and Russian transcripts pass.
- **Hook scoring.** The English word lists are not applied to other scripts, and the "hook in the first seconds" check flags instead of blocking when it has no lexicon to judge with.

## What needs a multilingual model

Transcription quality comes from the model, not the app. `ggml-base.en` and `ggml-small.en` are English-only: choosing Hindi with one of those installed produces English guesses. Models lists multilingual Whisper files as **Whisper base / small / medium / large-v3-turbo (multilingual)**; install one, activate it, and select the spoken language before analysing.

If the language is left on **Detect automatically**, whisper decides and the app records what it detected. The analysis header shows that language.

The bundled whisper binaries have no Vulkan or CUDA backend, so speech recognition is CPU-bound regardless of your graphics card.

## Translation

There is one translation direction: whisper's own `-tr` flag translates speech **into English**. Nothing in the app translates English into another language. For dual-language subtitles, import a second caption track rather than translating.

## YouTube caption tracks

A YouTube URL can bring its own captions. Paste the URL, and the add sheet lists every track the video has — manual tracks first, then automatic ones marked `AUTO`. A manual track is exact text and timing for free; speech recognition is the fallback.

The track is stored with the source and used automatically the next time you analyse it.

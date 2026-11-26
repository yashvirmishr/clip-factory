#!/usr/bin/env python3
"""Flag internal vocabulary that leaked into user-facing copy.

Checks the words a person actually reads: JSX text and the usual copy props
(label, title, hint, placeholder, aria-label...). Code identifiers and CSS class
names are ignored on purpose, so a clean run stays meaningful.

Exit code 1 when something is found. Pass --warn to report without failing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"
TICK = chr(96)
DOLLAR_BRACE = chr(36) + "{"

RULES = [
    (re.compile(r"\bLLM\b"), "ranking model"),
    (re.compile(r"\bASR\b"), "speech model"),
    (re.compile(r"\bVAD\b"), "speech detection"),
    (re.compile(r"\bcandidates?\b", re.I), "clip(s)"),
    (re.compile(r"\btelemetry\b", re.I), "say what is measured"),
    (re.compile(r"\batelier\b", re.I), "theme studio"),
    (re.compile(r"\btriage\b", re.I), "sort clips"),
    (re.compile(r"\bstub\b", re.I), "stand-in"),
    (re.compile(r"\bdeterministic\b", re.I), "say what it does"),
    (re.compile(r"\bgates?\b", re.I), "check(s)"),
    (re.compile(r"\bsignals?\b", re.I), "what it noticed"),
]

JSX_TEXT = re.compile(r">([^<>{}]+)<")
PROP = re.compile(
    r"""(?:label|title|hint|placeholder|eyebrow|message|detail|description|aria-label)
        \s*[:=]\s*(?:"([^"]*)"|'([^']*)'|\x00([^\x00]*)\x00)""",
    re.VERBOSE,
)


def strings_in(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.replace(TICK, "\x00")
        for match in JSX_TEXT.finditer(line):
            yield number, match.group(1)
        for match in PROP.finditer(line):
            value = next(group for group in match.groups() if group is not None)
            yield number, value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warn", action="store_true", help="report but exit 0")
    args = parser.parse_args()

    findings = 0
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in {".tsx", ".ts"} or path.name.endswith(".test.ts"):
            continue
        for number, raw in strings_in(path):
            text = " ".join(raw.split())
            if not text or DOLLAR_BRACE in text:
                continue
            for pattern, suggestion in RULES:
                hit = pattern.search(text)
                if not hit:
                    continue
                where = path.relative_to(ROOT).as_posix()
                print(f'{where}:{number}: "{text[:90]}" -> use {suggestion} (found "{hit.group(0)}")')
                findings += 1
                break  # one finding per string keeps the report readable

    if findings:
        print(f"\n{findings} line(s) of internal vocabulary found.")
        print("See docs/copy-guidelines.md for the words we use instead.")
        return 0 if args.warn else 1
    print("Copy check clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

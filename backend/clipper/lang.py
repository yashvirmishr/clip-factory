"""Script and language facts, without a dependency.

Everything here is derived from the Unicode character database in the standard
library. That is deliberate: the pipeline has to count words, measure subtitle
width and pick a font for a transcript it did not expect, and none of that is
worth a 400 MB model or a per-language regex.

The codes are whisper.cpp's (`-l`), which are ISO 639-1 except for `auto`.
"""

from __future__ import annotations

import unicodedata

# code -> (English name, native name, primary script, right-to-left)
LANGUAGES: dict[str, dict] = {
    "en": {"name": "English", "native": "English", "script": "latin", "rtl": False},
    "es": {"name": "Spanish", "native": "Español", "script": "latin", "rtl": False},
    "pt": {"name": "Portuguese", "native": "Português", "script": "latin", "rtl": False},
    "fr": {"name": "French", "native": "Français", "script": "latin", "rtl": False},
    "de": {"name": "German", "native": "Deutsch", "script": "latin", "rtl": False},
    "it": {"name": "Italian", "native": "Italiano", "script": "latin", "rtl": False},
    "nl": {"name": "Dutch", "native": "Nederlands", "script": "latin", "rtl": False},
    "sv": {"name": "Swedish", "native": "Svenska", "script": "latin", "rtl": False},
    "da": {"name": "Danish", "native": "Dansk", "script": "latin", "rtl": False},
    "no": {"name": "Norwegian", "native": "Norsk", "script": "latin", "rtl": False},
    "fi": {"name": "Finnish", "native": "Suomi", "script": "latin", "rtl": False},
    "pl": {"name": "Polish", "native": "Polski", "script": "latin", "rtl": False},
    "cs": {"name": "Czech", "native": "Čeština", "script": "latin", "rtl": False},
    "sk": {"name": "Slovak", "native": "Slovenčina", "script": "latin", "rtl": False},
    "hu": {"name": "Hungarian", "native": "Magyar", "script": "latin", "rtl": False},
    "ro": {"name": "Romanian", "native": "Română", "script": "latin", "rtl": False},
    "hr": {"name": "Croatian", "native": "Hrvatski", "script": "latin", "rtl": False},
    "tr": {"name": "Turkish", "native": "Türkçe", "script": "latin", "rtl": False},
    "vi": {"name": "Vietnamese", "native": "Tiếng Việt", "script": "latin", "rtl": False},
    "id": {"name": "Indonesian", "native": "Bahasa Indonesia", "script": "latin", "rtl": False},
    "ms": {"name": "Malay", "native": "Bahasa Melayu", "script": "latin", "rtl": False},
    "tl": {"name": "Tagalog", "native": "Tagalog", "script": "latin", "rtl": False},
    "sw": {"name": "Swahili", "native": "Kiswahili", "script": "latin", "rtl": False},
    "ru": {"name": "Russian", "native": "Русский", "script": "cyrillic", "rtl": False},
    "uk": {"name": "Ukrainian", "native": "Українська", "script": "cyrillic", "rtl": False},
    "bg": {"name": "Bulgarian", "native": "Български", "script": "cyrillic", "rtl": False},
    "el": {"name": "Greek", "native": "Ελληνικά", "script": "greek", "rtl": False},
    "ar": {"name": "Arabic", "native": "العربية", "script": "arabic", "rtl": True},
    "fa": {"name": "Persian", "native": "فارسی", "script": "arabic", "rtl": True},
    "ur": {"name": "Urdu", "native": "اردو", "script": "arabic", "rtl": True},
    "he": {"name": "Hebrew", "native": "עברית", "script": "hebrew", "rtl": True},
    "hi": {"name": "Hindi", "native": "हिन्दी", "script": "devanagari", "rtl": False},
    "mr": {"name": "Marathi", "native": "मराठी", "script": "devanagari", "rtl": False},
    "bn": {"name": "Bengali", "native": "বাংলা", "script": "bengali", "rtl": False},
    "pa": {"name": "Punjabi", "native": "ਪੰਜਾਬੀ", "script": "gurmukhi", "rtl": False},
    "gu": {"name": "Gujarati", "native": "ગુજરાતી", "script": "gujarati", "rtl": False},
    "ta": {"name": "Tamil", "native": "தமிழ்", "script": "tamil", "rtl": False},
    "te": {"name": "Telugu", "native": "తెలుగు", "script": "telugu", "rtl": False},
    "kn": {"name": "Kannada", "native": "ಕನ್ನಡ", "script": "kannada", "rtl": False},
    "ml": {"name": "Malayalam", "native": "മലയാളം", "script": "malayalam", "rtl": False},
    "th": {"name": "Thai", "native": "ไทย", "script": "thai", "rtl": False},
    "zh": {"name": "Chinese", "native": "中文", "script": "han", "rtl": False},
    "ja": {"name": "Japanese", "native": "日本語", "script": "kana", "rtl": False},
    "ko": {"name": "Korean", "native": "한국어", "script": "hangul", "rtl": False},
    "auto": {"name": "Detect automatically", "native": "Detect automatically", "script": "", "rtl": False},
}

SCRIPTS = (
    "latin", "greek", "cyrillic", "hebrew", "arabic", "devanagari", "bengali",
    "gurmukhi", "gujarati", "tamil", "telugu", "kannada", "malayalam", "thai",
    "han", "kana", "hangul",
)

_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "latin": ((0x0041, 0x024F), (0x1E00, 0x1EFF)),
    "greek": ((0x0370, 0x03FF), (0x1F00, 0x1FFF)),
    "cyrillic": ((0x0400, 0x052F),),
    "hebrew": ((0x0590, 0x05FF),),
    "arabic": ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
    "devanagari": ((0x0900, 0x097F),),
    "bengali": ((0x0980, 0x09FF),),
    "gurmukhi": ((0x0A00, 0x0A7F),),
    "gujarati": ((0x0A80, 0x0AFF),),
    "tamil": ((0x0B80, 0x0BFF),),
    "telugu": ((0x0C00, 0x0C7F),),
    "kannada": ((0x0C80, 0x0CFF),),
    "malayalam": ((0x0D00, 0x0D7F),),
    "thai": ((0x0E00, 0x0E7F),),
    "han": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F)),
    "kana": ((0x3040, 0x30FF),),
    "hangul": ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF)),
}

# Scripts written without spaces between words: joining tokens must not insert
# one, or every caption line acquires gaps that do not exist in the language.
UNSPACED_SCRIPTS = frozenset({"han", "kana", "thai"})

_CASED_SCRIPTS = frozenset({"latin", "greek", "cyrillic"})

_SENTENCE_END = frozenset(".!?…。！？؟۔।॥")
_TRAILING = "\"'”’»)]}」』】"


def normalise(code: str | None) -> str:
    """`zh-Hans`, `pt_BR`, `EN` -> a whisper code we know."""
    if not code:
        return "auto"
    value = str(code).strip().lower().replace("_", "-")
    if not value:
        return "auto"
    if value in LANGUAGES:
        return value
    base_code = value.split("-", 1)[0]
    return base_code if base_code in LANGUAGES else value


def base(code: str | None) -> str:
    """The language part of a BCP-47 tag, lowercased: `pt-BR` -> `pt`."""
    value = (code or "").strip().lower().replace("_", "-")
    return value.split("-", 1)[0]


def script_for_language(code: str | None) -> str:
    entry = LANGUAGES.get(normalise(code))
    return entry["script"] if entry else ""


def is_rtl(code: str | None) -> bool:
    entry = LANGUAGES.get(normalise(code))
    return bool(entry and entry["rtl"])


def cased(script: str) -> bool:
    return script in _CASED_SCRIPTS


def _script_of_char(char: str) -> str:
    point = ord(char)
    for script, ranges in _RANGES.items():
        for low, high in ranges:
            if low <= point <= high:
                return script
    return ""


def script_of_char(char: str) -> str:
    return _script_of_char(char)


def scripts_for(expected: str) -> frozenset[str]:
    """Scripts that count as correct for one language."""
    if expected in {"han", "kana"}:
        return frozenset({"han", "kana"})
    return frozenset({expected}) if expected else frozenset()


def script_switch_ratio(text: str, expected: str) -> float:
    """Share of letters written in a script other than the expected one."""
    allowed = scripts_for(expected)
    letters = [char for char in text if char.isalpha()]
    if not letters or not allowed:
        return 0.0
    other = sum(1 for char in letters if _script_of_char(char) not in allowed)
    return other / len(letters)


def script_of(text: str) -> str:
    """The dominant script of a piece of text: latin, han, mixed, none..."""
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue
        script = _script_of_char(char)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return "none"
    if counts.get("kana"):
        # Japanese mixes kanji and kana; kana is the identifying half.
        return "kana"
    total = sum(counts.values())
    script, count = max(counts.items(), key=lambda item: item[1])
    return script if count / total >= 0.8 else "mixed"


def _is_word_char(char: str) -> bool:
    # Combining marks belong to the letter they sit on: dropping them turns
    # "नमस्ते" into fragments that no longer read as the word it is.
    return char.isalnum() or unicodedata.category(char).startswith("M")


def tokenize(text: str) -> list[str]:
    """Unicode words, with one token per character for Han and kana runs."""
    if not text:
        return []
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        word = "".join(buffer).strip("'’")
        buffer.clear()
        if not word:
            return
        if any(_script_of_char(char) in {"han", "kana"} for char in word):
            tokens.extend(char for char in word if char.isalnum())
        else:
            tokens.append(word)

    for char in text.lower():
        if _is_word_char(char):
            buffer.append(char)
        elif char in "'’" and buffer:
            buffer.append(char)
        else:
            flush()
    flush()
    return tokens


def join_tokens(tokens: list[str], lang: str | None) -> str:
    script = script_for_language(lang) or script_of(" ".join(tokens))
    separator = "" if script in UNSPACED_SCRIPTS else " "
    return separator.join(tokens).strip()


def display_width(text: str) -> int:
    """Columns a subtitle renderer will spend, not code points."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def ends_sentence(token: str) -> bool:
    value = token.rstrip(_TRAILING).strip()
    return bool(value) and value[-1] in _SENTENCE_END


def font_for(script: str) -> list[str]:
    """Windows families that actually carry the script, best first."""
    families = {
        "latin": ["Segoe UI", "Arial"],
        "cyrillic": ["Segoe UI", "Arial"],
        "greek": ["Segoe UI", "Arial"],
        "han": ["Microsoft YaHei", "SimSun"],
        "kana": ["Yu Gothic UI", "YuGothic", "Meiryo"],
        "hangul": ["Malgun Gothic"],
        "arabic": ["Noto Naskh Arabic", "Segoe UI"],
        "hebrew": ["Noto Sans Hebrew", "Segoe UI"],
        "devanagari": ["Nirmala UI"],
        "bengali": ["Nirmala UI"],
        "gurmukhi": ["Nirmala UI"],
        "gujarati": ["Nirmala UI"],
        "tamil": ["Nirmala UI"],
        "telugu": ["Nirmala UI"],
        "kannada": ["Nirmala UI"],
        "malayalam": ["Nirmala UI"],
        "thai": ["Leelawadee UI"],
    }
    return families.get(script, ["Segoe UI"])


def catalog() -> list[dict]:
    """The picker's payload: code, English name, native name, script."""
    return [
        {
            "code": code,
            "name": entry["name"],
            "native": entry["native"],
            "script": entry["script"],
            "rtl": entry["rtl"],
        }
        for code, entry in LANGUAGES.items()
    ]

"""Language codes, names, and the ALL_LANGS preset."""

from __future__ import annotations

# Play Store `hl` codes commonly used for reviews.
ALL_LANGS: list[str] = [
    "en",
    "es",
    "pt",
    "de",
    "fr",
    "it",
    "ru",
    "ja",
    "ko",
    "zh-CN",
    "zh-TW",
    "hi",
    "id",
    "tr",
    "ar",
    "vi",
    "th",
    "pl",
    "nl",
    "uk",
    "bn",
    "ta",
    "te",
    "mr",
    "gu",
    "kn",
    "ml",
    "pa",
    "ro",
    "cs",
    "sv",
    "hu",
    "el",
    "he",
    "ms",
    "fil",
    "fa",
    "ur",
    "sw",
    "no",
    "da",
    "fi",
]

# Lowercase name / alias → Play Store language code.
_NAME_TO_CODE: dict[str, str] = {
    "english": "en",
    "spanish": "es",
    "portuguese": "pt",
    "german": "de",
    "french": "fr",
    "italian": "it",
    "russian": "ru",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh-CN",
    "simplified chinese": "zh-CN",
    "traditional chinese": "zh-TW",
    "hindi": "hi",
    "indonesian": "id",
    "turkish": "tr",
    "arabic": "ar",
    "vietnamese": "vi",
    "thai": "th",
    "polish": "pl",
    "dutch": "nl",
    "ukrainian": "uk",
    "bengali": "bn",
    "tamil": "ta",
    "telugu": "te",
    "marathi": "mr",
    "gujarati": "gu",
    "kannada": "kn",
    "malayalam": "ml",
    "punjabi": "pa",
    "romanian": "ro",
    "czech": "cs",
    "swedish": "sv",
    "hungarian": "hu",
    "greek": "el",
    "hebrew": "he",
    "malay": "ms",
    "filipino": "fil",
    "tagalog": "fil",
    "persian": "fa",
    "farsi": "fa",
    "urdu": "ur",
    "swahili": "sw",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
}

# Known codes (case-normalized lookup).
_CODE_SET: dict[str, str] = {c.lower(): c for c in ALL_LANGS}
_CODE_SET.update(
    {
        "zh-cn": "zh-CN",
        "zh-tw": "zh-TW",
        "zh": "zh-CN",
    }
)


class InvalidLanguageError(ValueError):
    pass


def resolve_language_token(token: str) -> str:
    """Map a single code or name to a Play Store language code."""
    raw = token.strip()
    if not raw:
        raise InvalidLanguageError("Empty language token.")
    lower = raw.lower()
    if lower in _CODE_SET:
        return _CODE_SET[lower]
    if lower in _NAME_TO_CODE:
        return _NAME_TO_CODE[lower]
    # Direct case match for hyphenated codes like zh-CN
    if raw in ALL_LANGS:
        return raw
    supported = ", ".join(sorted(set(list(_NAME_TO_CODE) + ALL_LANGS)))
    raise InvalidLanguageError(
        f"Unknown language {token!r}. Use a code (en, hi) or name (hindi, german). "
        f"Supported: {supported}"
    )


def parse_langs(value: str) -> list[str]:
    """
    Parse --lang value.

    Accepts: 'any', 'en', 'hindi', 'en,hi', 'english,hindi'
    """
    raw = value.strip()
    if not raw:
        raise InvalidLanguageError("Language cannot be empty.")
    if raw.lower() in {"any", "all", "*"}:
        return list(ALL_LANGS)

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise InvalidLanguageError("Language cannot be empty.")

    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        code = resolve_language_token(part)
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def language_label(code: str) -> str:
    for name, c in _NAME_TO_CODE.items():
        if c == code:
            return f"{name.title()} ({code})"
    return code

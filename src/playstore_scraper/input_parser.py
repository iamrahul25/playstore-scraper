"""Normalize package ID / Play Store URL → app_id."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


class InvalidAppInputError(ValueError):
    pass


@dataclass(frozen=True)
class AppInput:
    app_id: str
    lang_from_url: str | None = None
    country_from_url: str | None = None


def _looks_like_url(s: str) -> bool:
    lower = s.lower()
    return (
        lower.startswith(("http://", "https://", "market://"))
        or "play.google.com" in lower
        or "play.app.goo.gl" in lower
    )


def _validate_package(app_id: str) -> str:
    if not PACKAGE_RE.match(app_id):
        raise InvalidAppInputError(
            f"Invalid package name: {app_id!r}\n"
            "Examples:\n"
            "  com.oakever.meowdoku\n"
            "  https://play.google.com/store/apps/details?id=com.oakever.meowdoku"
        )
    return app_id


def resolve_app_input(user_input: str, *, follow_redirects: bool = True) -> AppInput:
    """Parse a package ID or Play Store URL into AppInput."""
    s = user_input.strip().strip("\"'")
    if not s:
        raise InvalidAppInputError(
            "Empty input. Provide a package name or Play Store URL.\n"
            "Examples:\n"
            "  com.oakever.meowdoku\n"
            "  https://play.google.com/store/apps/details?id=com.oakever.meowdoku"
        )

    if not _looks_like_url(s):
        return AppInput(app_id=_validate_package(s))

    # market://details?id=...
    if s.lower().startswith("market://"):
        parsed = urlparse(s)
        qs = parse_qs(parsed.query)
        ids = qs.get("id", [])
        if not ids:
            raise InvalidAppInputError("market:// URL has no id= parameter.")
        return AppInput(app_id=_validate_package(ids[0]))

    # Short links: resolve redirects
    if "play.app.goo.gl" in s.lower() and follow_redirects:
        try:
            import httpx

            with httpx.Client(follow_redirects=True, timeout=15.0) as client:
                resp = client.head(s if "://" in s else f"https://{s}")
                s = str(resp.url)
        except Exception as exc:  # noqa: BLE001
            raise InvalidAppInputError(
                f"Could not resolve short link {user_input!r}: {exc}"
            ) from exc

    if "://" not in s:
        s = "https://" + s

    parsed = urlparse(s)
    qs = parse_qs(parsed.query)
    ids = qs.get("id", [])
    if not ids:
        raise InvalidAppInputError(
            f"URL has no id= parameter: {user_input!r}\n"
            "Expected something like:\n"
            "  https://play.google.com/store/apps/details?id=com.oakever.meowdoku"
        )

    hl = qs.get("hl", [None])[0]
    gl = qs.get("gl", [None])[0]
    return AppInput(
        app_id=_validate_package(ids[0]),
        lang_from_url=hl.lower() if hl else None,
        country_from_url=gl.lower() if gl else None,
    )


def resolve_app_id(user_input: str) -> str:
    return resolve_app_input(user_input).app_id

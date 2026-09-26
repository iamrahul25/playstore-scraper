"""Normalize Play Store review arrays into dicts."""

from __future__ import annotations

from typing import Any

from playstore_scraper.utils import dig, unix_to_iso


def normalize_review(
    arr: list,
    *,
    lang: str,
    country: str,
    sort: str,
    star_filter: int | None,
    stream_id: str,
) -> dict[str, Any]:
    at_unix = dig(arr, 5, 0)
    replied_unix = dig(arr, 7, 2, 0)
    version = dig(arr, 10)

    return {
        "reviewId": dig(arr, 0),
        "userName": dig(arr, 1, 0),
        "userImage": dig(arr, 1, 1, 3, 2),
        "score": dig(arr, 2),
        "content": dig(arr, 4),
        "thumbsUpCount": dig(arr, 6) or 0,
        "reviewCreatedVersion": version,
        "appVersion": version,
        "at": unix_to_iso(at_unix),
        "atUnix": int(at_unix) if at_unix is not None else None,
        "replyContent": dig(arr, 7, 1),
        "repliedAt": unix_to_iso(replied_unix),
        "source": {
            "lang": lang,
            "country": country,
            "sort": sort,
            "starFilter": star_filter,
            "firstSeenStream": stream_id,
        },
        "raw": arr,
    }

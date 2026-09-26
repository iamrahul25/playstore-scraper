"""Play Store batchexecute reviews RPC (id: oCPfdb)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

# Current Play Store reviews RPC id (was UsvDTd in older clients).
RPC_ID = "oCPfdb"

SORT = {"relevant": 1, "newest": 2, "rating": 3}

BATCHEXECUTE_URL = (
    "https://play.google.com/_/PlayStoreUi/data/batchexecute?hl={lang}&gl={country}"
)


class RpcDecodeError(ValueError):
    def __init__(self, message: str, body_preview: str = "") -> None:
        super().__init__(message)
        self.body_preview = body_preview


def build_reviews_url(lang: str, country: str) -> str:
    return BATCHEXECUTE_URL.format(lang=lang, country=country)


def build_reviews_payload(
    app_id: str,
    sort: int | str,
    count: int,
    token: str | None = None,
    score: int | None = None,
    device_id: int | None = None,
) -> str:
    """
    Build URL-encoded f.req body for the reviews RPC.

    Inner payload shape (current Play Store):
      [null, [2, sort, [count, null, token?], null,
              [null, score, null, null, null, null, null, null, device_id]],
       [app_id, 7]]
    """
    sort_int = SORT[sort] if isinstance(sort, str) else int(sort)

    page_spec: list[Any] = [count]
    if token is not None:
        page_spec.extend([None, token])

    filter_spec: list[Any] = [
        None,
        score,  # null = all stars
        None,
        None,
        None,
        None,
        None,
        None,
        device_id,  # null = all devices
    ]

    inner = [None, [2, sort_int, page_spec, None, filter_spec], [app_id, 7]]
    inner_json = json.dumps(inner, separators=(",", ":"), ensure_ascii=False)
    outer = [[[RPC_ID, inner_json, None, "generic"]]]
    outer_json = json.dumps(outer, separators=(",", ":"), ensure_ascii=False)
    return urlencode({"f.req": outer_json})


def decode_reviews_response(body: str) -> tuple[list[list], str | None]:
    """
    Decode a batchexecute response.

    Returns (review_arrays, next_token).
    """
    if not body or not body.strip():
        raise RpcDecodeError("Empty response body.")

    text = body.lstrip()
    if text.startswith(")]}'"):
        # Strip anti-XSSI prefix and following newlines
        text = text[4:].lstrip("\n\r")

    try:
        outer = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RpcDecodeError(
            f"Response is not valid JSON: {exc}", body_preview=body[:500]
        ) from exc

    if not isinstance(outer, list):
        raise RpcDecodeError(
            "Unexpected response root (expected array).", body_preview=body[:500]
        )

    payload_str: str | None = None
    for entry in outer:
        if (
            isinstance(entry, list)
            and len(entry) >= 3
            and entry[0] == "wrb.fr"
            and entry[1] == RPC_ID
        ):
            payload_str = entry[2]
            break

    if payload_str is None:
        # Sometimes the RPC id is nested differently; try first wrb.fr with a string payload
        for entry in outer:
            if (
                isinstance(entry, list)
                and len(entry) >= 3
                and entry[0] == "wrb.fr"
                and isinstance(entry[2], str)
            ):
                payload_str = entry[2]
                break

    if payload_str is None:
        raise RpcDecodeError(
            f"Could not find wrb.fr/{RPC_ID} payload in response.",
            body_preview=body[:500],
        )

    try:
        inner = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        raise RpcDecodeError(
            f"Inner payload is not valid JSON: {exc}", body_preview=payload_str[:500]
        ) from exc

    if not isinstance(inner, list):
        raise RpcDecodeError(
            "Inner payload is not a list.", body_preview=str(inner)[:500]
        )

    if len(inner) == 0:
        return [], None

    reviews_raw = inner[0]
    if reviews_raw is None:
        reviews = []
    elif isinstance(reviews_raw, list):
        reviews = [r for r in reviews_raw if isinstance(r, list)]
    else:
        reviews = []

    token: str | None = None
    try:
        candidate = inner[-2][-1]
        if isinstance(candidate, str) and candidate:
            token = candidate
    except (IndexError, TypeError):
        try:
            candidate = inner[-1][-1]
            if isinstance(candidate, str) and candidate:
                token = candidate
        except (IndexError, TypeError):
            token = None

    return reviews, token

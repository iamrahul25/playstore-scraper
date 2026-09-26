"""Fetch basic app metadata from the Play Store details page."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from playstore_scraper.http_client import HttpError, PlayStoreClient
from playstore_scraper.utils import dig

logger = logging.getLogger(__name__)


class AppNotFoundError(Exception):
    pass


def _extract_datasets(html: str) -> dict[str, Any]:
    datasets: dict[str, Any] = {}
    pattern = re.compile(
        r"AF_initDataCallback\({key:\s*'([^']+)',\s*hash:\s*'[^']*',\s*data:(.*?),\s*sideChannel:.*?}\);",
        re.DOTALL,
    )
    for match in pattern.finditer(html):
        key = match.group(1)
        raw = match.group(2)
        try:
            datasets[key] = json.loads(raw)
        except json.JSONDecodeError:
            continue
    return datasets


def fetch_app_info(
    client: PlayStoreClient,
    app_id: str,
    *,
    lang: str = "en",
    country: str = "us",
) -> dict[str, Any]:
    url = (
        f"https://play.google.com/store/apps/details?id={app_id}"
        f"&hl={lang}&gl={country}"
    )
    try:
        html, status = client.get_text(url, lang=lang)
    except HttpError as exc:
        if exc.status_code == 404:
            raise AppNotFoundError(f"App not found: {app_id}") from exc
        raise

    if status == 404 or "We're sorry, the requested URL was not found" in html:
        raise AppNotFoundError(f"App not found: {app_id}")

    datasets = _extract_datasets(html)
    ds5 = datasets.get("ds:5")

    info: dict[str, Any] = {
        "appId": app_id,
        "title": None,
        "developer": None,
        "score": None,
        "ratings": None,
        "reviews": None,
        "histogram": None,
        "installs": None,
        "url": url,
    }

    if ds5 is not None:
        # Paths from google-play-scraper ElementSpecs.Detail
        info["title"] = dig(ds5, 1, 2, 0, 0)
        info["developer"] = dig(ds5, 1, 2, 68, 0)
        info["score"] = dig(ds5, 1, 2, 51, 0, 1)
        info["ratings"] = dig(ds5, 1, 2, 51, 2, 1)
        info["reviews"] = dig(ds5, 1, 2, 51, 3, 1)
        info["installs"] = dig(ds5, 1, 2, 13, 0)
        hist = dig(ds5, 1, 2, 51, 1)
        if isinstance(hist, list) and len(hist) >= 6:
            try:
                info["histogram"] = {
                    "1": hist[1][1],
                    "2": hist[2][1],
                    "3": hist[3][1],
                    "4": hist[4][1],
                    "5": hist[5][1],
                }
            except (IndexError, TypeError):
                info["histogram"] = None

    # Fallback: scrape <title>
    if not info["title"]:
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s*-\s*Apps on Google Play\s*$", "", m.group(1)).strip()
            title = re.sub(r"\s*-\s*Google Play\s*$", "", title).strip()
            info["title"] = title or None

    if not info["title"] and not datasets:
        # Likely blocked or unknown page shape; don't hard-fail scraping
        logger.warning("Could not parse app details for %s; continuing", app_id)

    return info

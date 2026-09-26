"""Scrape configuration and count/sort parsing."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from playstore_scraper.languages import parse_langs

SortChoice = Literal["newest", "relevant", "rating", "all"]
SORT_CHOICES = ("newest", "relevant", "rating", "all")
SINGLE_SORTS = ("newest", "relevant", "rating")


class InvalidCountError(ValueError):
    pass


class InvalidSortError(ValueError):
    pass


_COUNT_SUFFIX = {
    "k": 1_000,
    "m": 1_000_000,
}


def parse_count(value: str | int | None) -> int | None:
    """
    Parse count input.

    Returns None for 'all' (unlimited). Accepts 1000, 1,000, 1k, 10k, 100k, 1m, all.
    """
    if value is None:
        return None
    if isinstance(value, int):
        if value <= 0:
            raise InvalidCountError("Count must be a positive integer or 'all'.")
        return value

    raw = str(value).strip().lower().replace(",", "").replace("_", "")
    if not raw:
        raise InvalidCountError("Count cannot be empty.")
    if raw in {"all", "*", "max", "unlimited"}:
        return None

    m = re.fullmatch(r"(\d+(?:\.\d+)?)([km])?", raw)
    if not m:
        raise InvalidCountError(
            f"Invalid count {value!r}. Use a number (100, 1000, 10k, 100000) or 'all'."
        )
    num = float(m.group(1))
    suffix = m.group(2)
    if suffix:
        num *= _COUNT_SUFFIX[suffix]
    n = int(num)
    if n <= 0 or n != num:
        raise InvalidCountError(
            f"Invalid count {value!r}. Must be a positive whole number or 'all'."
        )
    return n


def parse_sort(value: str | None) -> SortChoice:
    if value is None:
        return "newest"
    raw = value.strip().lower()
    aliases = {
        "new": "newest",
        "newest": "newest",
        "relevant": "relevant",
        "most relevant": "relevant",
        "most_relevant": "relevant",
        "rating": "rating",
        "ratings": "rating",
        "all": "all",
        "*": "all",
    }
    if raw not in aliases:
        raise InvalidSortError(
            f"Invalid sort {value!r}. Choose: newest, relevant, rating, or all."
        )
    return aliases[raw]  # type: ignore[return-value]


def _parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


class ScrapeConfig(BaseModel):
    app_id: str
    count: int | None = None  # None = all
    sort: SortChoice = "newest"
    langs: list[str] = Field(default_factory=lambda: ["en"])
    countries: list[str] = Field(default_factory=lambda: ["us"])
    star_filters: list[int | None] = Field(default_factory=lambda: [None, 5, 4, 3, 2, 1])
    page_size: int = 200
    max_pages_per_stream: int | None = None
    since: date | None = None
    until: date | None = None
    delay_seconds: float = 1.0
    max_retries: int = 6
    timeout_seconds: float = 30.0
    out_dir: Path = Path("data")
    save_raw_pages: bool = True
    compress_raw: bool = False
    resume: bool = True
    prune: bool = True
    pretty: bool = False
    proxy: str | None = None
    workers: int = 1
    engine: Literal["native", "library"] = "native"

    @field_validator("countries", mode="before")
    @classmethod
    def _normalize_countries(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            parts = [p.strip().lower() for p in v.split(",") if p.strip()]
            return parts or ["us"]
        return [str(c).strip().lower() for c in v]

    @field_validator("since", "until", mode="before")
    @classmethod
    def _coerce_date(cls, v: Any) -> date | None:
        return _parse_date(v)

    @model_validator(mode="after")
    def _adjust_page_size(self) -> ScrapeConfig:
        if self.count is not None:
            self.page_size = max(1, min(self.page_size, self.count, 200))
        else:
            self.page_size = max(1, min(self.page_size, 200))
        if self.workers < 1:
            self.workers = 1
        if self.workers > 4:
            self.workers = 4
        return self

    @property
    def sorts(self) -> list[str]:
        if self.sort == "all":
            return ["newest", "relevant", "rating"]
        return [self.sort]

    @property
    def count_label(self) -> str:
        return "all" if self.count is None else str(self.count)

    def config_hash(self) -> str:
        payload = {
            "app_id": self.app_id,
            "count": self.count,
            "sort": self.sort,
            "langs": self.langs,
            "countries": self.countries,
            "star_filters": self.star_filters,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "appId": self.app_id,
            "count": self.count_label,
            "sort": self.sort,
            "langs": self.langs,
            "countries": self.countries,
            "starFilters": self.star_filters,
            "pageSize": self.page_size,
            "delaySeconds": self.delay_seconds,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "prune": self.prune,
            "saveRawPages": self.save_raw_pages,
        }


def build_config(
    *,
    app_id: str,
    count: str | int | None = "all",
    sort: str | None = "newest",
    lang: str | None = "en",
    country: str = "us",
    no_star_split: bool = False,
    page_size: int = 200,
    delay: float = 1.0,
    out: str | Path = "data",
    no_raw: bool = False,
    compress_raw: bool = False,
    fresh: bool = False,
    no_prune: bool = False,
    pretty: bool = False,
    proxy: str | None = None,
    workers: int = 1,
    since: str | None = None,
    until: str | None = None,
    engine: str = "native",
    max_pages_per_stream: int | None = None,
) -> ScrapeConfig:
    parsed_count = parse_count(count if count is not None else "all")
    parsed_sort = parse_sort(sort)
    langs = parse_langs(lang if lang is not None else "en")
    star_filters: list[int | None]
    if no_star_split:
        star_filters = [None]
    else:
        star_filters = [None, 5, 4, 3, 2, 1]

    return ScrapeConfig(
        app_id=app_id,
        count=parsed_count,
        sort=parsed_sort,
        langs=langs,
        countries=country,
        star_filters=star_filters,
        page_size=page_size,
        max_pages_per_stream=max_pages_per_stream,
        since=since,
        until=until,
        delay_seconds=delay,
        out_dir=Path(out),
        save_raw_pages=not no_raw,
        compress_raw=compress_raw,
        resume=not fresh,
        prune=not no_prune,
        pretty=pretty,
        proxy=proxy,
        workers=workers,
        engine=engine,  # type: ignore[arg-type]
    )

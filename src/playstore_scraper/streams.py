"""Review stream definitions and matrix generation."""

from __future__ import annotations

from dataclasses import dataclass

from playstore_scraper.config import ScrapeConfig


@dataclass(frozen=True)
class Stream:
    lang: str
    country: str
    sort: str
    star_filter: int | None

    @property
    def id(self) -> str:
        star = "all" if self.star_filter is None else str(self.star_filter)
        return f"{self.lang}-{self.country}-{self.sort}-{star}"

    @property
    def is_primary(self) -> bool:
        """True for <sort>/all-stars streams (preferred first)."""
        return self.star_filter is None


def build_stream_matrix(cfg: ScrapeConfig) -> list[Stream]:
    """
    Build ordered streams from config.

    Single sort: <sort>/all then per-star (5→1).
    All sorts: newest → relevant → rating, each with all then per-star.
    Languages / countries expand the matrix.
    """
    streams: list[Stream] = []
    seen: set[str] = set()

    def add(lang: str, country: str, sort: str, star: int | None) -> None:
        s = Stream(lang=lang, country=country, sort=sort, star_filter=star)
        if s.id not in seen:
            seen.add(s.id)
            streams.append(s)

    # When count is limited and lang=any (many langs), still emit full matrix;
    # scraper does round-robin page-by-page.
    for country in cfg.countries:
        for lang in cfg.langs:
            for sort in cfg.sorts:
                # Primary (all stars) first
                if None in cfg.star_filters:
                    add(lang, country, sort, None)
                for star in cfg.star_filters:
                    if star is None:
                        continue
                    add(lang, country, sort, star)

    return streams


def group_streams_by_language(streams: list[Stream]) -> dict[str, list[Stream]]:
    grouped: dict[str, list[Stream]] = {}
    for s in streams:
        grouped.setdefault(s.lang, []).append(s)
    return grouped


def should_round_robin(cfg: ScrapeConfig) -> bool:
    """Interleave languages page-by-page when sampling a fixed count across many langs."""
    return cfg.count is not None and len(cfg.langs) > 1

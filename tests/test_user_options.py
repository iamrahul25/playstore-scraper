import pytest

from playstore_scraper.config import (
    InvalidCountError,
    InvalidSortError,
    build_config,
    parse_count,
    parse_sort,
)
from playstore_scraper.languages import InvalidLanguageError, parse_langs


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("all", None),
        ("ALL", None),
        ("100", 100),
        ("1,000", 1000),
        ("10k", 10_000),
        ("100k", 100_000),
        ("1m", 1_000_000),
        (2500, 2500),
    ],
)
def test_parse_count(raw, expected):
    assert parse_count(raw) == expected


def test_parse_count_invalid():
    with pytest.raises(InvalidCountError):
        parse_count("0")
    with pytest.raises(InvalidCountError):
        parse_count("-5")
    with pytest.raises(InvalidCountError):
        parse_count("abc")


def test_parse_sort():
    assert parse_sort("newest") == "newest"
    assert parse_sort("relevant") == "relevant"
    assert parse_sort("rating") == "rating"
    assert parse_sort("all") == "all"
    with pytest.raises(InvalidSortError):
        parse_sort("popular")


def test_parse_langs():
    assert parse_langs("en") == ["en"]
    assert parse_langs("hindi") == ["hi"]
    assert parse_langs("en,hi") == ["en", "hi"]
    assert parse_langs("english,german") == ["en", "de"]
    any_langs = parse_langs("any")
    assert "en" in any_langs and "hi" in any_langs and len(any_langs) > 10


def test_parse_langs_unknown():
    with pytest.raises(InvalidLanguageError):
        parse_langs("klingon")


def test_build_config_page_size_capped_by_count():
    cfg = build_config(app_id="com.foo.bar", count="100", sort="newest", lang="en")
    assert cfg.count == 100
    assert cfg.page_size == 100
    assert cfg.sorts == ["newest"]


def test_build_config_sort_all():
    cfg = build_config(app_id="com.foo.bar", count="all", sort="all", lang="en")
    assert cfg.count is None
    assert cfg.sorts == ["newest", "relevant", "rating"]

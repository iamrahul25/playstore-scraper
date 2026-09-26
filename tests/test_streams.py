from playstore_scraper.config import build_config
from playstore_scraper.streams import build_stream_matrix, should_round_robin


def test_single_sort_matrix():
    cfg = build_config(app_id="com.foo.bar", sort="newest", lang="en", count="all")
    streams = build_stream_matrix(cfg)
    ids = [s.id for s in streams]
    assert ids[0] == "en-us-newest-all"
    assert "en-us-newest-5" in ids
    assert all(s.sort == "newest" for s in streams)


def test_sort_all_matrix():
    cfg = build_config(
        app_id="com.foo.bar", sort="all", lang="en", count="all", no_star_split=True
    )
    streams = build_stream_matrix(cfg)
    sorts = [s.sort for s in streams]
    assert sorts == ["newest", "relevant", "rating"]


def test_round_robin_flag():
    cfg = build_config(app_id="com.foo.bar", count="1000", lang="en,hi")
    assert should_round_robin(cfg) is True
    cfg2 = build_config(app_id="com.foo.bar", count="all", lang="en,hi")
    assert should_round_robin(cfg2) is False

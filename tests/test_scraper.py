import json
from pathlib import Path

import httpx
import pytest
import respx

from playstore_scraper.config import build_config
from playstore_scraper.rpc import RPC_ID
from playstore_scraper.scraper import ReviewScraper


def _batchexecute_body(reviews: list, token: str | None) -> str:
    inner = [reviews, None, [None, token]]
    outer = [["wrb.fr", RPC_ID, json.dumps(inner), None, None, None, "generic"]]
    return ")]}'\n\n" + json.dumps(outer)


def _make_review(rid: str, score: int = 5) -> list:
    return [
        rid,
        ["User", [None, None, None, [None, None, "http://img"]]],
        score,
        None,
        f"content for {rid}",
        [1700000000],
        1,
        None,
        None,
        None,
        "1.0",
    ]


DETAILS_HTML = """
<html><head><title>Test App - Apps on Google Play</title></head>
<body>
<script>
AF_initDataCallback({key: 'ds:5', hash: '1', data:[[null,null,[null,null,[["Test App"],null,null,null,null,null,null,null,null,null,null,null,null,[null,null,null],null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,[null,[null,null,null],[null,null,1000]]]]]], sideChannel: {}});
</script>
</body></html>
"""


@respx.mock
def test_scraper_pagination_and_dedupe(tmp_path: Path):
    app_id = "com.example.testapp"

    # App details
    respx.get(url__regex=r".*store/apps/details.*").mock(
        return_value=httpx.Response(200, text=DETAILS_HTML)
    )

    page1 = [_make_review("gp:1"), _make_review("gp:2")]
    page2 = [_make_review("gp:2"), _make_review("gp:3")]  # gp:2 duplicate
    page3: list = []

    calls = {"n": 0}

    def reviews_route(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text=_batchexecute_body(page1, "TOK1"))
        if calls["n"] == 2:
            return httpx.Response(200, text=_batchexecute_body(page2, "TOK2"))
        return httpx.Response(200, text=_batchexecute_body(page3, None))

    respx.post(url__regex=r".*batchexecute.*").mock(side_effect=reviews_route)

    cfg = build_config(
        app_id=app_id,
        count="all",
        sort="newest",
        lang="en",
        country="us",
        no_star_split=True,
        delay=0,
        out=tmp_path,
        fresh=True,
        no_prune=True,
    )
    summary = ReviewScraper(cfg).run()

    assert summary["uniqueReviews"] == 3
    assert summary["duplicatesSkipped"] == 1
    reviews_path = Path(summary["outputDir"]) / "reviews.json"
    data = json.loads(reviews_path.read_text(encoding="utf-8"))
    ids = {r["reviewId"] for r in data}
    assert ids == {"gp:1", "gp:2", "gp:3"}


@respx.mock
def test_scraper_stops_at_count(tmp_path: Path):
    app_id = "com.example.count"

    respx.get(url__regex=r".*store/apps/details.*").mock(
        return_value=httpx.Response(200, text=DETAILS_HTML)
    )

    page = [_make_review(f"gp:{i}") for i in range(10)]
    respx.post(url__regex=r".*batchexecute.*").mock(
        return_value=httpx.Response(200, text=_batchexecute_body(page, "MORE"))
    )

    cfg = build_config(
        app_id=app_id,
        count="5",
        sort="newest",
        lang="en",
        no_star_split=True,
        delay=0,
        out=tmp_path,
        fresh=True,
    )
    summary = ReviewScraper(cfg).run()
    assert summary["uniqueReviews"] == 5
    assert summary["requested"] == 5


@pytest.mark.live
def test_live_one_page():
    """Opt-in live smoke test against Play Store."""
    from playstore_scraper.http_client import PlayStoreClient
    from playstore_scraper.rpc import build_reviews_payload, build_reviews_url, decode_reviews_response
    from playstore_scraper.parser import normalize_review

    with PlayStoreClient(delay_seconds=0.5, max_retries=3) as client:
        url = build_reviews_url("en", "us")
        body = build_reviews_payload("com.oakever.meowdoku", "newest", 50)
        text, status = client.post_form(url, body, lang="en")
        assert status == 200
        reviews, token = decode_reviews_response(text)
        assert len(reviews) > 0
        rec = normalize_review(
            reviews[0],
            lang="en",
            country="us",
            sort="newest",
            star_filter=None,
            stream_id="live",
        )
        assert rec["reviewId"]
        assert rec["score"] in {1, 2, 3, 4, 5}

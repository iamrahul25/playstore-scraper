from playstore_scraper.parser import normalize_review


def test_normalize_review():
    arr = [
        "gp:AOqpTOE123",
        ["Morgan", [None, None, None, [None, None, "https://img.example/a.png"]]],
        4,
        None,
        "I LOVED this game.",
        [1789740191],
        4,
        ["ignored", "Thanks!", [1789800000]],
        None,
        None,
        "1.12.0",
    ]
    rec = normalize_review(
        arr,
        lang="en",
        country="us",
        sort="newest",
        star_filter=None,
        stream_id="en-us-newest-all",
    )
    assert rec["reviewId"] == "gp:AOqpTOE123"
    assert rec["userName"] == "Morgan"
    assert rec["userImage"] == "https://img.example/a.png"
    assert rec["score"] == 4
    assert rec["content"] == "I LOVED this game."
    assert rec["thumbsUpCount"] == 4
    assert rec["appVersion"] == "1.12.0"
    assert rec["at"] == "2026-09-18T14:03:11Z" or rec["atUnix"] == 1789740191
    assert rec["replyContent"] == "Thanks!"
    assert rec["source"]["lang"] == "en"
    assert rec["raw"] is arr


def test_normalize_missing_fields():
    rec = normalize_review(
        ["gp:x"],
        lang="hi",
        country="in",
        sort="rating",
        star_filter=5,
        stream_id="hi-in-rating-5",
    )
    assert rec["reviewId"] == "gp:x"
    assert rec["userName"] is None
    assert rec["content"] is None
    assert rec["at"] is None
    assert rec["source"]["starFilter"] == 5
